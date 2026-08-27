from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
from html import escape
import logging
import re
from urllib.parse import parse_qs, urlparse

from aiogram.types import (
    InlineQueryResult,
    InlineQueryResultArticle,
    InlineQueryResultMpeg4Gif,
    InlineQueryResultPhoto,
    InlineQueryResultVideo,
    InputRichMessageContent,
    InputTextMessageContent,
    User,
)
from aiogram.enums import ParseMode

from src.telegram_runtime import BadRequest, ContextTypes, Update
from src.telegram_ui import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import config
from src.handlers.messages import telegram_timeout_kwargs
from src.models.media_card import MediaCard
from src.providers.link_router import LinkMatch, find_supported_links
from src.providers.soundcloud import fetch_soundcloud_card
from src.providers.spotify import fetch_spotify_card
from src.providers.youtube import fetch_youtube_card
from src.rendering.hashtags import build_hashtags, render_hashtags
from src.rendering.telegram_cards import format_card_text
from src.rendering.twitter_rich import build_twitter_rich_message
from src.services.database import Database
from src.services.providers import is_provider_enabled
from src.services.settings import EffectiveSettings, get_effective_settings, get_translation_language, is_user_allowed
from src.twitter.fetcher import fetch_tweet_data, fetch_tweet_html, get_trusted_twitter_mp4_url
from src.twitter.normalize import extract_tweet_id, extract_username, normalize_url
from src.twitter.parser import parse_tweet_html
from src.twitter.parser_api import parse_tweet_api
from src.twitter.models import Tweet
from src.utils.sender_quote import format_sender_quote
from src.utils.text_format import format_tweet_card

logger = logging.getLogger(__name__)

INLINE_FETCH_TIMEOUT_SECONDS = 8
INLINE_CACHE_SECONDS = 60
_inline_fetch_slots = asyncio.Semaphore(4)


@dataclass(frozen=True)
class BuiltInlineResult:
    primary: InlineQueryResult
    fallback: InlineQueryResultArticle
    cache_urls: tuple[str, ...] = ()


async def handle_inline_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.inline_query
    user = update.effective_user
    if query is None or user is None:
        return

    if not is_user_allowed(user.id):
        await _answer_inline(query, [])
        return

    links = find_supported_links(query.query or "")
    if not links:
        await _answer_inline(query, [], cache_time=1)
        return

    link = links[0]
    database_value = context.application.bot_data.get("database")
    database = database_value if isinstance(database_value, Database) else None
    if not await is_provider_enabled(database, link.source):
        await _answer_inline(query, [], cache_time=5)
        return

    settings = await get_effective_settings(database, update)
    comment = (query.query or "")[: link.start].strip() or None

    try:
        async with asyncio.timeout(INLINE_FETCH_TIMEOUT_SECONDS):
            async with _inline_fetch_slots:
                built = await _build_inline_result(update, database, link, settings, user, comment)
    except TimeoutError:
        logger.info("Inline timeout user_id=%s source=%s", user.id, link.source)
        await _answer_inline(query, [], cache_time=1)
        return
    except Exception as exc:
        logger.warning("Inline fetch failed user_id=%s source=%s error=%s", user.id, link.source, type(exc).__name__)
        await _answer_inline(query, [], cache_time=1)
        return

    if built is None:
        await _answer_inline(query, [], cache_time=5)
        return

    try:
        await _answer_inline(query, [built.primary])
    except BadRequest as exc:
        if built.primary is built.fallback:
            raise
        logger.info("Telegram rejected inline preview, using article fallback: %s", exc)
        if database is not None and built.cache_urls:
            await database.delete_cached_media(list(built.cache_urls))
        await _answer_inline(query, [built.fallback], cache_time=1)


async def _build_inline_result(
    update: Update,
    database: Database | None,
    link: LinkMatch,
    settings: EffectiveSettings,
    user: User,
    comment: str | None,
) -> BuiltInlineResult | None:
    if link.source == "twitter":
        language = await get_translation_language(database, update)
        tweet = await _fetch_tweet(link.url, language)
        if tweet is None:
            return None

        text = format_tweet_card(tweet, include_translation=bool(tweet.translated_text))
        if settings.enable_hashtags:
            hashtags = render_hashtags(build_hashtags("twitter", "post", tweet.username))
            if hashtags:
                text = f"{text}\n\n{hashtags}"
        text = _prepend_sender_quote(text, user, comment, settings)
        preview_url = _tweet_preview_url(tweet)
        title = f"{tweet.display_name} (@{tweet.username})"
        description = _plain_description(tweet.text)
        keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 Открыть оригинал", url=tweet.url)]])
        rich_result = await _build_rich_twitter_result(
            update,
            database,
            link,
            tweet,
            title,
            description,
            text,
            preview_url,
            keyboard,
            settings,
        )
        if rich_result is not None:
            return rich_result
        return _build_twitter_result(link, tweet, title, description, text, preview_url, keyboard, settings)

    card = await _fetch_media_card(link)
    if card is None:
        return None
    if not settings.enable_hashtags:
        card.hashtags = []

    text = _prepend_sender_quote(format_card_text(card), user, comment, settings)
    title = card.title or _source_title(card.source)
    description = _card_description(card)
    keyboard = _url_only_keyboard(card)
    return _build_result(link, title, description, text, card.thumbnail_url, keyboard, settings)


async def _fetch_media_card(link: LinkMatch) -> MediaCard | None:
    if link.source == "youtube":
        return await fetch_youtube_card(link.url)
    if link.source == "spotify":
        return await fetch_spotify_card(link.url)
    if link.source == "soundcloud":
        return await fetch_soundcloud_card(link.url)
    return None


async def _fetch_tweet(url: str, language: str | None):
    normalized_url = normalize_url(url)
    if not normalized_url:
        return None
    tweet_id = extract_tweet_id(normalized_url)
    username = extract_username(normalized_url)
    if not tweet_id or not username:
        return None

    data = await fetch_tweet_data(tweet_id, username, language)
    tweet = parse_tweet_api(data, normalized_url) if data else None
    if tweet is None or (language and not tweet.translated_text):
        html = await fetch_tweet_html(tweet_id, username, language)
        html_tweet = parse_tweet_html(html, normalized_url) if html else None
        if html_tweet is not None:
            tweet = html_tweet
    return tweet


def _build_result(
    link: LinkMatch,
    title: str,
    description: str,
    text: str,
    preview_url: str | None,
    keyboard: InlineKeyboardMarkup | None,
    settings: EffectiveSettings,
) -> BuiltInlineResult:
    safe_title = _single_line(title, 120) or _source_title(link.source)
    safe_description = _single_line(description, 180)
    message_text = _fit_message_text(text, safe_title, link.url)
    result_key = sha256(f"{link.source}:{link.url}:{message_text}".encode("utf-8")).hexdigest()[:32]
    article = InlineQueryResultArticle(
        id=f"a{result_key}",
        title=safe_title,
        description=safe_description,
        thumbnail_url=preview_url,
        input_message_content=InputTextMessageContent(
            message_text=message_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        ),
        reply_markup=keyboard,
    )

    if not preview_url or len(message_text) > 1024:
        return BuiltInlineResult(primary=article, fallback=article)

    photo = InlineQueryResultPhoto(
        id=f"p{result_key}",
        photo_url=preview_url,
        thumbnail_url=preview_url,
        title=safe_title,
        description=safe_description,
        caption=message_text,
        parse_mode=ParseMode.HTML,
        show_caption_above_media=settings.caption_above_media,
        reply_markup=keyboard,
    )
    return BuiltInlineResult(primary=photo, fallback=article)


def _build_twitter_result(
    link: LinkMatch,
    tweet: Tweet,
    title: str,
    description: str,
    text: str,
    preview_url: str | None,
    keyboard: InlineKeyboardMarkup | None,
    settings: EffectiveSettings,
) -> BuiltInlineResult:
    fallback = _build_result(link, title, description, text, preview_url, keyboard, settings)
    message_text = _fit_message_text(text, title, link.url)
    if len(message_text) > 1024:
        return fallback

    for media_item in tweet.media:
        if media_item.type != "animation":
            continue
        animation_url = get_trusted_twitter_mp4_url(media_item.url)
        thumbnail_url = _trusted_twitter_jpeg_url(media_item.thumbnail_url) or _trusted_twitter_jpeg_url(preview_url)
        if not animation_url or not thumbnail_url:
            continue
        result_key = sha256(f"gif:{link.url}:{message_text}".encode("utf-8")).hexdigest()[:32]
        animation = InlineQueryResultMpeg4Gif(
            id=f"g{result_key}",
            mpeg4_url=animation_url,
            thumbnail_url=thumbnail_url,
            mpeg4_width=media_item.width,
            mpeg4_height=media_item.height,
            mpeg4_duration=media_item.duration,
            title=_single_line(title, 120),
            caption=message_text,
            parse_mode=ParseMode.HTML,
            show_caption_above_media=settings.caption_above_media,
            reply_markup=keyboard,
        )
        return BuiltInlineResult(primary=animation, fallback=fallback.fallback)

    video_url = None
    thumbnail_url = None
    for media_item in tweet.media:
        if media_item.type != "video":
            continue
        candidate_url = get_trusted_twitter_mp4_url(media_item.url)
        candidate_thumbnail = _trusted_twitter_jpeg_url(media_item.thumbnail_url) or _trusted_twitter_jpeg_url(
            preview_url
        )
        if candidate_url and candidate_thumbnail:
            video_url = candidate_url
            thumbnail_url = candidate_thumbnail
            break

    if video_url is None or thumbnail_url is None:
        return fallback

    safe_title = _single_line(title, 120) or _source_title(link.source)
    safe_description = _single_line(description, 180)
    result_key = sha256(f"{link.source}:{link.url}:{message_text}".encode("utf-8")).hexdigest()[:32]
    video = InlineQueryResultVideo(
        id=f"v{result_key}",
        video_url=video_url,
        mime_type="video/mp4",
        thumbnail_url=thumbnail_url,
        title=safe_title,
        description=safe_description,
        caption=message_text,
        parse_mode=ParseMode.HTML,
        show_caption_above_media=settings.caption_above_media,
        reply_markup=keyboard,
    )
    return BuiltInlineResult(primary=video, fallback=fallback.fallback)


async def _build_rich_twitter_result(
    update: Update,
    database: Database | None,
    link: LinkMatch,
    tweet: Tweet,
    title: str,
    description: str,
    text: str,
    preview_url: str | None,
    keyboard: InlineKeyboardMarkup | None,
    settings: EffectiveSettings,
) -> BuiltInlineResult | None:
    if database is None:
        return None

    rich = await build_twitter_rich_message(update.get_bot(), database, tweet, text)
    if rich is None:
        return None

    safe_title = _single_line(title, 120) or _source_title(link.source)
    safe_description = _single_line(description, 180)
    fallback = _build_twitter_result(link, tweet, title, description, text, preview_url, keyboard, settings).fallback
    result_key = sha256(f"rich:{link.url}:{text}".encode("utf-8")).hexdigest()[:32]
    article = InlineQueryResultArticle(
        id=f"r{result_key}",
        title=safe_title,
        description=safe_description,
        thumbnail_url=preview_url,
        input_message_content=InputRichMessageContent(
            rich_message=rich.message
        ),
        reply_markup=keyboard,
    )
    return BuiltInlineResult(
        primary=article,
        fallback=fallback,
        cache_urls=rich.cache_urls,
    )


def _fit_message_text(text: str, title: str, original_url: str) -> str:
    if len(text) <= 4096:
        return text
    available = max(0, 4096 - len(title) - len(original_url) - 40)
    return f"<b>{escape(title)}</b>\n\n{escape(_single_line(text, available))}\n\n{escape(original_url)}"


def _prepend_sender_quote(
    text: str,
    user: User,
    comment: str | None,
    settings: EffectiveSettings,
) -> str:
    if not settings.include_sender_quote:
        return text
    return f"{format_sender_quote(user, comment, settings.sender_quote_mode)}\n\n{text}"


def _url_only_keyboard(card: MediaCard) -> InlineKeyboardMarkup | None:
    rows = [[InlineKeyboardButton(button.text, url=button.url)] for button in card.buttons if button.url]
    return InlineKeyboardMarkup(rows) if rows else None


def _tweet_preview_url(tweet) -> str | None:
    for media in tweet.media:
        if media.type == "photo":
            return media.url
        if media.thumbnail_url:
            return media.thumbnail_url
    return None


def _trusted_twitter_jpeg_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or parsed.fragment
        or hostname not in {"pbs.twimg.com", "pbs.fxtwitter.com"}
    ):
        return None

    extension = parsed.path.lower().rsplit(".", maxsplit=1)[-1] if "." in parsed.path else ""
    query_format = parse_qs(parsed.query).get("format", [""])[0].lower()
    if extension not in {"jpg", "jpeg"} and query_format not in {"jpg", "jpeg"}:
        return None
    return url


def _card_description(card: MediaCard) -> str:
    parts = [_source_title(card.source)]
    if card.author_name:
        parts.append(card.author_name)
    if card.duration_text:
        parts.append(card.duration_text)
    return " · ".join(parts)


def _source_title(source: str) -> str:
    return {
        "twitter": "Twitter/X",
        "youtube": "YouTube",
        "spotify": "Spotify",
        "soundcloud": "SoundCloud",
    }.get(source, config.APP_NAME)


def _plain_description(text: str) -> str:
    return _single_line(re.sub(r"<[^>]+>", " ", text or ""), 180)


def _single_line(text: str, limit: int) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


async def _answer_inline(query, results: list[InlineQueryResult], cache_time: int = INLINE_CACHE_SECONDS) -> None:
    timeouts = telegram_timeout_kwargs()
    await query.answer(
        results=results,
        cache_time=cache_time,
        is_personal=True,
        request_timeout=min(timeouts["request_timeout"], 5),
    )
