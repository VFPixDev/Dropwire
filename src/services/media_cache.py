"""Telegram file_id cache for inline Rich Messages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from urllib.parse import urlparse

from aiogram.exceptions import TelegramAPIError
from aiogram.types import BufferedInputFile

from src.services.database import Database
from src.services.settings import GLOBAL_OWNER_ID
from src.twitter.fetcher import (
    _is_trusted_twitter_media_url,
    download_media,
    get_trusted_twitter_mp4_url,
)
from src.twitter.models import MediaItem, Tweet

logger = logging.getLogger(__name__)
_cache_upload_slots = asyncio.Semaphore(4)


@dataclass(frozen=True)
class CachedMedia:
    source_url: str
    media_type: str
    file_id: str
    file_unique_id: str | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None


async def cache_tweet_media(bot, database: Database, items: list[MediaItem]) -> list[CachedMedia]:
    """Return cached media, uploading missing files to the transient cache chat."""
    if not items:
        return []

    raw_chat_id = await database.get_setting("global", GLOBAL_OWNER_ID, "inline_cache_chat_id")
    try:
        chat_id = int(raw_chat_id) if raw_chat_id else None
    except ValueError:
        chat_id = None

    results = await asyncio.shield(
        asyncio.gather(
            *(_get_or_upload(bot, database, chat_id, item) for item in items),
            return_exceptions=True,
        )
    )
    cached: list[CachedMedia] = []
    for result in results:
        if isinstance(result, CachedMedia):
            cached.append(result)
        elif isinstance(result, Exception):
            logger.info("Не удалось подготовить inline-медиа: %s", type(result).__name__)
    return cached


async def cache_photo_media(bot, database: Database, source_url: str) -> CachedMedia | None:
    """Upload a trusted external thumbnail and retain only its Telegram file_id."""
    item = MediaItem(type="photo", url=source_url)
    result = await asyncio.shield(_get_or_upload(bot, database, await _cache_chat_id(database), item))
    return result


async def _cache_chat_id(database: Database) -> int | None:
    raw_chat_id = await database.get_setting("global", GLOBAL_OWNER_ID, "inline_cache_chat_id")
    try:
        return int(raw_chat_id) if raw_chat_id else None
    except ValueError:
        return None


async def _get_or_upload(
    bot,
    database: Database,
    chat_id: int | None,
    item: MediaItem,
) -> CachedMedia | None:
    existing = await database.get_cached_media(item.url)
    if existing is not None:
        return _from_row(existing)
    if chat_id is None:
        return None

    media_url = _trusted_media_url(item)
    if media_url is None:
        return None

    async with _cache_upload_slots:
        existing = await database.get_cached_media(item.url)
        if existing is not None:
            return _from_row(existing)

        message = None
        try:
            common = {
                "chat_id": chat_id,
                "disable_notification": True,
                "protect_content": True,
            }
            if item.type == "photo":
                message = await bot.send_photo(photo=media_url, **common)
                telegram_file = message.photo[-1] if message.photo else None
            else:
                content = await download_media(media_url, max_bytes=50 * 1024 * 1024)
                if content is None:
                    return None
                filename = "twitter_animation.mp4" if item.type == "animation" else "twitter_video.mp4"
                upload = BufferedInputFile(content, filename=filename)
                if item.type == "animation":
                    message = await bot.send_animation(
                        animation=upload,
                        width=item.width,
                        height=item.height,
                        duration=item.duration,
                        **common,
                    )
                    telegram_file = message.animation
                else:
                    message = await bot.send_video(
                        video=upload,
                        width=item.width,
                        height=item.height,
                        duration=item.duration,
                        supports_streaming=True,
                        **common,
                    )
                    telegram_file = message.video

            if telegram_file is None:
                return None

            width = getattr(telegram_file, "width", None) or item.width
            height = getattr(telegram_file, "height", None) or item.height
            duration = getattr(telegram_file, "duration", None) or item.duration
            cached = CachedMedia(
                source_url=item.url,
                media_type=item.type,
                file_id=telegram_file.file_id,
                file_unique_id=getattr(telegram_file, "file_unique_id", None),
                width=width,
                height=height,
                duration=duration,
            )
            await database.upsert_cached_media(
                source_url=cached.source_url,
                media_type=cached.media_type,
                file_id=cached.file_id,
                file_unique_id=cached.file_unique_id,
                width=cached.width,
                height=cached.height,
                duration=cached.duration,
            )
            return cached
        except TelegramAPIError as exc:
            logger.info("Telegram отклонил загрузку в технический медиакэш: %s", exc)
            return None
        finally:
            if message is not None:
                await _delete_staging_message(bot, chat_id, message.message_id)


async def _delete_staging_message(bot, chat_id: int, message_id: int) -> None:
    for attempt in range(3):
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            return
        except TelegramAPIError as exc:
            if attempt == 2:
                logger.error("Не удалось удалить временное сообщение медиакэша %s: %s", message_id, exc)
                return
            await asyncio.sleep(0.25 * (2**attempt))


def _trusted_media_url(item: MediaItem) -> str | None:
    if item.type in {"video", "animation"}:
        return get_trusted_twitter_mp4_url(item.url)
    parsed = urlparse(item.url)
    return item.url if _is_trusted_cache_photo_url(parsed) else None


def _is_trusted_cache_photo_url(parsed) -> bool:
    if _is_trusted_twitter_media_url(parsed):
        return True
    hostname = (parsed.hostname or "").lower().rstrip(".")
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and not parsed.fragment
        and hostname in {"i.ytimg.com", "img.youtube.com"}
        and parsed.path.startswith(("/vi/", "/vi_webp/"))
    )


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
