import asyncio
from datetime import datetime
from types import SimpleNamespace

from src.services.database import Database
from src.services.media_cache import cache_tweet_media, remember_sent_rich_media
from src.twitter.models import MediaItem, Tweet


class CacheBot:
    def __init__(self):
        self.deleted: list[tuple[int, int]] = []

    async def send_photo(self, **kwargs):
        return SimpleNamespace(
            message_id=77,
            photo=[
                SimpleNamespace(
                    file_id="uploaded-photo-id",
                    file_unique_id="uploaded-photo-unique",
                    width=1200,
                    height=800,
                )
            ],
        )

    async def delete_message(self, chat_id: int, message_id: int):
        self.deleted.append((chat_id, message_id))


def test_inline_cache_only_reuses_existing_file_ids(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            video_url = "https://video.twimg.com/video.mp4"
            photo_url = "https://pbs.twimg.com/media/example.jpg"
            await database.upsert_cached_media(
                source_url=video_url,
                media_type="video",
                file_id="video-file-id",
                file_unique_id="video-unique-id",
                width=1080,
                height=1920,
                duration=74,
            )
            await database.upsert_cached_media(
                source_url=photo_url,
                media_type="photo",
                file_id="photo-file-id",
                file_unique_id="photo-unique-id",
                width=1200,
                height=800,
            )

            cached = await cache_tweet_media(
                None,
                database,
                [
                    MediaItem(type="video", url=video_url),
                    MediaItem(type="photo", url=photo_url),
                ],
            )

            assert [item.file_id for item in cached] == ["video-file-id", "photo-file-id"]
            assert await cache_tweet_media(
                None,
                database,
                [MediaItem(type="photo", url="https://pbs.twimg.com/media/missing.jpg")],
            ) == []
        finally:
            await database.close()

    asyncio.run(run())


def test_ordinary_rich_message_populates_inline_cache(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            media = [
                MediaItem(
                    type="video",
                    url="https://video.twimg.com/video.mp4",
                    width=1080,
                    height=1920,
                    duration=74,
                ),
                MediaItem(type="photo", url="https://pbs.twimg.com/media/one.jpg"),
                MediaItem(type="photo", url="https://pbs.twimg.com/media/two.jpg"),
            ]
            tweet = Tweet(
                display_name="Dropwire",
                username="dropwire",
                url="https://x.com/dropwire/status/1",
                text="Mixed media",
                date=datetime.now(),
                media=media,
            )
            rich_message = SimpleNamespace(
                blocks=[
                    SimpleNamespace(
                        blocks=[
                            SimpleNamespace(
                                video=SimpleNamespace(
                                    file_id="video-file-id",
                                    file_unique_id="video-unique-id",
                                    width=1080,
                                    height=1920,
                                    duration=74,
                                )
                            ),
                            SimpleNamespace(
                                photo=[
                                    SimpleNamespace(
                                        file_id="photo-one-small",
                                        file_unique_id="photo-one-small-unique",
                                        width=320,
                                        height=213,
                                    ),
                                    SimpleNamespace(
                                        file_id="photo-one-large",
                                        file_unique_id="photo-one-large-unique",
                                        width=1200,
                                        height=800,
                                    ),
                                ]
                            ),
                            SimpleNamespace(
                                photo=[
                                    SimpleNamespace(
                                        file_id="photo-two-large",
                                        file_unique_id="photo-two-large-unique",
                                        width=1200,
                                        height=800,
                                    )
                                ]
                            ),
                        ]
                    )
                ]
            )

            await remember_sent_rich_media(database, tweet, rich_message)

            cached = await cache_tweet_media(None, database, media)
            assert [item.file_id for item in cached] == [
                "video-file-id",
                "photo-one-large",
                "photo-two-large",
            ]
            assert cached[0].width == 1080
            assert cached[1].width == 1200
        finally:
            await database.close()

    asyncio.run(run())


def test_transient_cache_upload_is_deleted_after_file_id_is_saved(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        bot = CacheBot()
        try:
            await database.set_setting("global", 0, "inline_cache_chat_id", "-100123")
            url = "https://pbs.twimg.com/media/new-photo.jpg"
            cached = await cache_tweet_media(bot, database, [MediaItem(type="photo", url=url)])

            assert [item.file_id for item in cached] == ["uploaded-photo-id"]
            assert bot.deleted == [(-100123, 77)]
            row = await database.get_cached_media(url)
            assert row is not None
            assert row["file_id"] == "uploaded-photo-id"
        finally:
            await database.close()

    asyncio.run(run())
