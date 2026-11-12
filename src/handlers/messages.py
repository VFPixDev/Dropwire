from __future__ import annotations

import asyncio
import logging
import re
from html import escape
from typing import Optional
from weakref import WeakValueDictionary

from aiogram.enums import ParseMode
from aiogram.types import ReplyParameters

from src.telegram_runtime import BadRequest, ContextTypes, NetworkError, TelegramError, TimedOut, Update
from src.telegram_ui import InlineKeyboardButton, InlineKeyboardMarkup
from src.config import config
from src.providers.link_router import LinkMatch, find_supported_links
from src.providers.youtube import fetch_youtube_card
from src.providers.spotify import fetch_spotify_card
from src.providers.soundcloud import fetch_soundcloud_card
from src.rendering.hashtags import build_hashtags, render_hashtags
from src.rendering.telegram_cards import build_card_keyboard, format_card_text
from src.rendering.twitter_rich import build_twitter_rich_message
from src.rendering.youtube_rich import build_youtube_rich_message
from src.twitter.normalize import normalize_url, extract_tweet_id, extract_username
from src.twitter.loader import fetch_complete_tweet
from src.services.database import Database
from src.services.media_cache import remember_sent_rich_media
from src.services.settings import (
    EffectiveSettings,
    get_effective_settings,
    get_translation_language,
    is_user_allowed,
    remember_group,
)
from src.services.providers import is_provider_enabled
from src.utils.sender_quote import format_sender_quote
from src.utils.rate_limit import rate_limiter

logger = logging.getLogger(__name__)
_processing_locks: WeakValueDictionary[tuple[int, int], asyncio.Lock] = WeakValueDictionary()


def get_reply_to_message_id(update: Update, settings: Optional[EffectiveSettings] = None) -> int | None:
    """Возвращает ID исходного сообщения для reply, если включено"""
    reply_to_message = settings.reply_to_message if settings else config.REPLY_TO_MESSAGE
    if reply_to_message and update.message:
        return update.message.message_id
    return None


def get_tweet_url_keyboard(tweet_url: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру с кнопкой ссылки на оригинальный твит"""
    keyboard = [[InlineKeyboardButton("🔗 Открыть оригинал", url=tweet_url)]]
    return InlineKeyboardMarkup(keyboard)


def telegram_timeout_kwargs() -> dict[str, float]:
    return {"request_timeout": max(config.TELEGRAM_READ_TIMEOUT, config.TELEGRAM_WRITE_TIMEOUT)}


def build_sender_quote_prefix(
    update: Update,
    user_comment: Optional[str] = None,
    settings: Optional[EffectiveSettings] = None,
) -> str:
    include_quote = settings.include_sender_quote if settings else config.INCLUDE_SENDER_QUOTE
    quote_mode = settings.sender_quote_mode if settings else config.SENDER_QUOTE_MODE
    if not include_quote or update.effective_user is None:
        return ""
    return format_sender_quote(update.effective_user, user_comment, quote_mode)


def prepend_sender_quote(
    text: str,
    update: Update,
    user_comment: Optional[str] = None,
    settings: Optional[EffectiveSettings] = None,
) -> str:
    quote = build_sender_quote_prefix(update, user_comment, settings)
    return f"{quote}\n\n{text}" if quote else text


async def send_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    thread_id: Optional[int] = None,
    settings: Optional[EffectiveSettings] = None,
    **kwargs,
):
    """Отправляет текст без reply, если настройка выключена"""
    chat = update.effective_chat
    if chat is None:
        logger.warning("Не удалось отправить сообщение: effective_chat отсутствует")
        return

    chat_id = chat.id
    reply_to_message_id = get_reply_to_message_id(update, settings)
    send_kwargs = {**telegram_timeout_kwargs(), **kwargs}
    return await context.bot.send_message(
        chat_id=chat_id, text=text, message_thread_id=thread_id, reply_to_message_id=reply_to_message_id, **send_kwargs
    )


async def _record_delivery(update: Update, context: ContextTypes.DEFAULT_TYPE, sent) -> None:
    chat = update.effective_chat
    user = update.effective_user
    source = update.message
    if chat is None or user is None or source is None or chat.type not in {"group", "supergroup"}:
        return
    database = context.application.bot_data.get("database")
    if not isinstance(database, Database):
        return
    messages = sent if isinstance(sent, (list, tuple)) else [sent]
    try:
        for message in messages:
            message_id = getattr(message, "message_id", None)
            if isinstance(message_id, int):
                await database.record_delivery_message(chat.id, source.message_id, user.id, message_id)
    except Exception:
        logger.exception("Не удалось сохранить журнал доставки chat_id=%s", chat.id)


async def _try_send_rich_tweet_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tweet,
    thread_id: int | None,
    settings: EffectiveSettings | None,
    user_comment: str | None,
    hashtags: str,
):
    database_value = context.application.bot_data.get("database")
    database = database_value if isinstance(database_value, Database) else None
    if update.effective_chat is None:
        return None

    sender_quote = build_sender_quote_prefix(update, user_comment, settings)
    reply_to_message_id = get_reply_to_message_id(update, settings)
    reply_parameters = ReplyParameters(message_id=reply_to_message_id) if reply_to_message_id else None
    for mode in ("auto", "upload", "none"):
        rich = await build_twitter_rich_message(
            context.bot,
            database,
            tweet,
            sender_quote=sender_quote,
            hashtags=hashtags,
            media_mode=mode,
        )
        if rich is None:
            continue
        try:
            sent = await context.bot.send_rich_message(
                chat_id=update.effective_chat.id,
                rich_message=rich.message,
                message_thread_id=thread_id,
                reply_parameters=reply_parameters,
                reply_markup=get_tweet_url_keyboard(tweet.url),
                **telegram_timeout_kwargs(),
            )
        except BadRequest as exc:
            logger.info("Telegram rejected Twitter Rich Message mode=%s: %s", mode, exc)
            if database is not None and rich.cache_urls:
                try:
                    await database.delete_cached_media(list(rich.cache_urls))
                except Exception:
                    logger.warning("Could not invalidate media cache", exc_info=True)
            if not (
                tweet.media
                or tweet.quoted_tweet
                and tweet.quoted_tweet.media
                or tweet.parent_tweet
                and tweet.parent_tweet.media
            ):
                break
            continue

        await _record_delivery(update, context, sent)
        if database is not None and getattr(sent, "rich_message", None) is not None:
            try:
                await remember_sent_rich_media(database, tweet, sent.rich_message)
            except Exception:
                logger.warning("Не удалось сохранить Telegram file_id из Rich Message", exc_info=True)
        return sent
    return None


async def _try_send_rich_youtube_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    card,
    thread_id: int | None,
    settings: EffectiveSettings | None,
    user_comment: str | None,
):
    database_value = context.application.bot_data.get("database")
    database = database_value if isinstance(database_value, Database) else None
    if update.effective_chat is None:
        return None

    sender_quote = build_sender_quote_prefix(update, user_comment, settings)
    hashtags = render_hashtags(card.hashtags)
    rich = await build_youtube_rich_message(
        context.bot,
        database,
        card,
        sender_quote=sender_quote,
        hashtags=hashtags,
    )
    if rich is None:
        return None

    reply_to_message_id = get_reply_to_message_id(update, settings)
    reply_parameters = ReplyParameters(message_id=reply_to_message_id) if reply_to_message_id else None
    try:
        sent = await context.bot.send_rich_message(
            chat_id=update.effective_chat.id,
            rich_message=rich.message,
            message_thread_id=thread_id,
            reply_parameters=reply_parameters,
            reply_markup=build_card_keyboard(card),
            **telegram_timeout_kwargs(),
        )
    except BadRequest as exc:
        logger.info("Telegram отклонил YouTube Rich Message, используется fallback: %s", exc)
        if database is not None and rich.cache_urls:
            await database.delete_cached_media(list(rich.cache_urls))
        return None

    await _record_delivery(update, context, sent)
    return sent


def should_reply_in_chat(update: Update, settings: EffectiveSettings) -> bool:
    """Определяет, нужно ли отвечать в этом чате"""
    message = update.message
    if message is None:
        return False
    chat = message.chat

    # В личке всегда отвечаем
    if chat.type == "private":
        return True

    # В группах
    bot_username = update.get_bot().username

    # Если бот упомянут
    message_text = message.text or getattr(message, "caption", None) or ""
    if bot_username and f"@{bot_username}".casefold() in message_text.casefold():
        return True

    # Если включен режим ответов в группах
    if settings.reply_in_groups:
        return True

    return False


def check_whitelist(user_id: int) -> bool:
    """Проверяет whitelist пользователей"""
    return is_user_allowed(user_id)


async def send_tweet_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    tweet,
    thread_id: Optional[int] = None,
    user_comment: Optional[str] = None,
    settings: Optional[EffectiveSettings] = None,
):
    """Отправляет карточку твита"""

    if update.effective_chat is None or update.effective_user is None:
        logger.warning("Не удалось отправить твит: нет effective_chat/effective_user")
        return

    hashtags = ""
    enable_hashtags = settings.enable_hashtags if settings else config.ENABLE_HASHTAGS
    if enable_hashtags:
        hashtags = render_hashtags(build_hashtags("twitter", "post", tweet.username))
    try:
        sent = await _try_send_rich_tweet_card(update, context, tweet, thread_id, settings, user_comment, hashtags)
        if sent is not None:
            return True
    except (TimedOut, NetworkError) as exc:
        # Telegram may already have accepted the message. Do not duplicate it.
        logger.warning("Ambiguous Twitter delivery; no retry: %s", exc)
        return False

    # A server without Rich Message support still leaves an actionable source link.
    sent = await send_text_message(
        update,
        context,
        "⚠️ Не удалось отправить карточку. Публикация доступна по кнопке ниже.",
        thread_id=thread_id,
        reply_markup=get_tweet_url_keyboard(tweet.url),
        settings=settings,
    )
    await _record_delivery(update, context, sent)
    return False


async def process_tweet_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    original_url: str,
    thread_id: Optional[int] = None,
    user_comment: Optional[str] = None,
    settings: Optional[EffectiveSettings] = None,
):
    """Обрабатывает одну ссылку на твит"""
    normalized_url = normalize_url(original_url)

    if not normalized_url:
        logger.warning(f"Не удалось нормализовать URL: {original_url}")
        return False

    tweet_id = extract_tweet_id(normalized_url)
    username = extract_username(normalized_url)

    if not tweet_id or not username:
        logger.warning(f"Не удалось извлечь данные из URL: {normalized_url}")
        return False

    if update.effective_user is None:
        logger.warning("Не удалось обработать твит: effective_user отсутствует")
        return False

    database = context.application.bot_data.get("database")
    lang_code = await get_translation_language(database if isinstance(database, Database) else None, update)

    # Получаем данные твита
    logger.info(f"Обработка твита: {tweet_id} (язык: {lang_code or 'нет'})")

    try:
        tweet = await fetch_complete_tweet(normalized_url, tweet_id, username, lang_code)
    except Exception:
        logger.exception("Tweet fetch failed tweet_id=%s", tweet_id)
        tweet = None

    if not tweet:
        await send_text_message(
            update,
            context,
            "❌ Не удалось получить публикацию. Откройте оригинал по кнопке ниже.",
            reply_markup=get_tweet_url_keyboard(normalized_url),
            thread_id=thread_id,
            settings=settings,
        )
        return False

    # Если перевод не получен, но запрошен
    if lang_code and not tweet.translated_text:
        logger.info("Перевод не получен от источника")

    # Отправляем карточку
    try:
        return await send_tweet_card(update, context, tweet, thread_id, user_comment, settings)
    except Exception as e:
        logger.error("Ошибка при отправке твита: %s", e)
        await send_text_message(
            update,
            context,
            "❌ Не удалось отправить карточку твита.",
            reply_markup=get_tweet_url_keyboard(normalized_url),
            thread_id=thread_id,
            settings=settings,
        )
        return False


async def send_media_card(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    card,
    thread_id: Optional[int] = None,
    user_comment: Optional[str] = None,
    settings: Optional[EffectiveSettings] = None,
):
    """Sends a generic provider card."""
    if update.effective_chat is None:
        logger.warning("Не удалось отправить карточку: нет effective_chat")
        return

    text = prepend_sender_quote(format_card_text(card), update, user_comment, settings)
    keyboard = build_card_keyboard(card)
    reply_to_message_id = get_reply_to_message_id(update, settings)
    caption_above_media = settings.caption_above_media if settings else config.CAPTION_ABOVE_MEDIA

    if card.thumbnail_url:
        try:
            sent = await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=card.thumbnail_url,
                caption=text,
                parse_mode=ParseMode.HTML,
                message_thread_id=thread_id,
                reply_to_message_id=reply_to_message_id,
                show_caption_above_media=caption_above_media,
                reply_markup=keyboard,
                **telegram_timeout_kwargs(),
            )
            await _record_delivery(update, context, sent)
        except TimedOut, NetworkError:
            raise
        except TelegramError as exc:
            logger.warning("Telegram отклонил превью %s, отправляется текстовая карточка: %s", card.source, exc)
            sent = await send_text_message(
                update,
                context,
                text,
                thread_id=thread_id,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=keyboard,
                settings=settings,
            )
            await _record_delivery(update, context, sent)
        return

    sent = await send_text_message(
        update,
        context,
        text,
        thread_id=thread_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
        settings=settings,
    )
    await _record_delivery(update, context, sent)


async def process_youtube_url(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    original_url: str,
    thread_id: Optional[int] = None,
    user_comment: Optional[str] = None,
    settings: Optional[EffectiveSettings] = None,
):
    """Processes one YouTube link."""
    try:
        card = await fetch_youtube_card(original_url)
    except ValueError as exc:
        await send_text_message(update, context, f"❌ {escape(str(exc))}", thread_id=thread_id, settings=settings)
        return False
    except RuntimeError as exc:
        await send_text_message(update, context, f"❌ {escape(str(exc))}", thread_id=thread_id, settings=settings)
        return False
    except Exception:
        logger.exception("Ошибка обработки YouTube URL: %s", original_url)
        await send_text_message(
            update,
            context,
            "❌ Не удалось получить информацию о YouTube-видео.",
            thread_id=thread_id,
            settings=settings,
        )
        return False

    if settings is not None and not settings.enable_hashtags:
        card.hashtags = []
    try:
        rich_sent = await _try_send_rich_youtube_card(
            update,
            context,
            card,
            thread_id,
            settings,
            user_comment,
        )
        if rich_sent is not None:
            return True
        await send_media_card(update, context, card, thread_id=thread_id, user_comment=user_comment, settings=settings)
    except (TimedOut, NetworkError) as exc:
        logger.warning("Неоднозначный сетевой результат при отправке YouTube-карточки; повтор не выполняется: %s", exc)
        return False
    except TelegramError as exc:
        logger.warning("Telegram отклонил YouTube-карточку: %s", exc)
        await send_text_message(
            update,
            context,
            "❌ Telegram не смог отправить карточку YouTube.",
            thread_id=thread_id,
            settings=settings,
        )
        return False
    return True


async def process_oembed_source(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    link: LinkMatch,
    thread_id: Optional[int],
    user_comment: Optional[str] = None,
    settings: Optional[EffectiveSettings] = None,
):
    source_name = "Spotify" if link.source == "spotify" else "SoundCloud"
    try:
        card = await (fetch_spotify_card(link.url) if link.source == "spotify" else fetch_soundcloud_card(link.url))
        if settings is not None and not settings.enable_hashtags:
            card.hashtags = []
        await send_media_card(update, context, card, thread_id=thread_id, user_comment=user_comment, settings=settings)
        return True
    except (TimedOut, NetworkError) as exc:
        logger.warning("Неоднозначный сетевой результат при отправке %s-карточки: %s", source_name, exc)
        return False
    except (ValueError, RuntimeError) as exc:
        logger.info("Не удалось получить %s-карточку: %s", source_name, exc)
        await send_text_message(update, context, f"❌ {escape(str(exc))}", thread_id=thread_id, settings=settings)
        return False
    except TelegramError as exc:
        logger.warning("Telegram отклонил %s-карточку: %s", source_name, exc)
        return False
    except Exception:
        logger.exception("Ошибка обработки %s URL", source_name)
        await send_text_message(
            update,
            context,
            f"❌ Не удалось получить информацию из {source_name}.",
            thread_id=thread_id,
            settings=settings,
        )
        return False


async def _send_processing_notice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    thread_id: int | None,
    links_count: int,
):
    if update.effective_chat is None:
        return None
    text = "⏳ Принял, подготавливаю…" if links_count == 1 else f"⏳ Принял, подготавливаю 1 из {links_count}…"
    try:
        return await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            message_thread_id=thread_id,
            **telegram_timeout_kwargs(),
        )
    except TelegramError as exc:
        logger.info("Не удалось отправить статус обработки: %s", exc)
        return None


async def _edit_processing_notice(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    notice,
    text: str,
) -> None:
    if update.effective_chat is None or notice is None:
        return
    try:
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=notice.message_id,
            text=text,
            **telegram_timeout_kwargs(),
        )
    except TelegramError:
        logger.debug("Не удалось обновить статус обработки", exc_info=True)


async def _delete_processing_notice(update: Update, context: ContextTypes.DEFAULT_TYPE, notice) -> None:
    if update.effective_chat is None or notice is None:
        return
    try:
        await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=notice.message_id)
    except TelegramError:
        logger.debug("Не удалось удалить статус обработки", exc_info=True)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик текстовых сообщений"""

    if update.message is None or update.effective_user is None or update.effective_chat is None:
        logger.warning("Пропущен update без message/effective_user/effective_chat")
        return

    # Whitelist
    user_id = update.effective_user.id
    if not check_whitelist(user_id):
        logger.warning(f"Пользователь {user_id} не в whitelist")
        return

    database = context.application.bot_data.get("database")
    database = database if isinstance(database, Database) else None
    await remember_group(database, update)
    settings = await get_effective_settings(database, update)

    # Проверка нужно ли отвечать
    if not should_reply_in_chat(update, settings):
        return

    # Ищем поддерживаемые ссылки
    message_text = update.message.text or getattr(update.message, "caption", None) or ""
    links = find_supported_links(message_text)

    if not links:
        return

    chat_id = update.effective_chat.id

    thread_id = update.message.message_thread_id if update.message.is_topic_message else None

    total_links_count = len(links)
    if len(links) > config.MAX_LINKS_PER_MESSAGE:
        logger.info(
            "Ограничено число ссылок user_id=%s chat_id=%s: %s -> %s",
            user_id,
            chat_id,
            len(links),
            config.MAX_LINKS_PER_MESSAGE,
        )
        links = links[: config.MAX_LINKS_PER_MESSAGE]
        await send_text_message(
            update,
            context,
            f"ℹ️ За одно сообщение обрабатываю не больше {config.MAX_LINKS_PER_MESSAGE} ссылок.",
            thread_id=thread_id,
            settings=settings,
        )

    # Извлекаем комментарий если есть текст перед первой ссылкой
    user_comment = None
    first_url_pos = links[0].start
    if first_url_pos > 0:
        user_comment = message_text[:first_url_pos].strip()
        # Убираем упоминание бота из комментария
        bot_username = update.get_bot().username
        if bot_username:
            user_comment = re.sub(re.escape(f"@{bot_username}"), "", user_comment, flags=re.IGNORECASE).strip()
        if user_comment:
            logger.info("Найден комментарий пользователя длиной %s символов", len(user_comment))

    notice = await _send_processing_notice(update, context, thread_id, len(links))
    keep_notice = False
    lock = _processing_locks.setdefault((user_id, chat_id), asyncio.Lock())

    try:
        async with lock:
            if not await rate_limiter.wait_until_allowed(user_id, chat_id):
                logger.info("Очередь обработки переполнена user_id=%s chat_id=%s", user_id, chat_id)
                keep_notice = True
                await _edit_processing_notice(
                    update,
                    context,
                    notice,
                    "⚠️ Сейчас слишком много запросов. Повторите через несколько секунд.",
                )
                return

            processed_count = 0
            for idx, link in enumerate(links):
                if idx > 0:
                    await _edit_processing_notice(
                        update,
                        context,
                        notice,
                        f"⏳ Подготавливаю {idx + 1} из {len(links)}…",
                    )

                # Комментарий только для первой найденной ссылки.
                comment = user_comment if idx == 0 else None

                if not await is_provider_enabled(database, link.source):
                    await send_text_message(
                        update,
                        context,
                        f"ℹ️ Источник {link.source} временно отключён владельцем бота.",
                        thread_id=thread_id,
                        settings=settings,
                    )
                    continue

                try:
                    if link.source == "twitter":
                        success = await process_tweet_url(update, context, link.url, thread_id, comment, settings)
                    elif link.source == "youtube":
                        success = await process_youtube_url(update, context, link.url, thread_id, comment, settings)
                    else:
                        success = await process_oembed_source(update, context, link, thread_id, comment, settings)
                except Exception:
                    logger.exception("Link processing failed source=%s", link.source)
                    success = False
                    await send_text_message(
                        update,
                        context,
                        "❌ Не удалось обработать ссылку. Откройте оригинал по кнопке ниже.",
                        thread_id=thread_id,
                        settings=settings,
                        reply_markup=get_tweet_url_keyboard(link.url),
                    )

                if success:
                    processed_count += 1

            logger.info("Обработано %s из %s ссылок", processed_count, len(links))

            chat = update.effective_chat
            if (
                settings.remove_message_in_groups
                and chat.type in ["group", "supergroup"]
                and update.message.message_id
                and processed_count == total_links_count
            ):
                try:
                    await context.bot.delete_message(chat_id=chat.id, message_id=update.message.message_id)
                    logger.info("Удалено сообщение %s в группе %s", update.message.message_id, chat.id)
                except TelegramError as exc:
                    logger.warning("Не удалось удалить сообщение: %s", exc)
    finally:
        if not keep_notice:
            await _delete_processing_notice(update, context, notice)
