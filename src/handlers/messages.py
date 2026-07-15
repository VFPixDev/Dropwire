import logging
from typing import Optional

from telegram import Update, InputMediaPhoto, InputMediaVideo, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from telegram.constants import ParseMode
from telegram.error import NetworkError, TelegramError, TimedOut
from src.config import config
from src.providers.link_router import LinkMatch, find_supported_links
from src.providers.youtube import fetch_youtube_card
from src.providers.spotify import fetch_spotify_card
from src.providers.soundcloud import fetch_soundcloud_card
from src.rendering.hashtags import build_hashtags, render_hashtags
from src.rendering.telegram_cards import build_card_keyboard, format_card_text
from src.twitter.normalize import normalize_url, extract_tweet_id, extract_username
from src.twitter.fetcher import fetch_tweet_data, fetch_tweet_html
from src.twitter.parser import parse_tweet_html
from src.twitter.parser_api import parse_tweet_api
from src.services.database import Database
from src.services.settings import EffectiveSettings, get_effective_settings, get_translation_language, remember_group
from src.services.providers import is_provider_enabled
from src.utils.sender_quote import format_sender_quote
from src.utils.text_format import format_tweet_card, shorten_text_for_caption
from src.utils.rate_limit import rate_limiter
from src.media.download import download_media_file, get_file_size_mb
from src.media.compress import compress_image, compress_video
from src.media.cleanup import delete_files

logger = logging.getLogger(__name__)


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
    return {
        "connect_timeout": config.TELEGRAM_CONNECT_TIMEOUT,
        "read_timeout": config.TELEGRAM_READ_TIMEOUT,
        "write_timeout": config.TELEGRAM_WRITE_TIMEOUT,
        "pool_timeout": config.TELEGRAM_POOL_TIMEOUT,
    }


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
    await context.bot.send_message(
        chat_id=chat_id, text=text, message_thread_id=thread_id, reply_to_message_id=reply_to_message_id, **send_kwargs
    )


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
    if message.text and f"@{bot_username}" in message.text:
        return True

    # Если включен режим ответов в группах
    if settings.reply_in_groups:
        return True

    return False


def check_whitelist(user_id: int) -> bool:
    """Проверяет whitelist пользователей"""
    if config.TELEGRAM_USER_IDS is None:
        return True
    return user_id in config.TELEGRAM_USER_IDS


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

    # Всегда показываем оригинальный текст
    # Информацию о переводе добавим в конец карточки если есть
    include_translation = bool(tweet.translated_text)

    # Форматируем карточку
    card_text = format_tweet_card(tweet, include_translation=include_translation)
    card_text = prepend_sender_quote(card_text, update, user_comment, settings)
    enable_hashtags = settings.enable_hashtags if settings else config.ENABLE_HASHTAGS
    caption_above_media = settings.caption_above_media if settings else config.CAPTION_ABOVE_MEDIA
    if enable_hashtags:
        hashtags = render_hashtags(build_hashtags("twitter", "post", tweet.username))
        if hashtags:
            card_text = f"{card_text}\n\n{hashtags}"

    temp_files = []

    try:
        # Если нет медиа - просто отправляем текст
        if not tweet.media:
            await send_text_message(
                update,
                context,
                card_text,
                thread_id=thread_id,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                reply_markup=get_tweet_url_keyboard(tweet.url),
                settings=settings,
            )
            return

        # Скачиваем медиа
        media_files = []
        for media_item in tweet.media[:10]:  # Ограничение 10 медиа
            file_path = await download_media_file(media_item.url, media_item.type)
            if file_path:
                # Сжимаем если нужно
                if media_item.type == "photo":
                    compressed_path = compress_image(file_path)
                else:
                    compressed_path = compress_video(file_path)

                if get_file_size_mb(compressed_path) > config.MAX_MEDIA_MB:
                    logger.warning(
                        "Медиа пропущено: %.2fMB > %sMB", get_file_size_mb(compressed_path), config.MAX_MEDIA_MB
                    )
                    temp_files.append(file_path)
                    if compressed_path != file_path:
                        temp_files.append(compressed_path)
                    continue

                media_files.append((media_item.type, compressed_path))
                temp_files.append(file_path)
                if compressed_path != file_path:
                    temp_files.append(compressed_path)

        if not media_files:
            # Медиа не удалось скачать
            await send_text_message(
                update,
                context,
                card_text + "\n\n⚠️ Не удалось загрузить медиа",
                thread_id=thread_id,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                settings=settings,
            )
            return

        # Проверяем длину caption
        caption: Optional[str]
        caption, is_truncated = shorten_text_for_caption(card_text, max_length=1024)

        # Если текст слишком длинный - отправляем отдельно
        if is_truncated or len(card_text) > 1024:
            await send_text_message(
                update,
                context,
                card_text,
                thread_id=thread_id,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                settings=settings,
            )
            caption = None

        # Отправляем медиа
        if len(media_files) == 1:
            # Одно медиа
            media_type, file_path = media_files[0]
            reply_to_message_id = get_reply_to_message_id(update, settings)

            with open(file_path, "rb") as f:
                if media_type == "photo":
                    await context.bot.send_photo(
                        chat_id=update.effective_chat.id,
                        photo=f,
                        caption=caption,
                        parse_mode=ParseMode.HTML if caption else None,
                        message_thread_id=thread_id,
                        reply_to_message_id=reply_to_message_id,
                        show_caption_above_media=caption_above_media,
                        reply_markup=get_tweet_url_keyboard(tweet.url),
                        **telegram_timeout_kwargs(),
                    )
                else:
                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=f,
                        caption=caption,
                        parse_mode=ParseMode.HTML if caption else None,
                        message_thread_id=thread_id,
                        reply_to_message_id=reply_to_message_id,
                        show_caption_above_media=caption_above_media,
                        reply_markup=get_tweet_url_keyboard(tweet.url),
                        **telegram_timeout_kwargs(),
                    )
        else:
            # Несколько медиа - альбом
            media_group: list[InputMediaPhoto | InputMediaVideo] = []
            opened_files = []
            reply_to_message_id = get_reply_to_message_id(update, settings)

            try:
                for idx, (media_type, file_path) in enumerate(media_files):
                    f = open(file_path, "rb")
                    opened_files.append(f)

                    if media_type == "photo":
                        media_obj: InputMediaPhoto | InputMediaVideo = InputMediaPhoto(
                            media=f,
                            caption=caption if idx == 0 else None,
                            parse_mode=ParseMode.HTML if (idx == 0 and caption) else None,
                            show_caption_above_media=caption_above_media,
                        )
                    else:
                        media_obj = InputMediaVideo(
                            media=f,
                            caption=caption if idx == 0 else None,
                            parse_mode=ParseMode.HTML if (idx == 0 and caption) else None,
                            show_caption_above_media=caption_above_media,
                        )

                    media_group.append(media_obj)

                await context.bot.send_media_group(
                    chat_id=update.effective_chat.id,
                    media=media_group,
                    message_thread_id=thread_id,
                    reply_to_message_id=reply_to_message_id,
                    **telegram_timeout_kwargs(),
                )

                # Отправляем кнопку с ссылкой после альбома (media_group не поддерживает reply_markup)
                await context.bot.send_message(
                    chat_id=update.effective_chat.id,
                    text="👆",
                    message_thread_id=thread_id,
                    reply_markup=get_tweet_url_keyboard(tweet.url),
                    **telegram_timeout_kwargs(),
                )
            finally:
                # Закрываем все открытые файлы
                for f in opened_files:
                    f.close()

    except (TimedOut, NetworkError) as e:
        # Telegram may have accepted the upload before the client timed out. A
        # fallback message here would create the duplicate replies users saw.
        logger.warning("Неоднозначный сетевой результат при отправке медиа; повтор не выполняется: %s", e)
    except TelegramError as e:
        logger.error(f"Ошибка Telegram при отправке: {e}")
        await send_text_message(
            update,
            context,
            f"❌ Ошибка при отправке медиа: {e}\n\n{card_text}",
            thread_id=thread_id,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            settings=settings,
        )
    finally:
        # Удаляем временные файлы
        delete_files(temp_files)


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

    # Сначала пробуем структурированный API, HTML оставляем как fallback.
    tweet = None
    api_data = await fetch_tweet_data(tweet_id, username, lang_code)
    if api_data:
        tweet = parse_tweet_api(api_data, normalized_url)

    needs_html_fallback = tweet is None or (lang_code and not tweet.translated_text)
    if needs_html_fallback:
        html = await fetch_tweet_html(tweet_id, username, lang_code)

        if not html:
            if tweet is None:
                await send_text_message(
                    update,
                    context,
                    f"❌ Твит недоступен (возможно приватный, удалён или 18+): {original_url}",
                    thread_id=thread_id,
                    settings=settings,
                )
                return False
        else:
            html_tweet = parse_tweet_html(html, normalized_url)
            if html_tweet:
                tweet = html_tweet

    if not tweet:
        await send_text_message(
            update,
            context,
            f"❌ Не удалось распарсить твит: {original_url}",
            thread_id=thread_id,
            settings=settings,
        )
        return False

    # Если перевод не получен, но запрошен
    if lang_code and not tweet.translated_text:
        logger.info("Перевод не получен от источника")

    # Отправляем карточку
    try:
        await send_tweet_card(update, context, tweet, thread_id, user_comment, settings)
        return True
    except Exception as e:
        logger.error(f"Ошибка при отправке твита: {e}")
        await send_text_message(
            update,
            context,
            f"❌ Ошибка при отправке: {str(e)[:100]}",
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
        await context.bot.send_photo(
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
        return

    await send_text_message(
        update,
        context,
        text,
        thread_id=thread_id,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
        reply_markup=keyboard,
        settings=settings,
    )


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
        await send_text_message(update, context, f"❌ {exc}", thread_id=thread_id, settings=settings)
        return False
    except RuntimeError as exc:
        await send_text_message(update, context, f"❌ {exc}", thread_id=thread_id, settings=settings)
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
        await send_media_card(update, context, card, thread_id=thread_id, user_comment=user_comment, settings=settings)
    except (TimedOut, NetworkError) as exc:
        logger.warning("Неоднозначный сетевой результат при отправке YouTube-карточки; повтор не выполняется: %s", exc)
        return True
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
        return True
    except (ValueError, RuntimeError) as exc:
        logger.info("Не удалось получить %s-карточку: %s", source_name, exc)
        await send_text_message(update, context, f"❌ {exc}", thread_id=thread_id, settings=settings)
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

    # Rate limiting
    chat_id = update.effective_chat.id
    if not rate_limiter.is_allowed(user_id, chat_id):
        logger.info(f"Rate limit для пользователя {user_id}")
        return

    database = context.application.bot_data.get("database")
    database = database if isinstance(database, Database) else None
    await remember_group(database, update)
    settings = await get_effective_settings(database, update)

    # Проверка нужно ли отвечать
    if not should_reply_in_chat(update, settings):
        return

    # Ищем поддерживаемые ссылки
    message_text = update.message.text or ""
    links = find_supported_links(message_text)

    if not links:
        return

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
            settings=settings,
        )

    # Определяем thread_id для топиков
    thread_id = None
    if update.message.is_topic_message:
        thread_id = update.message.message_thread_id
        logger.info(f"Ответ в топик: {thread_id}")

    # Извлекаем комментарий если есть текст перед первой ссылкой
    user_comment = None
    first_url_pos = links[0].start
    if first_url_pos > 0:
        user_comment = message_text[:first_url_pos].strip()
        # Убираем упоминание бота из комментария
        bot_username = update.get_bot().username
        user_comment = user_comment.replace(f"@{bot_username}", "").strip()
        if user_comment:
            logger.info(f"Найден комментарий пользователя: {user_comment[:50]}")

    # Обрабатываем все найденные ссылки
    processed_count = 0
    for idx, link in enumerate(links):
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

        if link.source == "twitter":
            success = await process_tweet_url(update, context, link.url, thread_id, comment, settings)
        elif link.source == "youtube":
            success = await process_youtube_url(update, context, link.url, thread_id, comment, settings)
        else:
            success = await process_oembed_source(update, context, link, thread_id, comment, settings)

        if success:
            processed_count += 1

    logger.info(f"Обработано {processed_count} из {len(links)} ссылок")

    # Удаляем исходное сообщение в группах если включена опция
    chat = update.effective_chat
    if (
        settings.remove_message_in_groups
        and chat.type in ["group", "supergroup"]
        and update.message.message_id
        and processed_count > 0
    ):  # Только если хотя бы одна ссылка обработана
        try:
            await context.bot.delete_message(chat_id=chat.id, message_id=update.message.message_id)
            logger.info(f"Удалено сообщение {update.message.message_id} в группе {chat.id}")
        except TelegramError as e:
            logger.warning(f"Не удалось удалить сообщение: {e}")
