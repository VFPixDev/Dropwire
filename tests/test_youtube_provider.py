import asyncio

from src.providers.youtube import fetch_youtube_card


class FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params):
        self.calls.append((url, params))
        if "videos" in url:
            return FakeResponse(
                200,
                {
                    "items": [
                        {
                            "snippet": {
                                "title": "Video title",
                                "description": "Long description that should not be rendered",
                                "channelTitle": "Канал с пробелами",
                                "channelId": "channel-1",
                                "publishedAt": "2026-07-01T12:00:00Z",
                                "liveBroadcastContent": "none",
                                "thumbnails": {"high": {"url": "https://example.com/thumb.jpg"}},
                            },
                            "statistics": {"viewCount": "10", "likeCount": "2"},
                            "contentDetails": {"duration": "PT1M05S"},
                        }
                    ]
                },
            )
        return FakeResponse(200, {"items": [{"snippet": {"customUrl": "@pilmek"}}]})


def test_fetch_youtube_card_omits_description_and_uses_channel_handle(monkeypatch):
    monkeypatch.setattr("src.providers.youtube.config.YOUTUBE_API_KEY", "key")
    monkeypatch.setattr("src.providers.youtube.httpx.AsyncClient", FakeAsyncClient)

    card = asyncio.run(fetch_youtube_card("https://youtu.be/dQw4w9WgXcQ"))

    assert card.text is None
    assert card.author_name == "Канал с пробелами"
    assert card.author_handle == "@pilmek"
    assert card.hashtags == ["#youtube", "#video", "#pilmek"]
