"""Shared Twitter Rich Message renderer for inline and ordinary chats."""

from __future__ import annotations

from dataclasses import dataclass

from aiogram.types import (
    InputMediaAnimation,
    InputMediaPhoto,
    InputMediaVideo,
    InputRichMessage,
    InputRichMessageMedia,
)

from src.services.database import Database
from src.services.media_cache import CachedMedia, cache_tweet_media
from src.twitter.models import Tweet


@dataclass(frozen=True)
class BuiltTwitterRichMessage:
    message: InputRichMessage
    cache_urls: tuple[str, ...]


async def build_twitter_rich_message(
    bot,
    database: Database | None,
    tweet: Tweet,
    text: str,
) -> BuiltTwitterRichMessage | None:
    if database is None:
        return None

    group_specs: list[tuple[str | None, list]] = []
    if tweet.media:
        group_specs.append((None, tweet.media))
    if tweet.quoted_tweet and tweet.quoted_tweet.media:
        group_specs.append(("Медиа цитируемого поста", tweet.quoted_tweet.media))
    if tweet.parent_tweet and tweet.parent_tweet.media:
        group_specs.append(("Медиа исходного поста", tweet.parent_tweet.media))
    if not group_specs:
        return None

    all_items = [item for _, items in group_specs for item in items]
    all_cached = await cache_tweet_media(bot, database, all_items)
    if len(all_cached) != len(all_items):
        return None

    cached_groups: list[tuple[str | None, list[CachedMedia]]] = []
    offset = 0
    for label, items in group_specs:
        cached_groups.append((label, all_cached[offset : offset + len(items)]))
        offset += len(items)

    attachments: list[InputRichMessageMedia] = []
    html_parts = [_rich_text_html(text)]
    media_index = 0
    for label, cached_items in cached_groups:
        refs: list[str] = []
        for cached in cached_items:
            media_id = f"m{media_index}"
            media_index += 1
            attachments.append(InputRichMessageMedia(id=media_id, media=_cached_input_media(cached)))
            source = f"tg://{_rich_media_scheme(cached.media_type)}?id={media_id}"
            refs.append(f'<img src="{source}"/>' if cached.media_type == "photo" else f'<video src="{source}"></video>')

        media_html = refs[0] if len(refs) == 1 else f"<tg-collage>{''.join(refs)}</tg-collage>"
        if label:
            html_parts.append(f"<blockquote><b>{label}</b>{media_html}</blockquote>")
        else:
            html_parts.append(media_html)

    return BuiltTwitterRichMessage(
        message=InputRichMessage(html="".join(html_parts), media=attachments),
        cache_urls=tuple(item.url for item in all_items),
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


def _rich_media_scheme(media_type: str) -> str:
    # Rich HTML represents silent MPEG-4 animations through the video scheme.
    return "photo" if media_type == "photo" else "video"


def _rich_text_html(text: str) -> str:
    return text.replace("\n", "<br>")
