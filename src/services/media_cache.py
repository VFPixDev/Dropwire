"""Telegram file_id cache populated from ordinary Rich Messages."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from src.services.database import Database
from src.twitter.models import MediaItem, Tweet

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CachedMedia:
    source_url: str
    media_type: str
    file_id: str
    file_unique_id: str | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None


async def cache_tweet_media(database: Database, items: list[MediaItem]) -> list[CachedMedia]:
    cached: list[CachedMedia] = []
    for item in items:
        row = await database.get_cached_media(item.url)
        if row is None:
            return []
        cached.append(_from_row(row))
    return cached


async def remember_sent_rich_media(database: Database, tweet: Tweet, rich_message) -> None:
    source_items = _all_media(tweet)
    telegram_files = list(_iter_media_files(getattr(rich_message, "blocks", [])))
    if len(source_items) != len(telegram_files):
        logger.info("Rich media cache skipped: source=%s telegram=%s", len(source_items), len(telegram_files))
        return

    for item, telegram_file in zip(source_items, telegram_files, strict=True):
        await database.upsert_cached_media(
            source_url=item.url,
            media_type=item.type,
            file_id=telegram_file.file_id,
            file_unique_id=getattr(telegram_file, "file_unique_id", None),
            width=getattr(telegram_file, "width", None) or item.width,
            height=getattr(telegram_file, "height", None) or item.height,
            duration=getattr(telegram_file, "duration", None) or item.duration,
        )


def _iter_media_files(blocks):
    for block in blocks or []:
        photos = getattr(block, "photo", None)
        if isinstance(photos, list) and photos:
            yield photos[-1]
        for attribute in ("video", "animation"):
            media = getattr(block, attribute, None)
            if media is not None and getattr(media, "file_id", None):
                yield media
        nested = getattr(block, "blocks", None)
        if nested:
            yield from _iter_media_files(nested)


def _all_media(tweet: Tweet) -> list[MediaItem]:
    items = list(tweet.media)
    if tweet.quoted_tweet:
        items.extend(tweet.quoted_tweet.media)
    if tweet.parent_tweet:
        items.extend(tweet.parent_tweet.media)
    return items


def _from_row(row) -> CachedMedia:
    return CachedMedia(
        source_url=str(row["source_url"]),
        media_type=str(row["media_type"]),
        file_id=str(row["file_id"]),
        file_unique_id=str(row["file_unique_id"]) if row["file_unique_id"] else None,
        width=int(row["width"]) if row["width"] is not None else None,
        height=int(row["height"]) if row["height"] is not None else None,
        duration=int(row["duration"]) if row["duration"] is not None else None,
    )
