import asyncio
from types import SimpleNamespace

from aiogram.types import BufferedInputFile

from src.services.database import Database
from src.services.media_cache import cache_tweet_media
from src.twitter.models import MediaItem


class CacheBot:
    def __init__(self):
        self.sent = []
        self.deleted = []

    async def send_photo(self, **kwargs):
        self.sent.append(kwargs)
        photo = SimpleNamespace(
            file_id="file-id",
            file_unique_id="unique-id",
            width=1200,
            height=800,
        )
        return SimpleNamespace(message_id=77, photo=[photo])

    async def send_video(self, **kwargs):
        self.sent.append(kwargs)
        video = SimpleNamespace(
            file_id="video-file-id",
            file_unique_id="video-unique-id",
            width=1080,
            height=1920,
            duration=74,
        )
        return SimpleNamespace(message_id=78, video=video)

    async def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


def test_inline_cache_upload_is_deleted_immediately(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            bot = CacheBot()
            url = "https://pbs.twimg.com/media/example.jpg"

            cached = await cache_tweet_media(
                bot,
                database,
                [MediaItem(type="photo", url=url)],
                staging_chat_id=42,
            )

            assert cached[0].file_id == "file-id"
            assert bot.sent == [
                {
                    "chat_id": 42,
                    "photo": url,
                    "disable_notification": True,
                    "protect_content": True,
                }
            ]
            assert bot.deleted == [{"chat_id": 42, "message_id": 77}]
            assert (await database.get_cached_media(url))["file_id"] == "file-id"

            second = await cache_tweet_media(bot, database, [MediaItem(type="photo", url=url)])

            assert second[0].file_id == "file-id"
            assert len(bot.sent) == 1
        finally:
            await database.close()

    asyncio.run(run())


def test_inline_video_staging_uploads_original_bytes(monkeypatch, tmp_path):
    original = b"original-video-bytes"

    async def fake_download(url, max_bytes):
        assert url == "https://video.twimg.com/video.mp4"
        assert max_bytes == 50 * 1024 * 1024
        return original

    monkeypatch.setattr("src.services.media_cache.download_media", fake_download)

    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            bot = CacheBot()
            item = MediaItem(
                type="video",
                url="https://video.twimg.com/video.mp4",
                width=1080,
                height=1920,
                duration=74,
            )

            cached = await cache_tweet_media(bot, database, [item], staging_chat_id=42)

            assert cached[0].file_id == "video-file-id"
            upload = bot.sent[0]["video"]
            assert isinstance(upload, BufferedInputFile)
            assert upload.data == original
            assert bot.deleted == [{"chat_id": 42, "message_id": 78}]
        finally:
            await database.close()

    asyncio.run(run())
