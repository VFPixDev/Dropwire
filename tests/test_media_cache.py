import asyncio
from types import SimpleNamespace

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
