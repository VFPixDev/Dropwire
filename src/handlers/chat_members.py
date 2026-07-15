"""Handlers for bot membership changes in chats."""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from src.services.database import Database

logger = logging.getLogger(__name__)

ACTIVE_BOT_STATUSES = {"member", "administrator"}
INACTIVE_BOT_STATUSES = {"left", "kicked"}


async def handle_my_chat_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Remember which user added Dropwire to which group."""
    event = update.my_chat_member
    if event is None or event.chat.type not in {"group", "supergroup"}:
        return

    database = context.application.bot_data.get("database")
    if not isinstance(database, Database):
        return

    old_status = event.old_chat_member.status
    new_status = event.new_chat_member.status
    chat = event.chat

    if new_status in ACTIVE_BOT_STATUSES:
        await database.upsert_group(chat.id, chat.title or str(chat.id), chat.type)
        await database.link_user_group(event.from_user.id, chat.id, "adder")
        logger.info("Группа %s привязана к пользователю %s", chat.id, event.from_user.id)
        return

    if old_status in ACTIVE_BOT_STATUSES and new_status in INACTIVE_BOT_STATUSES:
        await database.unlink_group_users(chat.id)
        logger.info("Группа %s отвязана: бот удален из чата", chat.id)
