import asyncio
from datetime import datetime
from types import SimpleNamespace

from src.handlers.messages import _try_send_rich_tweet_card
from src.services.database import Database
from src.services.settings import EffectiveSettings
from src.twitter.models import MediaItem, Tweet


class RichBot:
    def __init__(self):
        self.calls = []

    async def send_rich_message(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message_id=99)


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
            await database.set_setting("global", 0, "inline_cache_chat_id", "-1004458765190")
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

            sent = await _try_send_rich_tweet_card(update, context, tweet, "Text above media", None, settings)

            assert sent.message_id == 99
            assert len(bot.calls) == 1
            call = bot.calls[0]
            assert call["chat_id"] == -100
            assert call["rich_message"].html.startswith("Text above media")
            assert "<tg-collage>" in call["rich_message"].html
            assert call["reply_parameters"].message_id == 7
            assert call["reply_markup"].inline_keyboard[0][0].url == tweet.url
            delivery = await database.get_delivery_for_message(-100, 99)
            assert delivery is not None
            assert delivery["requester_user_id"] == 42
        finally:
            await database.close()

    asyncio.run(run())
