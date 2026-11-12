"""Load a complete tweet while keeping localization metadata separate."""

from __future__ import annotations

import asyncio
import logging

from src.twitter.fetcher import fetch_tweet_data, fetch_tweet_html
from src.twitter.models import Tweet
from src.twitter.parser import parse_tweet_html
from src.twitter.parser_api import parse_tweet_api
from src.twitter.reference_translation import hydrate_reference_translations
from src.twitter.translate import valid_translation

logger = logging.getLogger(__name__)


async def fetch_complete_tweet(
    normalized_url: str,
    tweet_id: str,
    username: str,
    language: str | None,
) -> Tweet | None:
    if language:
        original, localized = await asyncio.gather(
            _safe_fetch_version(normalized_url, tweet_id, username, None),
            _safe_fetch_version(normalized_url, tweet_id, username, language),
        )
    else:
        original = await _safe_fetch_version(normalized_url, tweet_id, username, None)
        localized = None

    if original is None:
        original = localized
    if original is None:
        return None

    if localized is not None and valid_translation(localized.translated_text):
        original.translated_text = valid_translation(localized.translated_text)
        original.source_language = localized.source_language

    await hydrate_reference_translations(original, language)
    return original


async def _safe_fetch_version(normalized_url: str, tweet_id: str, username: str, language: str | None) -> Tweet | None:
    try:
        return await _fetch_version(normalized_url, tweet_id, username, language)
    except Exception:
        logger.warning("Could not load tweet version tweet_id=%s language=%s", tweet_id, language, exc_info=True)
        return None


async def _fetch_version(
    normalized_url: str,
    tweet_id: str,
    username: str,
    language: str | None,
) -> Tweet | None:
    data = await fetch_tweet_data(tweet_id, username, language)
    tweet = parse_tweet_api(data, normalized_url) if data else None
    if tweet is not None and (not language or valid_translation(tweet.translated_text)):
        return tweet

    html = await fetch_tweet_html(tweet_id, username, language)
    html_tweet = parse_tweet_html(html, normalized_url) if html else None
    if tweet is None:
        return html_tweet
    if html_tweet is not None and html_tweet.translated_text:
        tweet.translated_text = html_tweet.translated_text
        tweet.source_language = html_tweet.source_language
    return tweet
