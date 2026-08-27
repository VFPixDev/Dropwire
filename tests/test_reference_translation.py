import asyncio
from datetime import datetime

from src.twitter.models import QuotedTweet, Tweet
from src.twitter.reference_translation import hydrate_reference_translations


def test_reference_translation_is_fetched_without_extra_labels(monkeypatch):
    async def fake_fetch(tweet_id, username, language):
        assert (tweet_id, username, language) == ("10", "parent", "ru")
        return {
            "tweet": {
                "id": "10",
                "text": "Original",
                "author": {"name": "Parent", "screen_name": "parent"},
                "translation": {
                    "text": "Перевод исходного твита",
                    "source_lang": "en",
                    "source_lang_en": "English",
                },
            }
        }

    monkeypatch.setattr("src.twitter.reference_translation.fetch_tweet_data", fake_fetch)
    parent = QuotedTweet(
        display_name="Parent",
        username="parent",
        url="https://x.com/parent/status/10",
        tweet_id="10",
        text="Original",
    )
    tweet = Tweet(
        display_name="Outer",
        username="outer",
        url="https://x.com/outer/status/11",
        text="Reply",
        date=datetime(2026, 8, 27),
        parent_tweet=parent,
    )

    asyncio.run(hydrate_reference_translations(tweet, "ru"))

    assert parent.translated_text == "Перевод исходного твита"
    assert parent.source_language == "English"
