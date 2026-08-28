import asyncio
from datetime import datetime

from src.twitter.loader import fetch_complete_tweet
from src.twitter.models import MediaItem, Tweet


def test_localized_response_cannot_replace_original_media(monkeypatch):
    calls = []

    async def fake_fetch_data(tweet_id, username, language):
        calls.append(language)
        return {"language": language}

    async def fake_fetch_html(tweet_id, username, language):
        return ""

    def fake_parse_api(data, url):
        if data["language"] == "ru":
            return Tweet(
                display_name="Author",
                username="author",
                url=url,
                text="Localized response",
                date=datetime(2026, 8, 28),
                media=[MediaItem(type="video", url="https://video.twimg.com/720.mp4")],
                translated_text="Перевод",
                source_language="English",
            )
        return Tweet(
            display_name="Author",
            username="author",
            url=url,
            text="Original",
            date=datetime(2026, 8, 28),
            media=[
                MediaItem(type="video", url="https://video.twimg.com/1080.mp4"),
                MediaItem(type="photo", url="https://pbs.twimg.com/one.jpg"),
                MediaItem(type="photo", url="https://pbs.twimg.com/two.jpg"),
            ],
        )

    monkeypatch.setattr("src.twitter.loader.fetch_tweet_data", fake_fetch_data)
    monkeypatch.setattr("src.twitter.loader.fetch_tweet_html", fake_fetch_html)
    monkeypatch.setattr("src.twitter.loader.parse_tweet_api", fake_parse_api)

    tweet = asyncio.run(fetch_complete_tweet("https://x.com/author/status/1", "1", "author", "ru"))

    assert tweet is not None
    assert calls == [None, "ru"]
    assert [item.type for item in tweet.media] == ["video", "photo", "photo"]
    assert tweet.media[0].url.endswith("1080.mp4")
    assert tweet.translated_text == "Перевод"
    assert tweet.source_language == "English"
