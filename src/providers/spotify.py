import asyncio
import logging
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import httpx

from src.config import config
from src.models.media_card import Button, MediaCard
from src.providers.oembed import OEmbedData, fetch_oembed
from src.rendering.hashtags import build_hashtags

logger = logging.getLogger(__name__)

SPOTIFY_ENTITY_TYPES = {"track", "album", "playlist", "artist", "show", "episode"}
API_PATHS = {
    "track": "tracks",
    "album": "albums",
    "playlist": "playlists",
    "artist": "artists",
    "show": "shows",
    "episode": "episodes",
}
EMBED_ENTITY_RE = re.compile(r"/embed/(track|album|playlist|artist|show|episode)/([A-Za-z0-9]+)")

_access_token: str | None = None
_access_token_expires_at = 0.0
_token_lock = asyncio.Lock()


async def fetch_spotify_card(url: str) -> MediaCard:
    _validate_spotify_url(url)
    oembed = await fetch_oembed("https://open.spotify.com/oembed", url, "Spotify")
    entity_type, entity_id = extract_spotify_entity(url, oembed)
    metadata: dict = {}

    if entity_type and entity_id and config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET:
        try:
            metadata = await _fetch_spotify_metadata(entity_type, entity_id)
        except Exception as exc:
            logger.warning("Spotify Web API недоступен, используется oEmbed: %s", exc)

    title = str(metadata.get("name") or oembed.title).strip()
    author = _spotify_author(entity_type, metadata)
    thumbnail = _spotify_thumbnail(entity_type, metadata) or oembed.thumbnail_url
    duration_text = _format_duration_ms(metadata.get("duration_ms"))
    published_at = _spotify_published_at(entity_type, metadata)
    author_tag = author

    return MediaCard(
        source="spotify",
        media_type="podcast" if entity_type in {"show", "episode"} else "music",
        original_url=url,
        title=title,
        author_name=author,
        author_handle=author_tag,
        published_at=published_at,
        thumbnail_url=thumbnail,
        duration_text=duration_text,
        buttons=[Button(text="▶ Открыть в Spotify", url=url)],
        hashtags=build_hashtags(
            "spotify",
            "podcast" if entity_type in {"show", "episode"} else "music",
            author_tag,
        ),
    )


def extract_spotify_entity(url: str, oembed: OEmbedData | None = None) -> tuple[str | None, str | None]:
    segments = [segment for segment in urlparse(url).path.split("/") if segment]
    for index, segment in enumerate(segments[:-1]):
        if segment in SPOTIFY_ENTITY_TYPES:
            entity_id = segments[index + 1]
            if re.fullmatch(r"[A-Za-z0-9]+", entity_id):
                return segment, entity_id

    if oembed and oembed.html:
        match = EMBED_ENTITY_RE.search(oembed.html)
        if match:
            return match.group(1), match.group(2)
    return None, None


def _validate_spotify_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in {
        "open.spotify.com",
        "spotify.link",
    }:
        raise ValueError("Некорректная Spotify-ссылка")


async def _fetch_spotify_metadata(entity_type: str, entity_id: str) -> dict:
    token = await _get_spotify_access_token()
    timeout = httpx.Timeout(15.0, connect=8.0)
    endpoint = f"https://api.spotify.com/v1/{API_PATHS[entity_type]}/{entity_id}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
    if response.status_code != 200:
        raise RuntimeError(f"Spotify Web API HTTP {response.status_code}")
    if len(response.content) > config.PROVIDER_RESPONSE_MAX_KB * 1024:
        raise RuntimeError("Spotify Web API response is too large")
    return response.json()


async def _get_spotify_access_token() -> str:
    global _access_token, _access_token_expires_at
    if _access_token and time.monotonic() < _access_token_expires_at:
        return _access_token

    async with _token_lock:
        if _access_token and time.monotonic() < _access_token_expires_at:
            return _access_token
        timeout = httpx.Timeout(15.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.post(
                "https://accounts.spotify.com/api/token",
                data={"grant_type": "client_credentials"},
                auth=(config.SPOTIFY_CLIENT_ID, config.SPOTIFY_CLIENT_SECRET),
            )
        if response.status_code != 200:
            raise RuntimeError(f"Spotify auth HTTP {response.status_code}")
        payload = response.json()
        token = str(payload.get("access_token", ""))
        if not token:
            raise RuntimeError("Spotify auth response has no access token")
        expires_in = max(int(payload.get("expires_in", 3600)), 60)
        _access_token = token
        _access_token_expires_at = time.monotonic() + expires_in - 30
        return token


def _spotify_author(entity_type: str | None, metadata: dict) -> str | None:
    if entity_type in {"track", "album"}:
        artists = metadata.get("artists") or []
        names = [str(item.get("name", "")).strip() for item in artists if isinstance(item, dict)]
        return ", ".join(name for name in names if name)[:200] or None
    if entity_type == "artist":
        return str(metadata.get("name", "")).strip()[:200] or None
    if entity_type == "playlist":
        owner = metadata.get("owner") or {}
        return str(owner.get("display_name", "")).strip()[:200] or None
    if entity_type == "show":
        return str(metadata.get("publisher", "")).strip()[:200] or None
    if entity_type == "episode":
        show = metadata.get("show") or {}
        return str(show.get("publisher") or show.get("name") or "").strip()[:200] or None
    return None


def _spotify_thumbnail(entity_type: str | None, metadata: dict) -> str | None:
    image_owner = metadata.get("album") if entity_type == "track" else metadata
    images = image_owner.get("images", []) if isinstance(image_owner, dict) else []
    for image in images:
        if isinstance(image, dict) and image.get("url"):
            return str(image["url"])
    return None


def _spotify_published_at(entity_type: str | None, metadata: dict) -> datetime | None:
    owner = metadata.get("album") if entity_type == "track" else metadata
    if not isinstance(owner, dict):
        return None
    value = owner.get("release_date")
    if not isinstance(value, str):
        return None
    try:
        if len(value) == 4:
            return datetime(int(value), 1, 1)
        if len(value) == 7:
            return datetime.fromisoformat(f"{value}-01")
        return datetime.fromisoformat(value[:10])
    except ValueError:
        return None


def _format_duration_ms(value: object) -> str | None:
    try:
        total_seconds = max(int(value) // 1000, 0)
    except (TypeError, ValueError):
        return None
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"
