"""Обработчики команд бота (минимальный набор)."""

import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.handlers.menus import (
    get_admin_keyboard,
    get_admin_text,
    get_downloads_keyboard,
    get_downloads_text,
    get_help_keyboard,
    get_help_text,
    get_main_menu_keyboard,
    get_main_menu_text,
    get_settings_hub_keyboard,
    get_settings_hub_text,
)
from src.services.database import Database
from src.services.menu_data import build_download_menu_data, build_provider_states
from src.services.settings import is_admin, is_user_allowed, remember_group
from src.providers.youtube_urls import VIDEO_ID_RE

logger = logging.getLogger(__name__)


async def _ensure_command_allowed(update: Update) -> bool:
    user = update.effective_user
    if user is None or is_user_allowed(user.id):
        return True
    if update.message is not None:
        await update.message.reply_text("Доступ к боту ограничен владельцем.")
    return False


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /start - показывает главное меню."""
    if update.message is None or update.effective_user is None:
        logger.warning("Команда /start без message/effective_user")
        return
    if not await _ensure_command_allowed(update):
        return

    database = context.application.bot_data.get("database")
    if isinstance(database, Database):
        await database.upsert_user(
            telegram_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )

    await update.message.reply_text(
        text=get_main_menu_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=get_main_menu_keyboard(
            update.effective_chat is not None and update.effective_chat.type == "private",
            is_admin(update.effective_user.id),
        ),
        disable_web_page_preview=True,
    )
    if context.args and update.effective_chat is not None and update.effective_chat.type == "private":
        payload = context.args[0]
        if payload.startswith("dl_"):
            video_id = payload.removeprefix("dl_")
            if VIDEO_ID_RE.fullmatch(video_id):
                await update.message.reply_text(
                    "Теперь загрузку можно продолжить здесь:",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("📥 Выбрать качество", callback_data=f"download:youtube:{video_id}")]]
                    ),
                )
    logger.info("Команда /start от пользователя %s", update.effective_user.id)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /status - показывает настройки и статус."""
    if update.message is None or update.effective_user is None:
        logger.warning("Команда /status без message/effective_user")
        return
    if not await _ensure_command_allowed(update):
        return

    user_id = update.effective_user.id
    private = update.effective_chat is not None and update.effective_chat.type == "private"

    database = context.application.bot_data.get("database")
    if isinstance(database, Database):
        await remember_group(database, update)

    if private and is_admin(user_id) and isinstance(database, Database):
        states = await build_provider_states(database)
        stats = await database.get_runtime_stats()
        text = get_admin_text(stats, states)
        keyboard = get_admin_keyboard(states)
    else:
        text = get_settings_hub_text(private, is_admin(user_id))
        keyboard = get_settings_hub_keyboard(private, is_admin(user_id))

    await update.message.reply_text(
        text=text, parse_mode=ParseMode.HTML, reply_markup=keyboard, disable_web_page_preview=True
    )
    logger.info("Команда /status от пользователя %s", user_id)


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None:
        return
    if not await _ensure_command_allowed(update):
        return
    private = update.effective_chat is not None and update.effective_chat.type == "private"
    await update.message.reply_text(
        text=get_settings_hub_text(private, is_admin(update.effective_user.id)),
        parse_mode=ParseMode.HTML,
        reply_markup=get_settings_hub_keyboard(private, is_admin(update.effective_user.id)),
        disable_web_page_preview=True,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None:
        return
    if not await _ensure_command_allowed(update):
        return
    await update.message.reply_text(
        text=get_help_text(),
        parse_mode=ParseMode.HTML,
        reply_markup=get_help_keyboard(),
        disable_web_page_preview=True,
    )


async def downloads(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    if not await _ensure_command_allowed(update):
        return
    if update.effective_chat.type != "private":
        await update.message.reply_text("Загрузки доступны только в ЛС с ботом.")
        return
    database = context.application.bot_data.get("database")
    if not isinstance(database, Database):
        await update.message.reply_text("База данных пока недоступна.")
        return
    total, items = await build_download_menu_data(database, update.effective_user.id)
    await update.message.reply_text(
        text=get_downloads_text(total, len(items)),
        parse_mode=ParseMode.HTML,
        reply_markup=get_downloads_keyboard(items),
        disable_web_page_preview=True,
    )


async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.message is None or update.effective_user is None or update.effective_chat is None:
        return
    if not await _ensure_command_allowed(update):
        return
    if update.effective_chat.type != "private" or not is_admin(update.effective_user.id):
        await update.message.reply_text("Панель доступна только владельцу бота в ЛС.")
        return
    database = context.application.bot_data.get("database")
    if not isinstance(database, Database):
        await update.message.reply_text("База данных пока недоступна.")
        return
    states = await build_provider_states(database)
    stats = await database.get_runtime_stats()
    await update.message.reply_text(
        text=get_admin_text(stats, states),
        parse_mode=ParseMode.HTML,
        reply_markup=get_admin_keyboard(states),
        disable_web_page_preview=True,
    )
