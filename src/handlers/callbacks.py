"""Callback handlers for inline menus."""

from __future__ import annotations

import logging
from html import escape

from aiogram.enums import ParseMode

from src.telegram_runtime import (
    BadRequest,
    CallbackQueryAdapter as CallbackQuery,
    ContextTypes,
    Forbidden,
    TelegramError,
    Update,
)
from src.telegram_ui import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import config
from src.handlers.menus import (
    CALLBACK_ADMIN,
    CALLBACK_DOWNLOADS,
    CALLBACK_HELP,
    CALLBACK_MAIN_MENU,
    CALLBACK_SETTINGS,
    CALLBACK_TRANSLATE,
    CB_ADMIN_PROVIDER,
    CB_SETTINGS_GLOBAL,
    CB_SETTINGS_GROUP,
    CB_SETTINGS_GROUPS,
    CB_SETTINGS_SENDER,
    CB_SETTINGS_SENDER_SET,
    CB_SETTINGS_TOGGLE,
    CB_SETTINGS_RESET,
    CB_INLINE_CACHE,
    CB_INLINE_CACHE_BIND,
    CB_INLINE_CACHE_DISABLE,
    CB_TRANSLATE_GROUP,
    CB_TRANSLATE_SET,
    CB_TRANSLATE_USER,
    get_admin_keyboard,
    get_admin_text,
    get_downloads_keyboard,
    get_downloads_text,
    get_groups_keyboard,
    get_groups_text,
    get_help_keyboard,
    get_help_text,
    get_main_menu_keyboard,
    get_main_menu_text,
    get_scope_settings_keyboard,
    get_scope_settings_text,
    get_inline_cache_keyboard,
    get_inline_cache_text,
    get_sender_mode_keyboard,
    get_settings_hub_keyboard,
    get_settings_hub_text,
    get_translate_language_keyboard,
    get_translate_language_text,
    get_translate_scope_keyboard,
    get_translate_scope_text,
)
from src.services.database import Database
from src.services.download_links import create_download_url
from src.services.download_queue import DownloadQueue
from src.services.menu_data import build_download_menu_data, build_provider_states
from src.services.providers import PROVIDERS, toggle_provider
from src.services.settings import (
    GLOBAL_OWNER_ID,
    SENDER_QUOTE_MODES,
    get_scope_settings,
    is_admin,
    is_user_allowed,
    set_sender_quote_mode,
    set_translation_language,
    toggle_bool_setting,
)
from src.services.youtube_downloader import FormatOption, YtDlpDownloader
from src.twitter.translate import SUPPORTED_LANGUAGES
from src.providers.youtube_urls import VIDEO_ID_RE
from src.utils.progress import MessageProgress

logger = logging.getLogger(__name__)


async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Main callback query dispatcher."""
    query = update.callback_query
    user = update.effective_user
    if query is None or user is None:
        logger.warning("Callback update без query/effective_user")
        return

    user_id = user.id
    callback_data = query.data or ""

    if not is_user_allowed(user_id):
        await query.answer("Доступ к боту ограничен владельцем", show_alert=True)
        return

    logger.info("Callback от юзера %s: %s", user_id, callback_data)

    if not callback_data.startswith("download:"):
        await query.answer()

    if callback_data == CALLBACK_MAIN_MENU:
        await show_main_menu(query, user_id)
    elif callback_data == CALLBACK_HELP:
        await show_help(query)
    elif callback_data == CALLBACK_SETTINGS:
        await show_settings_hub(query, user_id)
    elif callback_data == CB_SETTINGS_GLOBAL:
        await show_global_settings(query, context, user_id)
    elif callback_data == CB_SETTINGS_GROUPS or callback_data.startswith(f"{CB_SETTINGS_GROUPS}:"):
        await show_groups(query, context, user_id, callback_data)
    elif callback_data.startswith(CB_SETTINGS_GROUP):
        await show_group_settings(query, context, user_id, callback_data)
    elif callback_data.startswith(CB_SETTINGS_TOGGLE):
        await handle_toggle_setting(query, context, user_id, callback_data)
    elif callback_data.startswith(CB_SETTINGS_RESET):
        await handle_reset_settings(query, context, user_id, callback_data)
    elif callback_data.startswith(CB_SETTINGS_SENDER_SET):
        await handle_sender_mode_set(query, context, user_id, callback_data)
    elif callback_data.startswith(CB_SETTINGS_SENDER):
        await show_sender_mode(query, context, user_id, callback_data)
    elif callback_data == CB_INLINE_CACHE:
        await show_inline_cache(query, context, user_id)
    elif callback_data == CB_INLINE_CACHE_BIND:
        await begin_inline_cache_binding(query, context, user_id)
    elif callback_data == CB_INLINE_CACHE_DISABLE:
        await disable_inline_cache(query, context, user_id)
    elif callback_data == CALLBACK_TRANSLATE:
        await show_translate_scope(query)
    elif callback_data == CALLBACK_DOWNLOADS:
        await show_downloads(query, context, user_id)
    elif callback_data == CALLBACK_ADMIN:
        await show_admin(query, context, user_id)
    elif callback_data.startswith(CB_ADMIN_PROVIDER):
        await handle_provider_toggle(query, context, user_id, callback_data)
    elif callback_data == CB_TRANSLATE_USER:
        await show_translate_language(query, context, "dm", user_id)
    elif callback_data == CB_TRANSLATE_GROUP:
        await show_current_group_translate(query, context)
    elif callback_data.startswith(CB_TRANSLATE_SET):
        await handle_translate_set(query, context, user_id, callback_data)
    elif callback_data.startswith("download:youtube:q:"):
        await handle_youtube_quality_selected(query, context, user_id, callback_data)
    elif callback_data.startswith("download:youtube:c:"):
        await handle_youtube_download_cancel(query, context, user_id, callback_data)
    elif callback_data.startswith("download:youtube:"):
        await handle_youtube_download_requested(query, context, user_id, callback_data)
    else:
        logger.warning("Неизвестный callback: %s", callback_data)
        await query.answer("⚠️ Неизвестная команда", show_alert=True)


async def show_main_menu(query: CallbackQuery, user_id: int) -> None:
    """Show main menu."""
    await query.edit_message_text(
        text=get_main_menu_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu_keyboard(_is_private(query), is_admin(user_id)),
        disable_web_page_preview=True,
    )


async def handle_youtube_download_requested(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    video_id = callback_data.removeprefix("download:youtube:")
    if not VIDEO_ID_RE.match(video_id):
        await query.answer("Некорректный video id", show_alert=True)
        return
    if query.message is None:
        return
    if not config.WEB_BASE_URL:
        await query.answer("WEB_BASE_URL не настроен, скачивание пока недоступно", show_alert=True)
        return

    database = await _require_database(query, context)
    if database is None:
        return

    user = await database.get_user(user_id)
    if user is None:
        await query.answer("Сначала откройте бота в ЛС и нажмите /start", show_alert=True)
        await query.message.reply_text(
            "Чтобы получить видео в личные сообщения, сначала откройте бота и нажмите /start.",
            reply_markup=_open_bot_keyboard(context.bot.username, f"dl_{video_id}"),
        )
        return

    downloader = _get_downloader(context)
    if downloader is None:
        await query.answer("Downloader пока недоступен", show_alert=True)
        return
    request_id, reservation_error = await database.reserve_download_request(
        telegram_id=user_id,
        video_id=video_id,
        source_chat_id=query.message.chat.id,
        source_message_id=query.message.message_id,
        max_active=config.MAX_ACTIVE_DOWNLOADS_PER_USER,
    )
    if reservation_error == "duplicate":
        await query.answer("Это видео уже находится в ваших загрузках", show_alert=True)
        return
    if reservation_error == "limit":
        await query.answer("У вас уже слишком много активных загрузок", show_alert=True)
        return
    if request_id is None:
        await query.answer("Не удалось создать запрос на загрузку", show_alert=True)
        return

    try:
        options = await downloader.get_available_format_options(f"https://www.youtube.com/watch?v={video_id}")
    except Exception:
        logger.exception("Не удалось получить форматы video_id=%s", video_id)
        await database.update_download_request(request_id, status="failed")
        await query.answer("Не удалось получить форматы", show_alert=True)
        return

    try:
        await context.bot.send_message(
            chat_id=user_id,
            text="Выберите качество для скачивания:",
            reply_markup=_youtube_quality_keyboard(options, request_id),
        )
    except Forbidden:
        await database.update_download_request(request_id, status="failed")
        await query.answer("Сначала откройте бота в ЛС и нажмите /start", show_alert=True)
        return

    await query.answer("Отправил выбор качества в ЛС")


async def handle_youtube_download_cancel(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    request_id = _parse_download_request_id(callback_data, "download:youtube:c:")
    if request_id is None:
        await query.answer("Некорректный запрос", show_alert=True)
        return

    database = await _require_database(query, context)
    if database is None:
        return
    request = await database.get_download_request(request_id)
    if request is None or int(request["telegram_id"]) != user_id:
        await query.answer("Запрос не найден", show_alert=True)
        return

    await database.update_download_request(request_id, status="cancelled")
    if query.message is not None:
        await query.message.edit_text("❌ Загрузка отменена.")
    await query.answer("Отменено")


async def handle_youtube_quality_selected(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    parsed = _parse_quality_callback(callback_data)
    if parsed is None:
        await query.answer("Некорректные данные", show_alert=True)
        return
    request_id, quality = parsed
    if quality not in {"360", "480", "720", "1080", "audio"}:
        await query.answer("Некорректное качество", show_alert=True)
        return
    if query.message is None:
        return
    if query.message.chat.type != "private" or query.message.chat.id != user_id:
        await query.answer("Управлять загрузкой можно только в ЛС с ботом", show_alert=True)
        return

    database = await _require_database(query, context)
    if database is None:
        return
    request = await database.get_download_request(request_id)
    if request is None or int(request["telegram_id"]) != user_id:
        await query.answer("Запрос не найден", show_alert=True)
        return
    if request["status"] != "pending":
        await query.answer("Этот запрос уже завершён", show_alert=True)
        return

    queue = _get_download_queue(context)
    downloader = _get_downloader(context)
    if queue is None or downloader is None:
        await query.answer("Downloader пока недоступен", show_alert=True)
        return

    if not await database.claim_download_request(request_id, user_id, quality):
        await query.answer("Этот запрос уже обрабатывается", show_alert=True)
        return

    video_id = str(request["video_id"])
    try:
        duration_seconds = await downloader.get_duration_seconds(video_id)
    except Exception:
        logger.exception("Не удалось проверить длительность video_id=%s", video_id)
        await database.update_download_request(request_id, status="failed")
        await query.message.edit_text("Не удалось проверить параметры видео.")
        await query.answer()
        return

    if duration_seconds > config.MAX_VIDEO_DURATION_MINUTES * 60:
        await database.update_download_request(request_id, status="failed", selected_quality=quality)
        await query.message.edit_text(
            f"Видео слишком длинное. Максимальная длительность — {config.MAX_VIDEO_DURATION_MINUTES} минут."
        )
        await query.answer()
        return

    await query.message.edit_text("⏳ Подготавливаю загрузку...")
    progress = MessageProgress(context, query.message.chat.id, query.message.message_id)

    async def job() -> None:
        current_request = await database.get_download_request(request_id)
        if current_request is None or current_request["status"] == "cancelled":
            return

        await database.update_download_request(request_id, status="downloading")
        downloaded = None
        success = False
        failure_text: str | None = None

        async def on_progress(stage: str, percent: int | None = None) -> None:
            if stage == "info":
                await progress.set_text("⏳ Получаю информацию о формате...")
            elif stage == "downloading" and percent is not None:
                await progress.set_download_percent(percent)
            elif stage == "merging":
                await progress.set_text("🛠 Объединяю видео и аудио...")
            elif stage == "converting":
                await progress.set_text("📱 Готовлю совместимый формат для iPhone...")

        try:
            downloaded = await downloader.download(video_id, quality, on_progress)
            if downloaded.final_size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
                await database.update_download_request(request_id, status="failed")
                failure_text = "Видео слишком большое для скачивания."
                return

            link = create_download_url(downloaded.file_path)

            await progress.set_text("📤 Отправляю ссылку на скачивание...", force=True)
            await context.bot.send_message(
                chat_id=user_id,
                text=(
                    "Ссылка на скачивание готова:\n\n"
                    f"Качество: {downloaded.format_note}\n"
                    f"Размер: {downloaded.final_size / (1024 * 1024):.1f} MB\n"
                    f"{link}\n\n"
                    f"Ссылка активна {config.DOWNLOAD_LINK_TTL_MINUTES} минут."
                ),
                disable_web_page_preview=True,
            )
            await database.create_download(
                request_id, str(downloaded.file_path), downloaded.final_size, downloaded.format_note
            )
            await database.update_download_request(request_id, status="sent")
            await downloader.cleanup_stale_files(
                config.DOWNLOAD_FILE_RETENTION_HOURS * 3600,
                exclude_paths={downloaded.file_path},
            )
            success = True
        except RuntimeError as exc:
            logger.warning("Ошибка подготовки YouTube download request_id=%s: %s", request_id, exc)
            await database.update_download_request(request_id, status="failed")
            failure_text = str(exc)
        except Exception:
            logger.exception("Ошибка YouTube download request_id=%s", request_id)
            await database.update_download_request(request_id, status="failed")
            failure_text = "Не удалось подготовить ссылку. Видео может быть приватным, возрастным или недоступным."
        finally:
            if downloaded is not None and not success:
                await downloader.cleanup(downloaded.cleanup_paths)
            if success:
                await progress.set_text("✅ Готово", force=True)
            elif failure_text:
                await progress.set_text(failure_text, force=True)

    started, position, _task = await queue.enqueue(job)
    if started:
        await query.answer("Загрузка запущена")
    else:
        await query.answer()
        await progress.set_text(f"Все слоты заняты. Задача поставлена в очередь: позиция #{position}.", force=True)

    try:
        await query.message.edit_reply_markup(reply_markup=None)
    except BadRequest:
        pass


async def show_help(query: CallbackQuery) -> None:
    """Show help."""
    await query.edit_message_text(
        text=get_help_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=get_help_keyboard(),
        disable_web_page_preview=True,
    )


async def show_downloads(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    if not _is_private(query):
        await query.answer("Загрузки доступны только в ЛС с ботом", show_alert=True)
        return
    database = await _require_database(query, context)
    if database is None:
        return
    total, items = await build_download_menu_data(database, user_id)
    await query.edit_message_text(
        text=get_downloads_text(total, len(items)),
        parse_mode=ParseMode.HTML,
        reply_markup=get_downloads_keyboard(items),
        disable_web_page_preview=True,
    )


async def show_admin(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    if not _is_private(query) or not is_admin(user_id):
        await query.answer("Панель доступна только владельцу бота в ЛС", show_alert=True)
        return
    database = await _require_database(query, context)
    if database is None:
        return
    states = await build_provider_states(database)
    stats = await database.get_runtime_stats()
    await query.edit_message_text(
        text=get_admin_text(stats, states),
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_keyboard(states),
        disable_web_page_preview=True,
    )


async def handle_provider_toggle(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    if not _is_private(query) or not is_admin(user_id):
        await query.answer("Недостаточно прав", show_alert=True)
        return
    source = callback_data.removeprefix(CB_ADMIN_PROVIDER)
    if source not in PROVIDERS:
        await query.answer("Неизвестный источник", show_alert=True)
        return
    database = await _require_database(query, context)
    if database is None:
        return
    enabled = await toggle_provider(database, source)
    await query.answer("Источник включён" if enabled else "Источник выключен")
    await show_admin(query, context, user_id)


async def show_settings_hub(query: CallbackQuery, user_id: int) -> None:
    """Show settings sections."""
    private = _is_private(query)
    admin = is_admin(user_id)
    await query.edit_message_text(
        text=get_settings_hub_text(private, admin),
        parse_mode=ParseMode.HTML,
        reply_markup=get_settings_hub_keyboard(private, admin),
        disable_web_page_preview=True,
    )


async def show_global_settings(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    if not _is_private(query) or not is_admin(user_id):
        await query.answer("Глобальные настройки доступны только администратору", show_alert=True)
        return
    await show_scope_settings(query, context, "global", GLOBAL_OWNER_ID)


async def show_inline_cache(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    if not _is_private(query) or not is_admin(user_id):
        await query.answer("Медиакэш доступен только администратору", show_alert=True)
        return
    database = await _require_database(query, context)
    if database is None:
        return
    raw_chat_id = await database.get_setting("global", GLOBAL_OWNER_ID, "inline_cache_chat_id")
    try:
        cache_chat_id = int(raw_chat_id) if raw_chat_id else None
    except ValueError:
        cache_chat_id = None
    await query.edit_message_text(
        text=get_inline_cache_text(cache_chat_id),
        parse_mode=ParseMode.HTML,
        reply_markup=get_inline_cache_keyboard(cache_chat_id),
    )


async def begin_inline_cache_binding(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    if not _is_private(query) or not is_admin(user_id):
        await query.answer("Недостаточно прав", show_alert=True)
        return
    pending = context.application.bot_data.setdefault("pending_cache_bindings", set())
    if isinstance(pending, set):
        pending.add(user_id)
    await query.edit_message_text(
        text=get_inline_cache_text(None, pending=True),
        parse_mode=ParseMode.HTML,
        reply_markup=get_inline_cache_keyboard(None, pending=True),
    )


async def disable_inline_cache(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    if not _is_private(query) or not is_admin(user_id):
        await query.answer("Недостаточно прав", show_alert=True)
        return
    database = await _require_database(query, context)
    if database is None:
        return
    await database.delete_setting("global", GLOBAL_OWNER_ID, "inline_cache_chat_id")
    await query.answer("Медиакэш отключён")
    await show_inline_cache(query, context, user_id)


async def show_group_settings(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    if not _is_private(query):
        await query.answer("Групповые настройки меняются только в ЛС с ботом", show_alert=True)
        return

    raw_owner_id = callback_data[len(CB_SETTINGS_GROUP) :]
    try:
        owner_id = int(raw_owner_id)
    except ValueError:
        await query.answer("Не удалось определить группу", show_alert=True)
        return

    database = await _require_database(query, context)
    if database is None:
        return
    if not await _user_can_manage_group(context, database, user_id, owner_id):
        await query.answer("Эта группа не привязана к вашему аккаунту", show_alert=True)
        return

    await show_scope_settings(query, context, "group", owner_id)


async def show_groups(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str = CB_SETTINGS_GROUPS,
) -> None:
    if not _is_private(query):
        await query.answer("Список групп доступен только в ЛС с ботом", show_alert=True)
        return

    database = _get_database(context)
    groups = await _manageable_groups_for_user(context, database, user_id) if database is not None else []
    page = 0
    if callback_data.startswith(f"{CB_SETTINGS_GROUPS}:"):
        try:
            page = max(int(callback_data.rsplit(":", 1)[1]), 0)
        except ValueError:
            page = 0
    page_size = 10
    total_pages = max((len(groups) + page_size - 1) // page_size, 1)
    page = min(page, total_pages - 1)
    await query.edit_message_text(
        text=get_groups_text(len(groups), page, total_pages),
        parse_mode=ParseMode.HTML,
        reply_markup=get_groups_keyboard(groups, page, page_size),
        disable_web_page_preview=True,
    )


async def show_scope_settings(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    scope: str,
    owner_id: int,
) -> None:
    database = _get_database(context)
    values = await get_scope_settings(database, scope, owner_id)
    translation = await database.get_translation_language(scope, owner_id) if database is not None else None
    title = await _scope_title(database, scope, owner_id)

    await query.edit_message_text(
        text=get_scope_settings_text(scope, title, values, translation),
        parse_mode=ParseMode.HTML,
        reply_markup=get_scope_settings_keyboard(scope, owner_id),
        disable_web_page_preview=True,
    )


async def handle_toggle_setting(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    database = await _require_database(query, context)
    if database is None:
        return

    parsed = _parse_scope_owner_name(callback_data, CB_SETTINGS_TOGGLE)
    if parsed is None:
        await query.answer("Не удалось разобрать настройку", show_alert=True)
        return
    scope, owner_id, name = parsed

    if not await _ensure_scope_write_allowed(query, context, database, user_id, scope, owner_id):
        return

    try:
        enabled = await toggle_bool_setting(database, scope, owner_id, name)
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)
        return

    await query.answer("Включено" if enabled else "Выключено")
    await show_scope_settings(query, context, scope, owner_id)


async def handle_reset_settings(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    parsed = _parse_scope_owner(callback_data, CB_SETTINGS_RESET)
    if parsed is None:
        await query.answer("Не удалось разобрать профиль настроек", show_alert=True)
        return
    scope, owner_id = parsed
    if scope not in {"dm", "group"}:
        await query.answer("Этот профиль нельзя сбросить", show_alert=True)
        return
    database = await _require_database(query, context)
    if database is None:
        return
    if not await _ensure_scope_write_allowed(query, context, database, user_id, scope, owner_id):
        return
    await database.reset_scope_settings(scope, owner_id)
    await query.answer("Настройки снова наследуются от глобальных")
    await show_scope_settings(query, context, scope, owner_id)


async def show_sender_mode(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    parsed = _parse_scope_owner(callback_data, CB_SETTINGS_SENDER)
    if parsed is None:
        await query.answer("Не удалось разобрать настройку", show_alert=True)
        return
    scope, owner_id = parsed

    database = await _require_database(query, context)
    if database is None:
        return
    if not await _ensure_scope_write_allowed(query, context, database, user_id, scope, owner_id):
        return

    values = await get_scope_settings(database, scope, owner_id)
    current = values.get("sender_quote_mode", "name")
    title = await _scope_title(database, scope, owner_id)

    await query.edit_message_text(
        text=f"<b>Отправитель в цитате: {escape(title)}</b>\n\nВыберите формат:",
        parse_mode=ParseMode.HTML,
        reply_markup=get_sender_mode_keyboard(scope, owner_id, current),
        disable_web_page_preview=True,
    )


async def handle_sender_mode_set(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    database = await _require_database(query, context)
    if database is None:
        return

    parsed = _parse_scope_owner_name(callback_data, CB_SETTINGS_SENDER_SET)
    if parsed is None:
        await query.answer("Не удалось разобрать настройку", show_alert=True)
        return
    scope, owner_id, mode = parsed

    if not await _ensure_scope_write_allowed(query, context, database, user_id, scope, owner_id):
        return

    try:
        await set_sender_quote_mode(database, scope, owner_id, mode)
    except ValueError as exc:
        await query.answer(str(exc), show_alert=True)
        return

    await query.answer(f"Установлено: {SENDER_QUOTE_MODES[mode]}")
    await show_scope_settings(query, context, scope, owner_id)


async def show_translate_scope(query: CallbackQuery) -> None:
    is_group = _is_group(query)
    await query.edit_message_text(
        text=get_translate_scope_text(is_group),
        parse_mode=ParseMode.HTML,
        reply_markup=get_translate_scope_keyboard(is_group),
        disable_web_page_preview=True,
    )


async def show_current_group_translate(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = getattr(query.message, "chat", None)
    if chat is None or chat.type not in {"group", "supergroup"}:
        await query.answer("Перевод группы выбирается из самой группы", show_alert=True)
        return
    await show_translate_language(query, context, "group", chat.id)


async def show_translate_language(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    scope: str,
    owner_id: int,
) -> None:
    database = _get_database(context)
    current_lang = await database.get_translation_language(scope, owner_id) if database is not None else None
    title = await _scope_title(database, scope, owner_id)

    await query.edit_message_text(
        text=get_translate_language_text(title, current_lang),
        parse_mode=ParseMode.HTML,
        reply_markup=get_translate_language_keyboard(
            scope,
            owner_id,
            current_lang,
            back_callback=CALLBACK_TRANSLATE if not _is_private(query) else None,
        ),
        disable_web_page_preview=True,
    )


async def handle_translate_set(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    callback_data: str,
) -> None:
    parsed = _parse_scope_owner_name(callback_data, CB_TRANSLATE_SET)
    if parsed is None:
        await query.answer("Не удалось разобрать перевод", show_alert=True)
        return
    scope, owner_id, language = parsed

    if language == "menu":
        if not await _ensure_translate_write_allowed(query, context, user_id, scope, owner_id):
            return
        await show_translate_language(query, context, scope, owner_id)
        return

    if not await _ensure_translate_write_allowed(query, context, user_id, scope, owner_id):
        return

    database = await _require_database(query, context)
    if database is None:
        return

    try:
        await set_translation_language(database, scope, owner_id, language)
    except ValueError:
        await query.answer("❌ Неизвестный язык", show_alert=True)
        return

    if language == "off":
        await query.answer("Перевод выключен")
    else:
        await query.answer(f"Установлено: {SUPPORTED_LANGUAGES[language]}")
    await show_translate_language(query, context, scope, owner_id)


def _get_database(context: ContextTypes.DEFAULT_TYPE) -> Database | None:
    database = context.application.bot_data.get("database")
    return database if isinstance(database, Database) else None


def _get_downloader(context: ContextTypes.DEFAULT_TYPE) -> YtDlpDownloader | None:
    downloader = context.application.bot_data.get("youtube_downloader")
    return downloader if isinstance(downloader, YtDlpDownloader) else None


def _get_download_queue(context: ContextTypes.DEFAULT_TYPE) -> DownloadQueue | None:
    queue = context.application.bot_data.get("download_queue")
    return queue if isinstance(queue, DownloadQueue) else None


async def _require_database(query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> Database | None:
    database = _get_database(context)
    if database is None:
        await query.answer("База данных пока недоступна", show_alert=True)
    return database


def _is_private(query: CallbackQuery) -> bool:
    chat = getattr(query.message, "chat", None)
    return bool(chat and chat.type == "private")


def _is_group(query: CallbackQuery) -> bool:
    chat = getattr(query.message, "chat", None)
    return bool(chat and chat.type in {"group", "supergroup"})


async def _ensure_scope_write_allowed(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    database: Database,
    user_id: int,
    scope: str,
    owner_id: int,
) -> bool:
    if scope not in {"global", "group"}:
        await query.answer("Неизвестный раздел настроек", show_alert=True)
        return False
    if scope == "global" and owner_id != GLOBAL_OWNER_ID:
        await query.answer("Некорректный владелец глобальных настроек", show_alert=True)
        return False
    if scope == "global" and not is_admin(user_id):
        await query.answer("Глобальные настройки доступны только администратору", show_alert=True)
        return False
    if scope == "group" and owner_id >= 0:
        await query.answer("Некорректный идентификатор группы", show_alert=True)
        return False
    if scope == "group" and not _is_private(query):
        await query.answer("Групповые настройки меняются только в ЛС с ботом", show_alert=True)
        return False
    if scope == "group" and not await _user_can_manage_group(context, database, user_id, owner_id):
        await query.answer("Вы не добавляли бота в эту группу и не являетесь ее админом", show_alert=True)
        return False
    return True


async def _ensure_translate_write_allowed(
    query: CallbackQuery,
    context: ContextTypes.DEFAULT_TYPE,
    user_id: int,
    scope: str,
    owner_id: int,
) -> bool:
    if scope == "global" and not is_admin(user_id):
        await query.answer("Глобальный перевод доступен только администратору", show_alert=True)
        return False
    if scope == "dm" and owner_id != user_id:
        await query.answer("Личный перевод можно менять только себе", show_alert=True)
        return False
    if scope == "group":
        if _current_chat_id(query) == owner_id:
            database = await _require_database(query, context)
            if database is None:
                return False
            if await _user_can_manage_group(context, database, user_id, owner_id):
                return True
            await query.answer("Перевод группы могут менять только её администраторы", show_alert=True)
            return False
        database = await _require_database(query, context)
        if database is None:
            return False
        if not (_is_private(query) and await _user_can_manage_group(context, database, user_id, owner_id)):
            await query.answer("Вы не добавляли бота в эту группу и не являетесь ее админом", show_alert=True)
            return False
    return True


def _current_chat_id(query: CallbackQuery) -> int | None:
    chat = getattr(query.message, "chat", None)
    return int(chat.id) if chat is not None else None


async def _scope_title(database: Database | None, scope: str, owner_id: int) -> str:
    if scope == "global":
        return "Глобальные настройки"
    if scope == "dm":
        return "Для меня"
    if scope == "group":
        group = await database.get_group(owner_id) if database is not None else None
        title = str(group["title"]) if group is not None else str(owner_id)
        return f"Группа: {title}"
    return scope


async def _manageable_groups_for_user(
    context: ContextTypes.DEFAULT_TYPE,
    database: Database,
    user_id: int,
):
    groups = await database.list_groups()
    allowed_groups = []
    for group in groups:
        if await _user_can_manage_group(context, database, user_id, int(group["chat_id"])):
            allowed_groups.append(group)
    return allowed_groups


async def _user_can_manage_group(
    context: ContextTypes.DEFAULT_TYPE | None,
    database: Database,
    user_id: int,
    chat_id: int,
) -> bool:
    linked_as_adder = await database.user_can_manage_group(user_id, chat_id)
    if context is None:
        return linked_as_adder

    try:
        member = await context.bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    except TelegramError:
        logger.debug("Не удалось проверить админство user_id=%s chat_id=%s", user_id, chat_id, exc_info=True)
        return False

    status = str(getattr(member.status, "value", member.status))
    if status in {"left", "kicked", "banned"}:
        return False
    return linked_as_adder or status in {"administrator", "creator", "owner"}


def _parse_scope_owner(callback_data: str, prefix: str) -> tuple[str, int] | None:
    payload = callback_data[len(prefix) :]
    parts = payload.split(":", 1)
    if len(parts) != 2:
        return None
    scope, raw_owner_id = parts
    try:
        return scope, int(raw_owner_id)
    except ValueError:
        return None


def _parse_scope_owner_name(callback_data: str, prefix: str) -> tuple[str, int, str] | None:
    payload = callback_data[len(prefix) :]
    parts = payload.split(":", 2)
    if len(parts) != 3:
        return None
    scope, raw_owner_id, name = parts
    try:
        return scope, int(raw_owner_id), name
    except ValueError:
        return None


def _open_bot_keyboard(bot_username: str | None, payload: str) -> InlineKeyboardMarkup | None:
    if not bot_username:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Открыть бота", url=f"https://t.me/{bot_username}?start={payload}")]]
    )


def _youtube_quality_keyboard(options: list[FormatOption], request_id: int) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for option in options:
        row.append(
            InlineKeyboardButton(
                option.label,
                callback_data=f"download:youtube:q:{request_id}:{option.key}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Отмена", callback_data=f"download:youtube:c:{request_id}")])
    return InlineKeyboardMarkup(rows)


def _parse_download_request_id(callback_data: str, prefix: str) -> int | None:
    payload = callback_data.removeprefix(prefix)
    try:
        return int(payload)
    except ValueError:
        return None


def _parse_quality_callback(callback_data: str) -> tuple[int, str] | None:
    payload = callback_data.removeprefix("download:youtube:q:")
    parts = payload.split(":", 1)
    if len(parts) != 2:
        return None
    try:
        return int(parts[0]), parts[1]
    except ValueError:
        return None
