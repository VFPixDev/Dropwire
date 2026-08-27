"""Shared Twitter Rich Message renderer for inline and ordinary chats."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape
from urllib.parse import urlparse

from aiogram.types import (
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    InputRichMessage,
    InputRichMessageMedia,
)

from src.services.database import Database
from src.services.media_cache import CachedMedia, cache_tweet_media
from src.twitter.fetcher import _is_trusted_twitter_media_url, get_trusted_twitter_mp4_url
from src.twitter.models import MediaItem, QuotedTweet, Tweet
from src.utils.text_format import (
    clean_tweet_text,
    format_date,
    format_number,
    format_poll,
    format_tweet_footer,
    translated_or_original_text,
)


@dataclass(frozen=True)
class BuiltTwitterRichMessage:
    message: InputRichMessage
    cache_urls: tuple[str, ...]


@dataclass(frozen=True)
class PreparedMedia:
    media_type: str
    media: InputMediaPhoto | InputMediaVideo | InputMediaAnimation


async def build_twitter_rich_message(
    bot,
    database: Database | None,
    tweet: Tweet,
    *,
    sender_quote: str = "",
    hashtags: str = "",
    inline: bool = False,
    staging_chat_id: int | None = None,
) -> BuiltTwitterRichMessage | None:
    all_items = _all_media(tweet)
    if inline:
        prepared = await _prepare_inline_media(bot, database, all_items, staging_chat_id)
    else:
        prepared = _prepare_direct_media(all_items)
    if prepared is None:
        return None

    attachments: list[InputRichMessageMedia] = []
    cursor = 0

    def media_html(items: list[MediaItem]) -> str:
        nonlocal cursor
        selected = prepared[cursor : cursor + len(items)]
        cursor += len(items)
        refs: list[str] = []
        for item in selected:
            media_id = f"m{len(attachments)}"
            attachments.append(InputRichMessageMedia(id=media_id, media=item.media))
            source = f"tg://{_rich_media_scheme(item.media_type)}?id={media_id}"
            tag = f'<img src="{source}"/>' if item.media_type == "photo" else f'<video src="{source}"></video>'
            refs.append(tag)
        if not refs:
            return ""
        return refs[0] if len(refs) == 1 else f"<tg-collage>{''.join(refs)}</tg-collage>"

    html_parts: list[str] = []
    if sender_quote:
        html_parts.extend((sender_quote, "<hr/>"))

    html_parts.append(_paragraph(_author_line(tweet)))
    main_text = _formatted_text(translated_or_original_text(tweet))
    if main_text:
        html_parts.append(_paragraph(main_text))
    html_parts.append(media_html(tweet.media))

    seen_references: set[str] = set()
    for reference in (tweet.quoted_tweet, tweet.parent_tweet):
        if reference is None:
            continue
        identity = reference.tweet_id or reference.url
        if identity in seen_references:
            cursor += len(reference.media)
            continue
        seen_references.add(identity)
        html_parts.append(_reference_html(reference, media_html(reference.media)))

    if tweet.poll:
        html_parts.append(_paragraph(_rich_text_html(format_poll(tweet.poll))))

    html_parts.extend(("<hr/>", _paragraph(_stats_line(tweet))))
    footer = format_tweet_footer(tweet, hashtags)
    if footer:
        html_parts.append(f"<footer>{footer}</footer>")

    return BuiltTwitterRichMessage(
        message=InputRichMessage(html="".join(part for part in html_parts if part), media=attachments or None),
        cache_urls=tuple(item.url for item in all_items) if inline else (),
    )


async def _prepare_inline_media(
    bot,
    database: Database | None,
    items: list[MediaItem],
    staging_chat_id: int | None,
) -> list[PreparedMedia] | None:
    if not items:
        return []
    if database is None:
        return None
    cached = await cache_tweet_media(bot, database, items, staging_chat_id=staging_chat_id)
    if len(cached) != len(items):
        return None
    return [PreparedMedia(item.media_type, _cached_input_media(item)) for item in cached]


def _prepare_direct_media(items: list[MediaItem]) -> list[PreparedMedia] | None:
    prepared: list[PreparedMedia] = []
    for item in items:
        media_url = _trusted_media_url(item)
        if media_url is None:
            return None
        prepared.append(PreparedMedia(item.type, _direct_input_media(item, media_url)))
    return prepared


def _direct_input_media(item: MediaItem, media_url: str):
    if item.type == "photo":
        return InputMediaPhoto(media=media_url)
    if item.type == "animation":
        return InputMediaAnimation(
            media=media_url,
            width=item.width,
            height=item.height,
            duration=item.duration,
        )
    return InputMediaVideo(
        media=media_url,
        width=item.width,
        height=item.height,
        duration=item.duration,
        supports_streaming=True,
    )


def _cached_input_media(cached: CachedMedia):
    if cached.media_type == "photo":
        return InputMediaPhoto(media=cached.file_id)
    if cached.media_type == "animation":
        return InputMediaAnimation(
            media=cached.file_id,
            width=cached.width,
            height=cached.height,
            duration=cached.duration,
        )
    return InputMediaVideo(
        media=cached.file_id,
        width=cached.width,
        height=cached.height,
        duration=cached.duration,
        supports_streaming=True,
    )


def _trusted_media_url(item: MediaItem) -> str | None:
    if item.type in {"video", "animation"}:
        return get_trusted_twitter_mp4_url(item.url)
    return item.url if _is_trusted_twitter_media_url(urlparse(item.url)) else None


def _all_media(tweet: Tweet) -> list[MediaItem]:
    items = list(tweet.media)
    if tweet.quoted_tweet:
        items.extend(tweet.quoted_tweet.media)
    if tweet.parent_tweet:
        items.extend(tweet.parent_tweet.media)
    return items


def _reference_html(reference: QuotedTweet, media_html: str) -> str:
    parts = [_paragraph(_author_line(reference))]
    text = _formatted_text(translated_or_original_text(reference))
    if text:
        parts.append(_paragraph(text))
    if media_html:
        parts.append(media_html)
    return f"<blockquote>{''.join(parts)}</blockquote>"


def _author_line(item: Tweet | QuotedTweet) -> str:
    date_suffix = ""
    if item.date:
        date, time = format_date(item.date)
        date_suffix = f" — {date}, {time}"
    username = escape(item.username)
    return f'{escape(item.display_name)} (<a href="https://x.com/{username}">@{username}</a>){date_suffix}'


def _stats_line(tweet: Tweet) -> str:
    stats = tweet.stats
    return "  ".join(
        (
            f"💬 {format_number(stats.replies) if stats.replies is not None else '—'}",
            f"🔁 {format_number(stats.reposts) if stats.reposts is not None else '—'}",
            f"❤️ {format_number(stats.likes) if stats.likes is not None else '—'}",
            f"👁 {format_number(stats.views) if stats.views is not None else '—'}",
        )
    )


def _formatted_text(text: str) -> str:
    return _rich_text_html(clean_tweet_text(text))


def _paragraph(content: str) -> str:
    return f"<p>{content}</p>"


def _rich_media_scheme(media_type: str) -> str:
    return "photo" if media_type == "photo" else "video"


def _rich_text_html(text: str) -> str:
    return text.replace("\n", "<br>")
