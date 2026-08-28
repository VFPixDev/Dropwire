import asyncio
from datetime import datetime
from types import SimpleNamespace

from aiogram.types import (
    InlineQueryResultArticle,
    InlineQueryResultMpeg4Gif,
    InlineQueryResultPhoto,
    InlineQueryResultVideo,
    User,
)

from src.handlers.inline import (
    _build_result,
    _build_rich_twitter_result,
    _build_twitter_result,
    _prepend_sender_quote,
    _url_only_keyboard,
)
from src.models.media_card import Button, MediaCard
from src.providers.link_router import LinkMatch
from src.services.settings import EffectiveSettings
from src.services.database import Database
from src.twitter.models import MediaItem, QuotedTweet, Tweet


def _settings(**overrides) -> EffectiveSettings:
    values = {
        "reply_in_groups": True,
        "remove_message_in_groups": False,
        "reply_to_message": False,
        "caption_above_media": True,
        "enable_hashtags": True,
        "include_sender_quote": True,
        "sender_quote_mode": "username",
    }
    values.update(overrides)
    return EffectiveSettings(**values)


def test_inline_photo_has_article_fallback_and_url_only_buttons():
    link = LinkMatch("youtube", "https://youtu.be/dQw4w9WgXcQ", 0)
    card = MediaCard(
        source="youtube",
        media_type="video",
        original_url=link.url,
        title="Video",
        thumbnail_url="https://example.com/thumb.jpg",
        buttons=[
            Button("Open", url=link.url),
            Button("Download", callback_data="download:youtube:dQw4w9WgXcQ"),
        ],
    )
    keyboard = _url_only_keyboard(card)

    built = _build_result(link, "Video", "YouTube", "Card", card.thumbnail_url, keyboard, _settings())

    assert isinstance(built.primary, InlineQueryResultPhoto)
    assert isinstance(built.fallback, InlineQueryResultArticle)
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].url == link.url
    assert len(keyboard.inline_keyboard) == 1


def test_long_inline_caption_uses_article():
    link = LinkMatch("spotify", "https://open.spotify.com/track/abc", 0)
    built = _build_result(
        link,
        "Track",
        "Spotify",
        "x" * 1025,
        "https://example.com/cover.jpg",
        None,
        _settings(),
    )

    assert isinstance(built.primary, InlineQueryResultArticle)
    assert built.primary is built.fallback


def test_inline_sender_quote_uses_personal_mode_and_comment():
    user = User(id=123, first_name="Alice", is_bot=False, username="alice")

    text = _prepend_sender_quote("Card", user, "look", _settings())

    assert text == "<blockquote>@alice: look</blockquote>\n\nCard"


def test_twitter_inline_result_sends_direct_video():
    link = LinkMatch("twitter", "https://x.com/example/status/123", 0)
    tweet = Tweet(
        display_name="Example",
        username="example",
        url=link.url,
        text="Video post",
        date=datetime(2026, 7, 31),
        media=[
            MediaItem(
                type="video",
                url="https://video.twimg.com/ext_tw_video/123/playlist.m3u8",
                thumbnail_url="https://evil.example/preview.jpg",
            ),
            MediaItem(
                type="video",
                url=(
                    "https://api.fxtwitter.com/2/go?url="
                    "https%3A%2F%2Fvideo.twimg.com%2Famplify_video%2F123%2Fvid%2F720x1280%2Fclip.mp4"
                ),
                thumbnail_url="https://pbs.twimg.com/amplify_video_thumb/123/img/preview.jpg",
            )
        ],
    )

    built = _build_twitter_result(
        link,
        tweet,
        "Example (@example)",
        "Video post",
        "Video post",
        tweet.media[1].thumbnail_url,
        None,
        _settings(),
    )

    assert isinstance(built.primary, InlineQueryResultVideo)
    assert isinstance(built.fallback, InlineQueryResultArticle)
    assert built.primary.video_url == "https://video.twimg.com/amplify_video/123/vid/720x1280/clip.mp4"
    assert built.primary.mime_type == "video/mp4"


def test_twitter_inline_result_rejects_untrusted_video_url():
    link = LinkMatch("twitter", "https://x.com/example/status/123", 0)
    thumbnail = "https://pbs.twimg.com/amplify_video_thumb/123/img/preview.jpg"
    tweet = Tweet(
        display_name="Example",
        username="example",
        url=link.url,
        text="Video post",
        date=datetime(2026, 7, 31),
        media=[MediaItem(type="video", url="https://evil.example/video.mp4", thumbnail_url=thumbnail)],
    )

    built = _build_twitter_result(
        link,
        tweet,
        "Example (@example)",
        "Video post",
        "Video post",
        thumbnail,
        None,
        _settings(),
    )

    assert isinstance(built.primary, InlineQueryResultPhoto)
    assert isinstance(built.fallback, InlineQueryResultArticle)


def test_twitter_inline_animation_uses_native_mpeg4_gif_result():
    link = LinkMatch("twitter", "https://x.com/example/status/321", 0)
    thumbnail = "https://pbs.twimg.com/tweet_video_thumb/321/preview.jpg"
    tweet = Tweet(
        display_name="Example",
        username="example",
        url=link.url,
        text="GIF post",
        date=datetime(2026, 8, 27),
        media=[
            MediaItem(
                type="animation",
                url="https://video.twimg.com/tweet_video/clip.mp4",
                thumbnail_url=thumbnail,
                width=640,
                height=360,
                duration=4,
            )
        ],
    )

    built = _build_twitter_result(
        link, tweet, "Example (@example)", "GIF post", "GIF post", thumbnail, None, _settings()
    )

    assert isinstance(built.primary, InlineQueryResultMpeg4Gif)
    assert built.primary.mpeg4_width == 640
    assert built.primary.mpeg4_height == 360


def test_rich_inline_collage_supports_quote_media_without_outer_media(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            urls = [
                "https://pbs.twimg.com/media/quote-one.jpg",
                "https://pbs.twimg.com/media/quote-two.jpg",
            ]
            for index, url in enumerate(urls):
                await database.upsert_cached_media(url, "photo", f"file-{index}", width=1200, height=800)

            link = LinkMatch("twitter", "https://x.com/outer/status/11", 0)
            tweet = Tweet(
                display_name="Outer",
                username="outer",
                url=link.url,
                text="Reply",
                date=datetime(2026, 8, 27),
                quoted_tweet=QuotedTweet(
                    display_name="Quoted",
                    username="quoted",
                    url="https://x.com/quoted/status/10",
                    text="Original",
                    media=[MediaItem(type="photo", url=url) for url in urls],
                ),
            )
            update = SimpleNamespace(get_bot=lambda: None)
            built = await _build_rich_twitter_result(
                update,
                database,
                link,
                tweet,
                "Outer (@outer)",
                "Reply",
                "Text above media",
                urls[0],
                None,
                _settings(),
            )

            assert built is not None
            rich = built.primary.input_message_content.rich_message
            assert rich.blocks is None
            assert '<blockquote><p>Quoted (' in rich.html
            assert '<tg-collage><img src="tg://photo?id=m0"/><img src="tg://photo?id=m1"/></tg-collage>' in rich.html
            assert [attachment.media.media for attachment in rich.media] == ["file-0", "file-1"]
        finally:
            await database.close()

    asyncio.run(run())


def test_rich_inline_collage_combines_cached_video_and_photos(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            video_url = "https://video.twimg.com/amplify_video/example/vid/avc1/1080x1920/video.mp4"
            photo_urls = [
                "https://pbs.twimg.com/media/one.jpg?name=orig",
                "https://pbs.twimg.com/media/two.jpg?name=orig",
            ]
            await database.upsert_cached_media(
                video_url, "video", "video-file", width=1080, height=1920, duration=74
            )
            for index, url in enumerate(photo_urls):
                await database.upsert_cached_media(url, "photo", f"photo-file-{index}", width=1206, height=882)

            link = LinkMatch("twitter", "https://x.com/mixed/status/3", 0)
            tweet = Tweet(
                display_name="Mixed",
                username="mixed",
                url=link.url,
                text="Video and two photos",
                date=datetime(2026, 8, 27, 7, 47),
                media=[
                    MediaItem(type="video", url=video_url, width=1080, height=1920, duration=74),
                    *(MediaItem(type="photo", url=url, width=1206, height=882) for url in photo_urls),
                ],
            )
            built = await _build_rich_twitter_result(
                SimpleNamespace(get_bot=lambda: None),
                database,
                link,
                tweet,
                "Mixed (@mixed)",
                "Video and two photos",
                "Video and two photos",
                photo_urls[0],
                None,
                _settings(),
            )

            assert built is not None
            rich = built.primary.input_message_content.rich_message
            assert rich.blocks is None
            assert (
                '<tg-collage><video src="tg://video?id=m0"></video>'
                '<img src="tg://photo?id=m1"/><img src="tg://photo?id=m2"/></tg-collage>'
            ) in rich.html
            assert [attachment.media.media for attachment in rich.media] == [
                "video-file",
                "photo-file-0",
                "photo-file-1",
            ]
        finally:
            await database.close()

    asyncio.run(run())
