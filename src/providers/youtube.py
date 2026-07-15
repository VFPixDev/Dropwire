import logging
from datetime import datetime

import httpx
import isodate

from src.config import config
from src.models.media_card import Button, CardStats, MediaCard
from src.rendering.hashtags import build_hashtags
from src.providers.youtube_urls import extract_video_id

logger = logging.getLogger(__name__)


def format_count(count: int | None) -> str:
    if count is None:
        return "-"
    return f"{count:,}".replace(",", " ")


def format_seconds(total_seconds: int) -> str:
    hours, remainder = divmod(max(total_seconds, 0), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}"


def parse_duration_to_seconds(iso_duration: str) -> int:
    duration = isodate.parse_duration(iso_duration or "PT0S")
    return max(int(duration.total_seconds()), 0)


def short_description(value: str, max_len: int = 300, max_lines: int = 4) -> str:
    lines = [line.strip() for line in (value or "").replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return "-"
    text = "\n".join(lines[:max_lines])
    if len(lines) > max_lines and not text.endswith("..."):
        text = text.rstrip(".") + "..."
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


async def fetch_youtube_channel_tag(channel_id: str, client: httpx.AsyncClient) -> str | None:
    if not channel_id:
        return None

    params = {
        "part": "snippet",
        "id": channel_id,
        "key": config.YOUTUBE_API_KEY,
    }
    response = await client.get("https://www.googleapis.com/youtube/v3/channels", params=params)
    if response.status_code != 200:
        logger.warning("YouTube channel API error %s: %s", response.status_code, response.text[:300])
        return None

    data = response.json()
    items = data.get("items", [])
    if not items:
        return None

    snippet = items[0].get("snippet", {})
    custom_url = snippet.get("customUrl")
    if isinstance(custom_url, str) and custom_url.strip():
        return custom_url
    return None


async def fetch_youtube_card(url: str) -> MediaCard:
    video_id = extract_video_id(url)
    if not video_id:
        raise ValueError("Не удалось распознать YouTube-ссылку")
    if not config.YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY не задан")

    params = {
        "part": "snippet,contentDetails,statistics",
        "id": video_id,
        "key": config.YOUTUBE_API_KEY,
    }

    timeout = httpx.Timeout(20.0, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get("https://www.googleapis.com/youtube/v3/videos", params=params)
        if response.status_code != 200:
            logger.error("YouTube API error %s: %s", response.status_code, response.text[:500])
            raise RuntimeError("Ошибка YouTube API")

        data = response.json()
        items = data.get("items", [])
        if not items:
            raise ValueError("Видео не найдено или недоступно")

        item = items[0]
        snippet = item.get("snippet", {})
        statistics = item.get("statistics", {})
        content_details = item.get("contentDetails", {})
        live_status = snippet.get("liveBroadcastContent", "none")
        if live_status in {"live", "upcoming"}:
            raise ValueError("Стримы и премьеры пока не поддерживаются")

        duration_seconds = parse_duration_to_seconds(content_details.get("duration", "PT0S"))
        thumbnails = snippet.get("thumbnails", {})
        thumbnail_url = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )
        published_at = datetime.fromisoformat(snippet.get("publishedAt", "1970-01-01T00:00:00Z").replace("Z", "+00:00"))
        author = snippet.get("channelTitle", "Unknown")
        author_tag = await fetch_youtube_channel_tag(str(snippet.get("channelId", "")), client) or author

    return MediaCard(
        source="youtube",
        media_type="video",
        original_url=f"https://youtu.be/{video_id}",
        title=snippet.get("title", "Без названия"),
        text=None,
        author_name=author,
        author_handle=author_tag,
        published_at=published_at,
        thumbnail_url=thumbnail_url,
        duration_text=format_seconds(duration_seconds),
        stats=CardStats(
            views=int(statistics.get("viewCount", 0)),
            likes=int(statistics["likeCount"]) if "likeCount" in statistics else None,
        ),
        buttons=[
            Button(text="▶ Открыть в YouTube", url=f"https://youtu.be/{video_id}"),
            Button(text="📥 Скачать в ЛС", callback_data=f"download:youtube:{video_id}"),
        ],
        hashtags=build_hashtags("youtube", "video", author_tag),
    )
