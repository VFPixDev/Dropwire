"""Transient Telegram file_id cache used by inline Rich Messages."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from urllib.parse import urlparse

from aiogram.exceptions import TelegramAPIError

from src.services.database import Database
from src.twitter.fetcher import _is_trusted_twitter_media_url, get_trusted_twitter_mp4_url
from src.twitter.models import MediaItem

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


async def cache_tweet_media(
    bot,
    database: Database,
    items: list[MediaItem],
    *,
    staging_chat_id: int | None = None,
) -> list[CachedMedia]:
    if not items:
        return []

    results = await asyncio.gather(
        *(_get_or_upload(bot, database, staging_chat_id, item) for item in items),
        return_exceptions=True,
    )
    cached: list[CachedMedia] = []
    for result in results:
        if isinstance(result, CachedMedia):
            cached.append(result)
        elif isinstance(result, Exception):
            logger.info("Не удалось подготовить inline-медиа: %s", type(result).__name__)
    return cached


async def _get_or_upload(bot, database: Database, chat_id: int | None, item: MediaItem) -> CachedMedia | None:
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
            if item.type == "photo":
                message = await bot.send_photo(
                    chat_id=chat_id,
                    photo=media_url,
                    disable_notification=True,
                    protect_content=True,
                )
                telegram_file = message.photo[-1] if message.photo else None
            elif item.type == "animation":
                message = await bot.send_animation(
                    chat_id=chat_id,
                    animation=media_url,
                    width=item.width,
                    height=item.height,
                    duration=item.duration,
                    disable_notification=True,
                    protect_content=True,
                )
                telegram_file = message.animation
            else:
                message = await bot.send_video(
                    chat_id=chat_id,
                    video=media_url,
                    width=item.width,
                    height=item.height,
                    duration=item.duration,
                    supports_streaming=True,
                    disable_notification=True,
                    protect_content=True,
                )
                telegram_file = message.video
        except TelegramAPIError as exc:
            logger.info("Telegram отклонил временную inline-загрузку в ЛС пользователя: %s", exc)
            return None
        try:
            if telegram_file is None:
                return None
            width = getattr(telegram_file, "width", None) or item.width
            height = getattr(telegram_file, "height", None) or item.height
            duration = getattr(telegram_file, "duration", None) or item.duration
            await database.upsert_cached_media(
                source_url=item.url,
                media_type=item.type,
                file_id=telegram_file.file_id,
                file_unique_id=getattr(telegram_file, "file_unique_id", None),
                width=width,
                height=height,
                duration=duration,
            )
            return CachedMedia(
                source_url=item.url,
                media_type=item.type,
                file_id=telegram_file.file_id,
                file_unique_id=getattr(telegram_file, "file_unique_id", None),
                width=width,
                height=height,
                duration=duration,
            )
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
                logger.error("Не удалось удалить временное inline-сообщение %s: %s", message_id, exc)
                return
            await asyncio.sleep(0.25 * (2**attempt))


def _trusted_media_url(item: MediaItem) -> str | None:
    if item.type in {"video", "animation"}:
        return get_trusted_twitter_mp4_url(item.url)
    parsed = urlparse(item.url)
    return item.url if _is_trusted_twitter_media_url(parsed) else None


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
