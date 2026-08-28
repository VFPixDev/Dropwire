"""Group-only deletion of Dropwire cards by their original requester."""

from __future__ import annotations

import contextlib
import logging

from aiogram.exceptions import TelegramAPIError
from aiogram.types import Message

from src.services.database import Database
from src.services.settings import is_admin
from src.telegram_runtime import ApplicationState, BotAdapter

logger = logging.getLogger(__name__)
GROUP_TYPES = {"group", "supergroup"}
ADMIN_STATUSES = {"administrator", "creator", "owner"}


async def delete_card(message: Message, bot: BotAdapter, application: ApplicationState) -> None:
    if message.chat.type not in GROUP_TYPES or message.from_user is None:
        return
    if message.reply_to_message is None:
        await message.answer("Ответьте командой /del на карточку Dropwire.")
        return

    database = application.bot_data.get("database")
    if not isinstance(database, Database):
        await message.answer("База данных пока недоступна.")
        return
    delivery = await database.get_delivery_for_message(message.chat.id, message.reply_to_message.message_id)
    if delivery is None:
        await message.answer("Это сообщение не относится к сохранённой карточке Dropwire.")
        return

    if not await _can_delete(bot, message.chat.id, message.from_user.id, delivery["requester_user_id"]):
        await message.answer("Удалить карточку может отправитель ссылки или администратор группы.")
        return

    message_ids = delivery["message_ids"]
    try:
        if len(message_ids) == 1:
            await bot.delete_message(chat_id=message.chat.id, message_id=message_ids[0])
        else:
            await bot.delete_messages(chat_id=message.chat.id, message_ids=message_ids[:100])
    except TelegramAPIError as exc:
        logger.info("Не удалось удалить карточку chat_id=%s: %s", message.chat.id, exc)
        await message.answer("Telegram не позволил удалить карточку. Возможно, прошло больше 48 часов.")
        return

    await database.delete_delivery(delivery["id"])
    # The command is user-authored, so deleting it requires group admin rights.
    # Failure is harmless and must not make the successful card deletion look failed.
    with contextlib.suppress(TelegramAPIError):
        await bot.delete_message(chat_id=message.chat.id, message_id=message.message_id)


async def _can_delete(bot: BotAdapter, chat_id: int, user_id: int, requester_user_id: int) -> bool:
    if user_id == requester_user_id or is_admin(user_id):
        return True
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
    except TelegramAPIError:
        return False
    status = getattr(member.status, "value", member.status)
    return str(status) in ADMIN_STATUSES
