"""aiogram event adapters used by Dropwire's handler layer.

The adapters deliberately expose only the small event surface Dropwire needs.
This keeps provider and rendering code independent from dispatcher internals.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramUnauthorizedError,
)
from aiogram.types import CallbackQuery, Chat, ChatMemberUpdated, InlineQuery, Message, User


class BotAdapter:
    def __init__(self, bot: Bot) -> None:
        self.raw = bot
        self.username: str | None = None

    @property
    def id(self) -> int:
        return self.raw.id

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)


class MessageAdapter:
    def __init__(self, message: Message) -> None:
        self.raw = message

    def __getattr__(self, name: str) -> Any:
        return getattr(self.raw, name)

    async def reply_text(self, text: str, **kwargs):
        return await self.raw.answer(text=text, **kwargs)


class CallbackQueryAdapter:
    def __init__(self, query: CallbackQuery) -> None:
        self.raw = query
        self.data = query.data
        self.from_user = query.from_user
        self.message = MessageAdapter(query.message) if isinstance(query.message, Message) else query.message

    async def answer(self, *args, **kwargs):
        return await self.raw.answer(*args, **kwargs)

    async def edit_message_text(self, text: str, **kwargs):
        if isinstance(self.raw.message, Message):
            return await self.raw.message.edit_text(text=text, **kwargs)
        return await self.raw.bot.edit_message_text(
            text=text,
            inline_message_id=self.raw.inline_message_id,
            **kwargs,
        )


class InlineQueryAdapter:
    def __init__(self, query: InlineQuery) -> None:
        self.raw = query
        self.id = query.id
        self.query = query.query
        self.from_user = query.from_user

    async def answer(self, results, **kwargs):
        return await self.raw.answer(results=results, **kwargs)


@dataclass
class Update:
    update_id: int
    bot: BotAdapter
    message: MessageAdapter | None = None
    callback_query: CallbackQueryAdapter | None = None
    inline_query: InlineQueryAdapter | None = None
    my_chat_member: ChatMemberUpdated | None = None
    effective_user: User | None = None
    effective_chat: Chat | None = None

    def get_bot(self) -> BotAdapter:
        return self.bot


@dataclass
class ApplicationState:
    bot_data: dict[str, Any] = field(default_factory=dict)


@dataclass
class HandlerContext:
    bot: BotAdapter
    application: ApplicationState
    args: list[str] = field(default_factory=list)
    error: BaseException | None = None


class ContextTypes:
    DEFAULT_TYPE = HandlerContext


BadRequest = TelegramBadRequest
Forbidden = TelegramForbiddenError
InvalidToken = TelegramUnauthorizedError
NetworkError = TelegramNetworkError
RetryAfter = TelegramRetryAfter
TelegramError = TelegramAPIError
TimedOut = TelegramNetworkError


def message_update(message: Message, bot: BotAdapter, update_id: int = 0) -> Update:
    return Update(
        update_id=update_id,
        bot=bot,
        message=MessageAdapter(message),
        effective_user=message.from_user,
        effective_chat=message.chat,
    )


def callback_update(query: CallbackQuery, bot: BotAdapter, update_id: int = 0) -> Update:
    chat = query.message.chat if isinstance(query.message, Message) else None
    return Update(
        update_id=update_id,
        bot=bot,
        callback_query=CallbackQueryAdapter(query),
        effective_user=query.from_user,
        effective_chat=chat,
    )


def inline_update(query: InlineQuery, bot: BotAdapter, update_id: int = 0) -> Update:
    return Update(
        update_id=update_id,
        bot=bot,
        inline_query=InlineQueryAdapter(query),
        effective_user=query.from_user,
    )


def member_update(event: ChatMemberUpdated, bot: BotAdapter, update_id: int = 0) -> Update:
    return Update(
        update_id=update_id,
        bot=bot,
        my_chat_member=event,
        effective_user=event.from_user,
        effective_chat=event.chat,
    )
