from urllib.parse import urlparse

from src.models.media_card import Button, MediaCard
from src.providers.oembed import fetch_oembed
from src.rendering.hashtags import build_hashtags

SOUNDCLOUD_HOSTS = {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com", "on.soundcloud.com", "snd.sc"}


async def fetch_soundcloud_card(url: str) -> MediaCard:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").lower() not in SOUNDCLOUD_HOSTS:
        raise ValueError("Некорректная SoundCloud-ссылка")

    oembed = await fetch_oembed("https://soundcloud.com/oembed", url, "SoundCloud")
    author = oembed.author_name
    author_handle = _author_handle(oembed.author_url) or author
    title = _strip_author_suffix(oembed.title, author)
    media_type = _soundcloud_media_type(parsed.path)

    return MediaCard(
        source="soundcloud",
        media_type=media_type,
        original_url=url,
        title=title,
        author_name=author,
        author_handle=author_handle,
        thumbnail_url=oembed.thumbnail_url,
        buttons=[Button(text="▶ Открыть в SoundCloud", url=url)],
        hashtags=build_hashtags("soundcloud", media_type, author_handle),
    )


def _author_handle(author_url: str | None) -> str | None:
    if not author_url:
        return None
    segments = [segment for segment in urlparse(author_url).path.split("/") if segment]
    return segments[0] if segments else None


def _strip_author_suffix(title: str, author: str | None) -> str:
    if not author:
        return title
    suffix = f" by {author}"
    return title[: -len(suffix)].strip() if title.lower().endswith(suffix.lower()) else title


def _soundcloud_media_type(path: str) -> str:
    segments = [segment for segment in path.split("/") if segment]
    if "sets" in segments:
        return "playlist"
    if len(segments) <= 1:
        return "artist"
    return "music"
