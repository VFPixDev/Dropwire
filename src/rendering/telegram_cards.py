from __future__ import annotations

from html import escape

from src.telegram_ui import InlineKeyboardButton, InlineKeyboardMarkup

from src.models.media_card import Button, MediaCard
from src.rendering.hashtags import render_hashtags


def format_count(count: int | None) -> str:
    if count is None:
        return "-"
    return f"{count:,}".replace(",", " ")


def format_card_text(card: MediaCard) -> str:
    lines: list[str] = []

    if card.source == "youtube":
        lines.append(f"📺 {escape(card.title or 'Без названия')}")
        lines.append("")

        meta_parts = []
        if card.author_name:
            meta_parts.append(f"👤 {escape(card.author_name)}")
        if card.stats.views is not None:
            meta_parts.append(f"👁 {format_count(card.stats.views)}")
        if card.stats.likes is not None:
            meta_parts.append(f"👍 {format_count(card.stats.likes)}")
        if meta_parts:
            lines.append(" ".join(meta_parts))

        detail_parts = []
        if card.duration_text:
            detail_parts.append(f"⏱️ {escape(card.duration_text)}")
        if card.published_at:
            detail_parts.append(f"📅 {card.published_at.strftime('%d.%m.%Y')}")
        if detail_parts:
            lines.append(" ".join(detail_parts))

        if card.text:
            lines.append("")
            lines.append(f"📄 {escape(card.text)}")
    elif card.source in {"spotify", "soundcloud"}:
        icon = "🎙" if card.media_type == "podcast" else "🎵"
        lines.append(f"{icon} {escape(card.title or 'Без названия')}")
        if card.author_name:
            lines.append("")
            lines.append(f"👤 {escape(card.author_name)}")
        details = []
        if card.duration_text:
            details.append(f"⏱️ {escape(card.duration_text)}")
        if card.published_at:
            details.append(f"📅 {card.published_at.strftime('%d.%m.%Y')}")
        if details:
            lines.append(" ".join(details))
    else:
        if card.title:
            lines.append(escape(card.title))
        if card.text:
            lines.append(escape(card.text))

    hashtags = render_hashtags(card.hashtags)
    if hashtags:
        lines.append("")
        lines.append(hashtags)

    return "\n".join(lines)


def build_card_keyboard(card: MediaCard) -> InlineKeyboardMarkup | None:
    buttons = [telegram_button for button in card.buttons if (telegram_button := _build_button(button))]
    if not buttons:
        return None
    if card.source == "youtube":
        return InlineKeyboardMarkup([buttons])
    return InlineKeyboardMarkup([[button] for button in buttons])


def _build_button(button: Button) -> InlineKeyboardButton | None:
    if button.url:
        return InlineKeyboardButton(button.text, url=button.url)
    if button.callback_data:
        return InlineKeyboardButton(button.text, callback_data=button.callback_data)
    return None
