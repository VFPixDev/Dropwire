import asyncio
from datetime import datetime
from types import SimpleNamespace

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
            assert call["rich_message"].html.startswith('<p>Example (<a href="https://x.com/example">@example</a>)')
            assert "<tg-collage>" in call["rich_message"].html
            assert [item.media.media for item in call["rich_message"].media] == urls
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
        html = built.message.html
        assert html.startswith("<blockquote>Отправитель: комментарий</blockquote><hr/>")
        assert "Переведённый внешний твит" in html
        assert "Original outer" not in html
        reference_start = html.index("<blockquote>", html.index("<hr/>") + 1)
        media_start = html.index('tg://photo?id=m0')
        reference_end = html.index("</blockquote>", reference_start)
        assert reference_start < media_start < reference_end
        assert "Переведённый исходный твит" in html
        assert "Original parent" not in html
        assert html.count("<hr/>") == 2
        assert "#twitter #post #outer | <i>Переведено с английского</i>" in html
        assert built.message.media[0].media.media == parent_url
        assert built.cache_urls == ()

    asyncio.run(run())
