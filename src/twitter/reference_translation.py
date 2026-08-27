"""Translation hydration for quoted and parent tweets."""

from __future__ import annotations

import asyncio
import logging

from src.twitter.fetcher import fetch_tweet_data
from src.twitter.models import QuotedTweet, Tweet
from src.twitter.normalize import extract_tweet_id
from src.twitter.parser_api import parse_tweet_api

logger = logging.getLogger(__name__)


async def hydrate_reference_translations(tweet: Tweet, language: str | None) -> None:
    if not language:
        return

    references = _unique_references(tweet)
    pending = [reference for reference in references if reference.text and not reference.translated_text]
    if not pending:
        return

    results = await asyncio.gather(
        *(_fetch_reference_translation(reference, language) for reference in pending),
        return_exceptions=True,
    )
    for reference, result in zip(pending, results, strict=True):
        if isinstance(result, Exception):
            logger.info("Не удалось перевести вложенный твит %s: %s", reference.url, type(result).__name__)
            continue
        if result is None or not result.translated_text:
            continue
        reference.translated_text = result.translated_text
        reference.source_language = result.source_language


async def _fetch_reference_translation(reference: QuotedTweet, language: str) -> Tweet | None:
    tweet_id = reference.tweet_id or extract_tweet_id(reference.url)
    if not tweet_id:
        return None
    data = await fetch_tweet_data(tweet_id, reference.username, language)
    return parse_tweet_api(data, reference.url) if data else None


def _unique_references(tweet: Tweet) -> list[QuotedTweet]:
    unique: list[QuotedTweet] = []
    seen: set[str] = set()
    for reference in (tweet.quoted_tweet, tweet.parent_tweet):
        if reference is None:
            continue
        identity = reference.tweet_id or reference.url
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(reference)
    return unique
