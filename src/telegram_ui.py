"""Small constructors that keep keyboard creation concise with aiogram models."""

from aiogram.types import InlineKeyboardButton as _InlineKeyboardButton
from aiogram.types import InlineKeyboardMarkup as _InlineKeyboardMarkup


def InlineKeyboardButton(text: str, **kwargs) -> _InlineKeyboardButton:
    return _InlineKeyboardButton(text=text, **kwargs)


def InlineKeyboardMarkup(rows: list[list[_InlineKeyboardButton]]) -> _InlineKeyboardMarkup:
    return _InlineKeyboardMarkup(inline_keyboard=rows)


KeyboardButton = _InlineKeyboardButton
KeyboardMarkup = _InlineKeyboardMarkup
