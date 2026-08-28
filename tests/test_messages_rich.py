import asyncio
from datetime import datetime
from types import SimpleNamespace

from aiogram.types import (
    BufferedInputFile,
    InputRichBlockBlockQuotation,
    InputRichBlockCollage,
    InputRichBlockDivider,
    InputRichBlockFooter,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockVideo,
)

from src.handlers.messages import _try_send_rich_tweet_card
from src.rendering.twitter_rich import build_twitter_rich_message
from src.services.database import Database
from src.services.settings import EffectiveSettings
from src.twitter.models import MediaItem, QuotedTweet, Tweet


class RichBot:
    def __init__(self):
        self.calls = []

    async def send_rich_message(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message_id=99)


def _plain_rich_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_plain_rich_text(item) for item in value)
    return _plain_rich_text(getattr(value, "text", ""))


def test_group_twitter_collage_is_one_rich_message_with_button_and_delivery(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            urls = [
                "https://pbs.twimg.com/media/one.jpg",
                "https://pbs.twimg.com/media/two.jpg",
            ]
            for index, url in enumerate(urls):
                await database.upsert_cached_media(url, "photo", f"file-{index}", width=1200, height=800)

            tweet = Tweet(
                display_name="Example",
                username="example",
                url="https://x.com/example/status/1",
                text="Post",
                date=datetime(2026, 8, 27),
                media=[MediaItem(type="photo", url=url) for url in urls],
            )
            bot = RichBot()
            update = SimpleNamespace(
                effective_chat=SimpleNamespace(id=-100, type="supergroup"),
                effective_user=SimpleNamespace(id=42),
                message=SimpleNamespace(message_id=7),
            )
            context = SimpleNamespace(
                bot=bot,
                application=SimpleNamespace(bot_data={"database": database}),
            )
            settings = EffectiveSettings(
                reply_in_groups=True,
                remove_message_in_groups=False,
                reply_to_message=True,
                caption_above_media=True,
                enable_hashtags=False,
                include_sender_quote=False,
                sender_quote_mode="name",
            )

            sent = await _try_send_rich_tweet_card(update, context, tweet, None, settings, None, "")

            assert sent.message_id == 99
            assert len(bot.calls) == 1
            call = bot.calls[0]
            assert call["chat_id"] == -100
            blocks = call["rich_message"].blocks
            assert isinstance(blocks[0], InputRichBlockParagraph)
            assert _plain_rich_text(blocks[0].text).startswith("Example (@example)")
            assert isinstance(blocks[2], InputRichBlockCollage)
            assert [block.photo.media for block in blocks[2].blocks] == ["file-0", "file-1"]
            assert call["rich_message"].media is None
            assert call["reply_parameters"].message_id == 7
            assert call["reply_markup"].inline_keyboard[0][0].url == tweet.url
            delivery = await database.get_delivery_for_message(-100, 99)
            assert delivery is not None
            assert delivery["requester_user_id"] == 42
        finally:
            await database.close()

    asyncio.run(run())


def test_rich_layout_nests_translated_reference_media_and_combines_footer():
    async def run():
        parent_url = "https://pbs.twimg.com/media/parent.jpg"
        tweet = Tweet(
            display_name="Outer",
            username="outer",
            url="https://x.com/outer/status/2",
            text="Original outer",
            translated_text="Переведённый внешний твит",
            source_language="English",
            date=datetime(2026, 8, 27, 12, 30),
            parent_tweet=QuotedTweet(
                display_name="Parent",
                username="parent",
                url="https://x.com/parent/status/1",
                text="Original parent",
                translated_text="Переведённый исходный твит",
                source_language="English",
                date=datetime(2026, 8, 26, 11, 0),
                media=[MediaItem(type="photo", url=parent_url)],
            ),
        )

        built = await build_twitter_rich_message(
            None,
            None,
            tweet,
            sender_quote="<blockquote>Отправитель: комментарий</blockquote>",
            hashtags="#twitter #post #outer",
        )

        assert built is not None
        blocks = built.message.blocks
        assert isinstance(blocks[0], InputRichBlockBlockQuotation)
        assert _plain_rich_text(blocks[0].blocks[0].text) == "Отправитель: комментарий"
        assert isinstance(blocks[1], InputRichBlockDivider)
        assert _plain_rich_text(blocks[3].text) == "Переведённый внешний твит"
        assert isinstance(blocks[4], InputRichBlockBlockQuotation)
        assert _plain_rich_text(blocks[4].blocks[1].text) == "Переведённый исходный твит"
        assert isinstance(blocks[4].blocks[2], InputRichBlockPhoto)
        assert blocks[4].blocks[2].photo.media == parent_url
        assert isinstance(blocks[5], InputRichBlockDivider)
        assert isinstance(blocks[7], InputRichBlockFooter)
        assert _plain_rich_text(blocks[7].text) == "#twitter #post #outer | Переведено с английского"
        assert built.cache_urls == ()

    asyncio.run(run())


def test_rich_layout_combines_original_video_bytes_and_photos(monkeypatch):
    original_video = b"original-video-bytes"

    async def fake_download(url, max_bytes):
        assert url.endswith("/video.mp4")
        assert max_bytes == 50 * 1024 * 1024
        return original_video

    monkeypatch.setattr("src.rendering.twitter_rich.download_media", fake_download)

    async def run():
        video_url = "https://video.twimg.com/amplify_video/example/vid/avc1/1080x1920/video.mp4"
        photo_urls = [
            "https://pbs.twimg.com/media/one.jpg?name=orig",
            "https://pbs.twimg.com/media/two.jpg?name=orig",
        ]
        tweet = Tweet(
            display_name="Mixed media",
            username="mixed",
            url="https://x.com/mixed/status/3",
            text="Video and two photos",
            date=datetime(2026, 8, 27, 7, 47),
            media=[
                MediaItem(type="video", url=video_url, width=1080, height=1920, duration=74),
                *(MediaItem(type="photo", url=url, width=1206, height=882) for url in photo_urls),
            ],
        )

        built = await build_twitter_rich_message(None, None, tweet)

        assert built is not None
        collage = built.message.blocks[2]
        assert isinstance(collage, InputRichBlockCollage)
        assert [type(block) for block in collage.blocks] == [
            InputRichBlockVideo,
            InputRichBlockPhoto,
            InputRichBlockPhoto,
        ]
        video = collage.blocks[0].video.media
        assert isinstance(video, BufferedInputFile)
        assert video.data == original_video
        assert [block.photo.media for block in collage.blocks[1:]] == photo_urls

    asyncio.run(run())
