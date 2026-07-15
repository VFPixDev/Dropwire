from datetime import datetime
from typing import Any, Optional

from src.twitter.models import MediaItem, Tweet, TweetStats
from src.twitter.parser import parse_date, parse_number


def _dig(data: dict[str, Any], *keys: str) -> Any:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _first_int(*values: Any) -> Optional[int]:
    for value in values:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            parsed = parse_number(value)
            if parsed is not None:
                return parsed
    return None


def _parse_media(raw_media: Any) -> list[MediaItem]:
    if not isinstance(raw_media, dict):
        return []

    media: list[MediaItem] = []
    for photo in raw_media.get("photos") or []:
        if isinstance(photo, dict):
            url = _first_text(photo.get("url"), photo.get("media_url_https"), photo.get("media_url"))
        else:
            url = _first_text(photo)
        if url:
            media.append(MediaItem(type="photo", url=url))

    for video in raw_media.get("videos") or []:
        if not isinstance(video, dict):
            url = _first_text(video)
            thumbnail_url = None
        else:
            variants = video.get("variants") or []
            url = _first_text(video.get("url"), video.get("media_url_https"), video.get("media_url"))
            thumbnail_url = _first_text(video.get("thumbnail_url"), video.get("poster")) or None
            if not url and isinstance(variants, list):
                mp4_variants = [v for v in variants if isinstance(v, dict) and _first_text(v.get("url"))]
                if mp4_variants:
                    best_variant = max(mp4_variants, key=lambda item: int(item.get("bitrate") or 0))
                    url = _first_text(best_variant.get("url"))
        if url:
            media.append(MediaItem(type="video", url=url, thumbnail_url=thumbnail_url))

    return media


def parse_tweet_api(data: dict[str, Any], original_url: str) -> Optional[Tweet]:
    """Парсит FxTwitter/FixTweet JSON API, если структура ответа распознана.

    API разных фронтендов менялся, поэтому парсер намеренно берёт несколько
    распространённых вариантов полей и возвращает None при недостатке данных.
    """
    tweet_data = data.get("tweet") if isinstance(data.get("tweet"), dict) else data
    if not isinstance(tweet_data, dict):
        return None

    raw_author = tweet_data.get("author")
    author: dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
    display_name = _first_text(
        author.get("name"),
        author.get("display_name"),
        tweet_data.get("author_name"),
        tweet_data.get("user_name"),
    )
    username = _first_text(
        author.get("screen_name"),
        author.get("username"),
        tweet_data.get("author_screen_name"),
        tweet_data.get("username"),
    )
    text = _first_text(tweet_data.get("text"), tweet_data.get("full_text"), tweet_data.get("description"))

    if not username or not text:
        return None
    if not display_name:
        display_name = username

    date = None
    for value in (tweet_data.get("created_at"), tweet_data.get("date"), tweet_data.get("created_timestamp")):
        if isinstance(value, str):
            date = parse_date(value)
            if date:
                break
    if date is None:
        date = datetime.now()

    raw_media = tweet_data.get("media")
    media = _parse_media(raw_media)

    raw_stats = tweet_data.get("stats")
    stats_source: dict[str, Any] = raw_stats if isinstance(raw_stats, dict) else tweet_data
    stats = TweetStats(
        replies=_first_int(
            _dig(stats_source, "replies"), _dig(stats_source, "reply_count"), _dig(stats_source, "replies_count")
        ),
        reposts=_first_int(
            _dig(stats_source, "retweets"), _dig(stats_source, "reposts"), _dig(stats_source, "retweet_count")
        ),
        likes=_first_int(
            _dig(stats_source, "likes"), _dig(stats_source, "favorite_count"), _dig(stats_source, "likes_count")
        ),
        views=_first_int(
            _dig(stats_source, "views"), _dig(stats_source, "view_count"), _dig(stats_source, "views_count")
        ),
    )

    return Tweet(
        display_name=display_name,
        username=username,
        url=original_url,
        text=text,
        date=date,
        media=media,
        stats=stats,
    )
