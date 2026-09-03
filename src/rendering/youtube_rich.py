"""YouTube card renderer for Telegram Rich Messages."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from aiogram.types import (
    InputMediaPhoto,
    InputRichBlockBlockQuotation,
    InputRichBlockDivider,
    InputRichBlockFooter,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichMessage,
    InputRichMessageMedia,
    RichTextBold,
    RichTextUrl,
)

from src.models.media_card import MediaCard
from src.rendering.twitter_rich import _rich_text_from_html
from src.services.database import Database
from src.services.media_cache import cache_photo_media


@dataclass(frozen=True)
class BuiltYoutubeRichMessage:
    message: InputRichMessage
    cache_urls: tuple[str, ...] = ()


async def build_youtube_rich_message(
    bot,
    database: Database | None,
    card: MediaCard,
    *,
    sender_quote: str = "",
    hashtags: str = "",
    inline: bool = False,
) -> BuiltYoutubeRichMessage | None:
    if not card.thumbnail_url:
        return None

    if inline:
        if database is None:
            return None
        cached = await cache_photo_media(bot, database, card.thumbnail_url)
        if cached is None:
            return None
        return BuiltYoutubeRichMessage(
            message=_build_inline_message(card, cached.file_id, sender_quote, hashtags),
            cache_urls=(card.thumbnail_url,),
        )

    blocks = []
    if sender_quote:
        blocks.extend(
            (
                InputRichBlockBlockQuotation(
                    blocks=[InputRichBlockParagraph(text=_rich_text_from_html(sender_quote))]
                ),
                InputRichBlockDivider(),
            )
        )

    blocks.extend(
        (
            InputRichBlockPhoto(photo=InputMediaPhoto(media=card.thumbnail_url)),
            InputRichBlockParagraph(text=RichTextBold(text=card.title or "Без названия")),
            InputRichBlockParagraph(text=_author_text(card)),
            InputRichBlockFooter(text=format_youtube_metadata(card)),
        )
    )
    if hashtags:
        blocks.extend(
            (
                InputRichBlockDivider(),
                InputRichBlockFooter(text=hashtags),
            )
        )
    return BuiltYoutubeRichMessage(message=InputRichMessage(blocks=blocks))


def _build_inline_message(
    card: MediaCard,
    file_id: str,
    sender_quote: str,
    hashtags: str,
) -> InputRichMessage:
    parts = []
    if sender_quote:
        parts.extend((sender_quote, "<hr/>"))

    parts.extend(
        (
            '<img src="tg://photo?id=cover"/>',
            f"<p><b>{escape(card.title or 'Без названия')}</b></p>",
            f"<p>{_author_html(card)}</p>",
            f"<footer>{escape(format_youtube_metadata(card))}</footer>",
        )
    )
    if hashtags:
        parts.extend(("<hr/>", f"<footer>{escape(hashtags)}</footer>"))

    return InputRichMessage(
        html="".join(parts),
        media=[
            InputRichMessageMedia(
                id="cover",
                media=InputMediaPhoto(media=file_id),
            )
        ],
    )


def format_youtube_metadata(card: MediaCard) -> str:
    parts = []
    if card.stats.views is not None:
        views = card.stats.views
        label = _plural(views, "просмотр", "просмотра", "просмотров") if views < 1_000 else "просмотров"
        parts.append(f"{_format_compact_count(views)} {label}")
    if card.published_at is not None:
        parts.append(card.published_at.strftime("%d.%m.%Y"))
    if card.duration_text:
        parts.append(card.duration_text)
    return " · ".join(parts)


def _author_text(card: MediaCard):
    name = card.author_name or card.author_handle or "YouTube"
    if card.author_url:
        return RichTextUrl(text=name, url=card.author_url)
    return name


def _author_html(card: MediaCard) -> str:
    name = escape(card.author_name or card.author_handle or "YouTube")
    if card.author_url:
        return f'<a href="{escape(card.author_url, quote=True)}">{name}</a>'
    return name


def _format_compact_count(value: int) -> str:
    if value < 1_000:
        return str(value)
    if value < 1_000_000:
        return f"{_decimal(value / 1_000)} тыс."
    if value < 1_000_000_000:
        return f"{_decimal(value / 1_000_000)} млн"
    return f"{_decimal(value / 1_000_000_000)} млрд"


def _decimal(value: float) -> str:
    precision = 0 if value >= 10 else 1
    return f"{value:.{precision}f}".replace(".", ",")




def _plural(value: int, one: str, few: str, many: str) -> str:
    if value % 10 == 1 and value % 100 != 11:
        return one
    if value % 10 in {2, 3, 4} and value % 100 not in {12, 13, 14}:
        return few
    return many
