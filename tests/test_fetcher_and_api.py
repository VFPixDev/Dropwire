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
    get_trusted_twitter_mp4_url,
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


def test_trusted_twitter_mp4_url_unwraps_only_direct_mp4_targets():
    wrapped = (
        "https://api.fxtwitter.com/2/go?url="
        "https%3A%2F%2Fvideo.twimg.com%2Famplify_video%2F123%2Fvid%2F720x1280%2Fclip.mp4%3Ftag%3D12"
    )

    assert (
        get_trusted_twitter_mp4_url(wrapped)
        == "https://video.twimg.com/amplify_video/123/vid/720x1280/clip.mp4?tag=12"
    )
    assert get_trusted_twitter_mp4_url("https://video.twimg.com/video.m3u8") is None
    assert get_trusted_twitter_mp4_url("https://video.twimg.com.evil.example/video.mp4") is None


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


def test_parse_tweet_api_accepts_media_only_gif_and_dimensions():
    tweet = parse_tweet_api(
        {
            "tweet": {
                "text": "",
                "author": {"name": "Loop", "screen_name": "loop"},
                "media": {
                    "all": [
                        {
                            "type": "animated_gif",
                            "url": "https://video.twimg.com/tweet_video/loop.mp4",
                            "width": 640,
                            "height": 360,
                            "duration_millis": 4200,
                        }
                    ]
                },
            }
        },
        "https://x.com/loop/status/2",
    )

    assert tweet is not None
    assert tweet.text == ""
    assert tweet.media[0].type == "animation"
    assert tweet.media[0].width == 640
    assert tweet.media[0].height == 360
    assert tweet.media[0].duration == 4


def test_parse_tweet_api_extracts_quote_media_and_parent():
    tweet = parse_tweet_api(
        {
            "tweet": {
                "text": "Reply with quote",
                "author": {"name": "Outer", "screen_name": "outer"},
                "quote": {
                    "id": "10",
                    "text": "Quoted",
                    "author": {"name": "Quoted author", "screen_name": "quoted"},
                    "media": {
                        "photos": [
                            {"url": "https://pbs.twimg.com/media/one.jpg"},
                            {"url": "https://pbs.twimg.com/media/two.jpg"},
                        ]
                    },
                },
                "parent_tweet": {
                    "id": "9",
                    "text": "Parent",
                    "author": {"name": "Parent author", "screen_name": "parent"},
                },
            }
        },
        "https://x.com/outer/status/11",
    )

    assert tweet is not None
    assert tweet.quoted_tweet is not None
    assert [item.url for item in tweet.quoted_tweet.media] == [
        "https://pbs.twimg.com/media/one.jpg",
        "https://pbs.twimg.com/media/two.jpg",
    ]
    assert tweet.parent_tweet is not None
    assert tweet.parent_tweet.username == "parent"


def test_parse_tweet_api_v2_thread_uses_original_photos_and_parent_status():
    tweet = parse_tweet_api(
        {
            "status": {
                "id": "11",
                "text": "Reply",
                "author": {"name": "Outer", "screen_name": "outer"},
                "replying_to": {
                    "screen_name": "parent",
                    "display_name": "Parent author",
                    "status": "10",
                    "url": "https://x.com/parent/status/10",
                },
                "media": {
                    "all": [{"type": "mosaic_photo", "url": "https://mosaic.fxtwitter.com/11/a/b"}],
                    "photos": [
                        {"type": "photo", "url": "https://pbs.twimg.com/media/one.jpg"},
                        {"type": "photo", "url": "https://pbs.twimg.com/media/two.jpg"},
                    ],
                },
                "translation": {"text": "Ответ", "source_lang_en": "English"},
            },
            "thread": [
                {
                    "id": "10",
                    "text": "Parent text",
                    "author": {"name": "Parent author", "screen_name": "parent"},
                    "media": {"photos": [{"url": "https://pbs.twimg.com/media/parent.jpg"}]},
                }
            ],
        },
        "https://x.com/outer/status/11",
    )

    assert tweet is not None
    assert [item.url for item in tweet.media] == [
        "https://pbs.twimg.com/media/one.jpg",
        "https://pbs.twimg.com/media/two.jpg",
    ]
    assert tweet.parent_tweet is not None
    assert tweet.parent_tweet.text == "Parent text"
    assert tweet.parent_tweet.media[0].url == "https://pbs.twimg.com/media/parent.jpg"
    assert tweet.translated_text == "Ответ"
    assert tweet.source_language == "English"
