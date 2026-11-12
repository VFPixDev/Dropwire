"""Shared Twitter Rich Message renderer for inline and ordinary chats."""

from __future__ import annotations

from dataclasses import dataclass, replace
from html import escape
from html.parser import HTMLParser
import logging
from typing import Literal
from urllib.parse import urlparse

from aiogram.types import (
    BufferedInputFile,
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    InputRichMessageMedia,
    InputRichBlockAnimation,
    InputRichBlockBlockQuotation,
    InputRichBlockCollage,
    InputRichBlockDivider,
    InputRichBlockFooter,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockVideo,
    InputRichMessage,
    RichTextBold,
    RichTextCode,
    RichTextItalic,
    RichTextUrl,
)

from src.services.database import Database
from src.media.prepare import prepare_upload
from src.config import config
from src.services.media_cache import CachedMedia, cache_tweet_media
from src.twitter.fetcher import _is_trusted_twitter_media_url, download_media, get_trusted_twitter_mp4_url
from src.twitter.models import MediaItem, QuotedTweet, Tweet
from src.utils.text_format import (
    clean_tweet_text,
    format_date,
    format_number,
    format_poll,
    format_tweet_footer,
    translated_or_original_text,
)

logger = logging.getLogger(__name__)
MEDIA_UNAVAILABLE = "⚠️ Часть медиа недоступна. Откройте оригинал по кнопке ниже."


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
    media_mode: Literal["auto", "upload", "none"] = "auto",
) -> BuiltTwitterRichMessage | None:
    all_items = _all_media(tweet)
    prepared: list[PreparedMedia | None] = [None] * len(all_items)
    cache_urls: tuple[str, ...] = ()
    if media_mode == "auto" and database is not None:
        try:
            cached = await cache_tweet_media(bot, database, all_items)
        except Exception:
            logger.warning("Media cache unavailable; preparing media directly", exc_info=True)
            cached = []
        by_url = {item.source_url: item for item in cached}
        prepared = [
            PreparedMedia(item.type, _cached_input_media(by_url[item.url])) if item.url in by_url else None
            for item in all_items
        ]
        cache_urls = tuple(item.url for item, ready in zip(all_items, prepared, strict=True) if ready is not None)
    if not inline and media_mode != "none":
        for index, item in enumerate(all_items):
            if prepared[index] is None:
                direct = await _prepare_direct_media([item], upload_photos=media_mode == "upload")
                prepared[index] = direct[0]
    if inline:
        return _build_inline_rich_message(tweet, prepared, cache_urls, sender_quote, hashtags)

    cursor = 0

    def media_block(items: list[MediaItem]):
        nonlocal cursor
        selected = prepared[cursor : cursor + len(items)]
        cursor += len(items)
        blocks = []
        for item in selected:
            if item is None:
                continue
            if item.media_type == "photo":
                blocks.append(InputRichBlockPhoto(photo=item.media))
            elif item.media_type == "animation":
                blocks.append(InputRichBlockAnimation(animation=item.media))
            else:
                blocks.append(InputRichBlockVideo(video=item.media))
        if not blocks:
            return None
        return blocks[0] if len(blocks) == 1 else InputRichBlockCollage(blocks=blocks)

    blocks = []
    if sender_quote:
        blocks.extend(
            (
                InputRichBlockBlockQuotation(blocks=[_paragraph_block(sender_quote)]),
                InputRichBlockDivider(),
            )
        )

    blocks.append(_paragraph_block(_author_line(tweet)))
    main_text = _formatted_text(translated_or_original_text(tweet))
    if main_text:
        blocks.append(_paragraph_block(main_text))
    main_media = media_block(tweet.media)
    if main_media is not None:
        blocks.append(main_media)

    seen_references: set[str] = set()
    for reference in (tweet.quoted_tweet, tweet.parent_tweet):
        if reference is None:
            continue
        identity = reference.tweet_id or reference.url
        if identity in seen_references:
            cursor += len(reference.media)
            continue
        seen_references.add(identity)
        blocks.append(_reference_block(reference, media_block(reference.media)))

    if tweet.poll:
        blocks.append(_paragraph_block(_rich_text_html(format_poll(tweet.poll))))

    if any(item is None for item in prepared):
        blocks.append(_paragraph_block(MEDIA_UNAVAILABLE))

    blocks.extend((InputRichBlockDivider(), _paragraph_block(_stats_line(tweet))))
    footer = format_tweet_footer(tweet, hashtags)
    if footer:
        blocks.append(InputRichBlockFooter(text=_rich_text_from_html(footer)))

    return BuiltTwitterRichMessage(
        message=InputRichMessage(blocks=blocks),
        cache_urls=cache_urls,
    )


def _build_inline_rich_message(
    tweet: Tweet,
    prepared: list[PreparedMedia | None],
    cache_urls: tuple[str, ...],
    sender_quote: str,
    hashtags: str,
) -> BuiltTwitterRichMessage:
    attachments: list[InputRichMessageMedia] = []
    cursor = 0

    def media_html(items: list[MediaItem]) -> str:
        nonlocal cursor
        selected = prepared[cursor : cursor + len(items)]
        cursor += len(items)
        tags = []
        for item in selected:
            if item is None:
                continue
            media_id = f"m{len(attachments)}"
            attachments.append(InputRichMessageMedia(id=media_id, media=item.media))
            scheme = "photo" if item.media_type == "photo" else "video"
            if item.media_type == "photo":
                tags.append(f'<img src="tg://{scheme}?id={media_id}"/>')
            else:
                tags.append(f'<video src="tg://{scheme}?id={media_id}"></video>')
        if not tags:
            return ""
        return tags[0] if len(tags) == 1 else f"<tg-collage>{''.join(tags)}</tg-collage>"

    parts = []
    if sender_quote:
        parts.extend((sender_quote, "<hr/>"))

    parts.append(f"<p>{_author_line(tweet)}</p>")
    main_text = _formatted_text(translated_or_original_text(tweet))
    if main_text:
        parts.append(f"<p>{main_text}</p>")
    main_media = media_html(tweet.media)
    if main_media:
        parts.append(main_media)

    seen_references: set[str] = set()
    for reference in (tweet.quoted_tweet, tweet.parent_tweet):
        if reference is None:
            continue
        identity = reference.tweet_id or reference.url
        if identity in seen_references:
            cursor += len(reference.media)
            continue
        seen_references.add(identity)
        reference_parts = [f"<p>{_author_line(reference)}</p>"]
        reference_text = _formatted_text(translated_or_original_text(reference))
        if reference_text:
            reference_parts.append(f"<p>{reference_text}</p>")
        reference_media = media_html(reference.media)
        if reference_media:
            reference_parts.append(reference_media)
        parts.append(f"<blockquote>{''.join(reference_parts)}</blockquote>")

    if tweet.poll:
        parts.append(f"<p>{_rich_text_html(format_poll(tweet.poll))}</p>")
    if any(item is None for item in prepared):
        parts.append(f"<p>{MEDIA_UNAVAILABLE}</p>")
    parts.extend(("<hr/>", f"<p>{_stats_line(tweet)}</p>"))
    footer = format_tweet_footer(tweet, hashtags)
    if footer:
        parts.append(f"<footer>{footer}</footer>")

    return BuiltTwitterRichMessage(
        message=InputRichMessage(html="".join(parts), media=attachments or None),
        cache_urls=cache_urls,
    )


async def _prepare_direct_media(items: list[MediaItem], *, upload_photos: bool = False) -> list[PreparedMedia | None]:
    prepared: list[PreparedMedia | None] = []
    for index, item in enumerate(items):
        media_url = _trusted_media_url(item)
        if media_url is None:
            prepared.append(None)
            continue
        media_source: str | BufferedInputFile = media_url
        if upload_photos or item.type in {"video", "animation"}:
            try:
                content = await download_media(media_url, max_bytes=min(config.MAX_MEDIA_MB, 50) * 1024 * 1024)
            except Exception:
                logger.warning("Media preparation failed", exc_info=True)
                content = None
            if content is None:
                prepared.append(None)
                continue
            if upload_photos:
                content, metadata = await prepare_upload(content, item.type)
                if content is None:
                    prepared.append(None)
                    continue
                if metadata is not None:
                    item = replace(item, width=metadata.width, height=metadata.height, duration=metadata.duration)
            extension = "jpg" if item.type == "photo" else "mp4"
            media_source = BufferedInputFile(content, filename=f"twitter_{index}.{extension}")
        prepared.append(PreparedMedia(item.type, _direct_input_media(item, media_source)))
    return prepared


def _direct_input_media(item: MediaItem, media_source: str | BufferedInputFile):
    if item.type == "photo":
        return InputMediaPhoto(media=media_source)
    if item.type == "animation":
        return InputMediaAnimation(
            media=media_source,
            width=item.width,
            height=item.height,
            duration=item.duration,
        )
    return InputMediaVideo(
        media=media_source,
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


def _reference_block(reference: QuotedTweet, media_block):
    blocks = [_paragraph_block(_author_line(reference))]
    text = _formatted_text(translated_or_original_text(reference))
    if text:
        blocks.append(_paragraph_block(text))
    if media_block is not None:
        blocks.append(media_block)
    return InputRichBlockBlockQuotation(blocks=blocks)


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


def _paragraph_block(content: str):
    return InputRichBlockParagraph(text=_rich_text_from_html(content))


def _rich_text_html(text: str) -> str:
    return text.replace("\n", "<br>")


class _RichTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = [("root", {}, [])]

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "br":
            self.stack[-1][2].append("\n")
            return
        self.stack.append((tag, dict(attrs), []))

    def handle_startendtag(self, tag: str, attrs) -> None:
        if tag == "br":
            self.stack[-1][2].append("\n")
            return
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        while len(self.stack) > 1:
            current_tag, attrs, parts = self.stack.pop()
            rendered = _wrap_rich_text(current_tag, attrs, parts)
            if rendered != "":
                self.stack[-1][2].append(rendered)
            if current_tag == tag:
                break

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1][2].append(data)

    def result(self):
        while len(self.stack) > 1:
            self.handle_endtag(self.stack[-1][0])
        return _compact_rich_text(self.stack[0][2])


def _rich_text_from_html(content: str):
    parser = _RichTextParser()
    parser.feed(content)
    parser.close()
    return parser.result()


def _wrap_rich_text(tag: str, attrs: dict[str, str | None], parts: list):
    text = _compact_rich_text(parts)
    if text == "":
        return ""
    if tag == "a" and attrs.get("href"):
        return RichTextUrl(text=text, url=str(attrs["href"]))
    if tag in {"b", "strong"}:
        return RichTextBold(text=text)
    if tag in {"i", "em"}:
        return RichTextItalic(text=text)
    if tag == "code":
        return RichTextCode(text=text)
    return text


def _compact_rich_text(parts: list):
    compact = []
    for part in parts:
        if part == "":
            continue
        if isinstance(part, str) and compact and isinstance(compact[-1], str):
            compact[-1] += part
        else:
            compact.append(part)
    if not compact:
        return ""
    return compact[0] if len(compact) == 1 else compact
