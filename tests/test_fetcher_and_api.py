import asyncio

import pytest

from urllib.parse import urlparse

from src.twitter.fetcher import (
    MediaTooLargeError,
    ResponseTooLargeError,
    _download_media_once,
    _get_with_retry,
    _is_safe_media_url,
    _is_trusted_twitter_media_host,
    _is_trusted_twitter_media_url,
)
from src.twitter.parser_api import parse_tweet_api


class FakeStreamResponse:
    def __init__(self, status_code=200, chunks=None, headers=None):
        self.status_code = status_code
        self._chunks = chunks or []
        self.headers = headers or {}
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def aiter_bytes(self):
        for chunk in self._chunks:
            yield chunk


class FakeClient:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, method, url, headers):
        return self.response


def test_download_media_rejects_large_content_length(monkeypatch):
    response = FakeStreamResponse(headers={"Content-Length": "11"})
    monkeypatch.setattr("src.twitter.fetcher.httpx.AsyncClient", lambda *args, **kwargs: FakeClient(response))

    with pytest.raises(MediaTooLargeError):
        asyncio.run(_download_media_once("https://example.com/file.jpg", {}, max_bytes=10))


def test_download_media_rejects_stream_that_exceeds_limit(monkeypatch):
    response = FakeStreamResponse(chunks=[b"12345", b"67890", b"x"])
    monkeypatch.setattr("src.twitter.fetcher.httpx.AsyncClient", lambda *args, **kwargs: FakeClient(response))

    with pytest.raises(MediaTooLargeError):
        asyncio.run(_download_media_once("https://example.com/file.jpg", {}, max_bytes=10))


def test_fxtwitter_response_is_bounded_before_parsing():
    response = FakeStreamResponse(chunks=[b"12345", b"67890", b"x"])
    client = FakeClient(response)

    with pytest.raises(ResponseTooLargeError):
        asyncio.run(_get_with_retry(client, "https://fxtwitter.com/api/status/1", {}, max_bytes=10))


def test_media_url_safety_blocks_local_targets():
    assert _is_safe_media_url(urlparse("https://pbs.twimg.com/media/file.jpg")) is True
    assert _is_safe_media_url(urlparse("file:///etc/passwd")) is False
    assert _is_safe_media_url(urlparse("http://localhost/file.jpg")) is False
    assert _is_safe_media_url(urlparse("http://127.0.0.1/file.jpg")) is False
    assert _is_safe_media_url(urlparse("http://10.0.0.1/file.jpg")) is False
    assert _is_trusted_twitter_media_host("pbs.twimg.com") is True
    assert _is_trusted_twitter_media_host("pbs.fxtwitter.com") is True
    assert _is_trusted_twitter_media_host("video.twimg.com") is True
    assert _is_trusted_twitter_media_host("pbs.twimg.com.evil.example") is False
    assert _is_trusted_twitter_media_host("pbs.fxtwitter.com.evil.example") is False


def test_fxtwitter_media_redirect_is_strictly_constrained():
    trusted = urlparse(
        "https://api.fxtwitter.com/2/go?url=https%3A%2F%2Fvideo.twimg.com%2Fvideo.mp4%3Ftag%3D1"
    )
    local_target = urlparse("https://api.fxtwitter.com/2/go?url=http%3A%2F%2F127.0.0.1%2Fsecret")
    lookalike_target = urlparse(
        "https://api.fxtwitter.com/2/go?url=https%3A%2F%2Fvideo.twimg.com.evil.example%2Fvideo.mp4"
    )
    wrong_path = urlparse("https://api.fxtwitter.com/other?url=https%3A%2F%2Fvideo.twimg.com%2Fvideo.mp4")

    assert _is_trusted_twitter_media_url(trusted) is True
    assert _is_trusted_twitter_media_url(local_target) is False
    assert _is_trusted_twitter_media_url(lookalike_target) is False
    assert _is_trusted_twitter_media_url(wrong_path) is False


def test_parse_tweet_api_minimal_payload():
    tweet = parse_tweet_api(
        {
            "tweet": {
                "text": "Hello from API",
                "created_at": "2026-02-14T12:19:00Z",
                "author": {"name": "Display", "screen_name": "user"},
                "media": {"photos": [{"url": "https://example.com/photo.jpg"}]},
                "stats": {"likes": 12, "retweets": "1.5K", "views": "2M"},
            }
        },
        "https://x.com/user/status/1",
    )

    assert tweet is not None
    assert tweet.display_name == "Display"
    assert tweet.username == "user"
    assert tweet.text == "Hello from API"
    assert tweet.media[0].url == "https://example.com/photo.jpg"
    assert tweet.stats.likes == 12
    assert tweet.stats.reposts == 1500
    assert tweet.stats.views == 2_000_000
