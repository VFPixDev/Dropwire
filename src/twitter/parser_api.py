from datetime import datetime, timezone
import math
from typing import Any, Optional

from src.twitter.models import MediaItem, Poll, PollOption, QuotedTweet, Tweet, TweetStats
from src.twitter.parser import parse_date, parse_number
from src.twitter.translate import valid_translation


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


def _optional_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except TypeError, ValueError, OverflowError:
        return None


def _best_video_url(item: dict[str, Any]) -> str:
    formats = item.get("formats") or item.get("variants") or []
    if isinstance(formats, list):
        candidates = []
        for value in formats:
            if not isinstance(value, dict):
                continue
            url = _first_text(value.get("url"))
            container = _first_text(value.get("container"), value.get("content_type"), "mp4").lower()
            if not url or "m3u8" in url.lower() or "mpegurl" in container or container == "m3u8":
                continue
            candidates.append(value)
        if candidates:
            h264 = [value for value in candidates if _first_text(value.get("codec"), "h264") == "h264"]
            pool = h264 or candidates
            best = max(
                pool,
                key=lambda value: (
                    _optional_int(value.get("bitrate")) or 0,
                    _optional_int(value.get("width")) or 0,
                    _optional_int(value.get("height")) or 0,
                ),
            )
            return _first_text(best.get("url"))
    return _first_text(
        item.get("url"),
        item.get("transcode_url"),
        item.get("media_url_https"),
        item.get("media_url"),
    )


def _parse_media_item(item: Any, fallback_type: str) -> Optional[MediaItem]:
    if isinstance(item, str):
        return MediaItem(type=fallback_type, url=item) if item else None
    if not isinstance(item, dict):
        return None

    raw_type = _first_text(item.get("type"), fallback_type).lower()
    media_type = {
        "gif": "animation",
        "animated_gif": "animation",
        "image": "photo",
        "mosaic_photo": "photo",
    }.get(raw_type, raw_type)
    if media_type not in {"photo", "video", "animation"}:
        media_type = fallback_type

    url = (
        _best_video_url(item)
        if media_type in {"video", "animation"}
        else _first_text(item.get("url"), item.get("media_url_https"), item.get("media_url"))
    )
    if not url:
        return None
    duration = _optional_int(item.get("duration"))
    if duration is None:
        duration_ms = _optional_int(item.get("duration_millis") or item.get("duration_ms"))
        duration = round(duration_ms / 1000) if duration_ms is not None else None

    return MediaItem(
        type=media_type,
        url=url,
        thumbnail_url=_first_text(item.get("thumbnail_url"), item.get("poster")) or None,
        width=_optional_int(item.get("width")),
        height=_optional_int(item.get("height")),
        duration=duration,
    )


def _parse_media(raw_media: Any) -> list[MediaItem]:
    if not isinstance(raw_media, dict):
        return []

    raw_all = raw_media.get("all")
    if isinstance(raw_all, list):
        # API v2 may put a generated mosaic into ``all`` while keeping the
        # original photos in ``photos``. A mosaic is only a preview and must
        # never replace the individual images used by Telegram collages.
        ordered = [
            _parse_media_item(item, "photo")
            for item in raw_all
            if not isinstance(item, dict) or item.get("type") != "mosaic_photo"
        ]
        parsed_all = [item for item in ordered if item is not None]
        if parsed_all:
            return parsed_all

    media: list[MediaItem] = []
    for photo in raw_media.get("photos") or []:
        parsed = _parse_media_item(photo, "photo")
        if parsed:
            media.append(parsed)

    for video in raw_media.get("videos") or []:
        parsed = _parse_media_item(video, "video")
        if parsed:
            media.append(parsed)

    external = _parse_media_item(raw_media.get("external"), "video")
    if external:
        media.append(external)

    return media


def _parse_date_value(raw: dict[str, Any]) -> Optional[datetime]:
    for value in (raw.get("created_at"), raw.get("date"), raw.get("created_timestamp")):
        if isinstance(value, str):
            parsed = parse_date(value)
            if parsed:
                return parsed
        if isinstance(value, (int, float)):
            try:
                return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None)
            except OverflowError, OSError, ValueError:
                pass
    return None


def _parse_reference(raw: Any) -> Optional[QuotedTweet]:
    if not isinstance(raw, dict):
        return None
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    username = _first_text(
        author.get("screen_name"), author.get("username"), raw.get("screen_name"), raw.get("username")
    )
    display_name = _first_text(author.get("name"), author.get("display_name"), raw.get("name"), username)
    display_name = _first_text(display_name, raw.get("display_name"), username)
    tweet_id = _first_text(raw.get("id"), raw.get("tweet_id"), raw.get("status_id"), raw.get("status")) or None
    url = _first_text(raw.get("url"))
    if not url and username and tweet_id:
        url = f"https://x.com/{username}/status/{tweet_id}"
    if not username and url:
        parts = url.split("/")
        if len(parts) >= 4:
            username = parts[3]
    text = _first_text(raw.get("text"), raw.get("full_text"), raw.get("description"))
    media = _parse_media(raw.get("media"))
    translated_text, source_language = _parse_translation(raw)
    if not username or not (text or media or tweet_id):
        return None
    return QuotedTweet(
        display_name=display_name or username,
        username=username,
        url=url or f"https://x.com/{username}",
        text=text,
        date=_parse_date_value(raw),
        media=media,
        tweet_id=tweet_id,
        translated_text=translated_text,
        source_language=source_language,
    )


def _parse_translation(raw: dict[str, Any]) -> tuple[str | None, str | None]:
    translation = raw.get("translation")
    if not isinstance(translation, dict):
        return None, None
    if translation.get("error") or translation.get("success") is False:
        return None, None
    translated_text = valid_translation(_first_text(translation.get("text")))
    if translated_text is None:
        return None, None
    source_language = (
        _first_text(
            translation.get("source_lang_en"),
            translation.get("source_lang"),
        )
        or None
    )
    return translated_text, source_language


def _parse_poll(raw: Any) -> Poll | None:
    if not isinstance(raw, dict):
        return None
    choices = raw.get("choices") or raw.get("options")
    if not isinstance(choices, list):
        return None
    votes = [
        max(_optional_int(item.get("count", item.get("votes"))) or 0, 0) for item in choices if isinstance(item, dict)
    ]
    total = max(_optional_int(raw.get("total_votes")) or sum(votes), 0)
    options = []
    for choice in choices[:4]:
        if not isinstance(choice, dict):
            continue
        label = _first_text(choice.get("label"), choice.get("text"))
        if not label:
            continue
        count = max(_optional_int(choice.get("count", choice.get("votes"))) or 0, 0)
        try:
            percent = float(choice.get("percentage", choice.get("percent", count / total * 100 if total else 0)))
        except TypeError, ValueError, OverflowError:
            percent = 0.0
        percent = min(max(percent, 0), 100) if math.isfinite(percent) else 0.0
        options.append(PollOption(text=label, votes=count, percent=percent))
    if not options:
        return None
    ended = raw.get("ended") is True or raw.get("is_ended") is True
    expires_at = raw.get("ends_at")
    if isinstance(expires_at, str):
        try:
            deadline = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            ended = ended or deadline.replace(tzinfo=deadline.tzinfo or timezone.utc) <= datetime.now(timezone.utc)
        except ValueError:
            pass
    return Poll(
        question=_first_text(raw.get("question")),
        options=options,
        total_votes=total,
        is_ended=ended,
        time_left=_first_text(raw.get("time_left")) or None,
    )


def parse_tweet_api(data: dict[str, Any], original_url: str) -> Optional[Tweet]:
    """Парсит FxTwitter/FixTweet JSON API, если структура ответа распознана.

    API разных фронтендов менялся, поэтому парсер намеренно берёт несколько
    распространённых вариантов полей и возвращает None при недостатке данных.
    """
    if isinstance(data.get("tweet"), dict):
        tweet_data = data["tweet"]
    elif isinstance(data.get("status"), dict):
        tweet_data = data["status"]
    else:
        tweet_data = data
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

    media = _parse_media(tweet_data.get("media"))
    quoted_tweet = _parse_reference(tweet_data.get("quote") or tweet_data.get("quoted_tweet"))

    parent_tweet = _parse_reference(tweet_data.get("parent_tweet"))
    poll = _parse_poll(tweet_data.get("poll"))
    replying_to = tweet_data.get("replying_to")
    if parent_tweet is None and isinstance(replying_to, dict):
        parent_tweet = _parse_reference(replying_to)

    if isinstance(data.get("thread"), list) and isinstance(replying_to, dict):
        parent_id = _first_text(
            replying_to.get("id"),
            replying_to.get("tweet_id"),
            replying_to.get("status_id"),
            replying_to.get("status"),
        )
        if parent_id:
            full_parent = next(
                (
                    parsed
                    for raw in data["thread"]
                    if isinstance(raw, dict) and _first_text(raw.get("id")) == parent_id
                    if (parsed := _parse_reference(raw)) is not None
                ),
                None,
            )
            if full_parent is not None:
                parent_tweet = full_parent

    if not username or not (text or media or quoted_tweet or parent_tweet or poll):
        return None
    if not display_name:
        display_name = username

    date = _parse_date_value(tweet_data)
    if date is None:
        date = datetime.now()

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

    translated_text, source_language = _parse_translation(tweet_data)

    return Tweet(
        display_name=display_name,
        username=username,
        url=original_url,
        text=text,
        date=date,
        media=media,
        quoted_tweet=quoted_tweet,
        parent_tweet=parent_tweet,
        stats=stats,
        poll=poll,
        translated_text=translated_text,
        source_language=source_language,
    )
