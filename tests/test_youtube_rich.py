import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from aiogram.types import (
    InputRichBlockFooter,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    RichTextBold,
    RichTextUrl,
)

from src.handlers.messages import _try_send_rich_youtube_card
from src.models.media_card import Button, CardStats, MediaCard
from src.rendering.youtube_rich import build_youtube_rich_message, format_youtube_metadata
from src.services.database import Database
from src.services.settings import EffectiveSettings


THUMBNAIL = "https://i.ytimg.com/vi/example/maxresdefault.jpg"


class RichBot:
    def __init__(self):
        self.calls = []

    async def send_rich_message(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(message_id=101)


def _card() -> MediaCard:
    return MediaCard(
        source="youtube",
        media_type="video",
        original_url="https://youtu.be/example",
        title="Hypernet Explorer - Early access trailer",
        author_name="Nocoldiz",
        author_handle="@nocoldiz",
        author_url="https://www.youtube.com/@nocoldiz",
        published_at=datetime(2026, 7, 1, 12, tzinfo=timezone.utc),
        thumbnail_url=THUMBNAIL,
        duration_text="3:26",
        stats=CardStats(views=37_000),
        buttons=[
            Button(text="Смотреть", url="https://youtu.be/example"),
            Button(text="Скачать", callback_data="download:youtube:example"),
        ],
        hashtags=["#youtube", "#video", "#nocoldiz"],
    )


def test_youtube_metadata_matches_compact_native_style():
    assert format_youtube_metadata(_card()) == "37 тыс. просмотров · 01.07.2026 · 3:26"


def test_youtube_rich_message_uses_cover_title_channel_and_metadata():
    built = asyncio.run(build_youtube_rich_message(None, None, _card(), hashtags="#youtube #video #nocoldiz"))

    assert built is not None
    blocks = built.message.blocks
    assert isinstance(blocks[0], InputRichBlockPhoto)
    assert blocks[0].photo.media == THUMBNAIL
    assert isinstance(blocks[1], InputRichBlockParagraph)
    assert isinstance(blocks[1].text, RichTextBold)
    assert blocks[1].text.text == "Hypernet Explorer - Early access trailer"
    assert isinstance(blocks[2].text, RichTextUrl)
    assert blocks[2].text.url == "https://www.youtube.com/@nocoldiz"
    assert isinstance(blocks[3], InputRichBlockFooter)
    assert blocks[3].text.endswith("3:26")
    assert blocks[4].text == "#youtube #video #nocoldiz"


def test_youtube_inline_rich_message_reuses_cached_thumbnail(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.upsert_cached_media(THUMBNAIL, "photo", "cached-cover")
            built = await build_youtube_rich_message(None, database, _card(), inline=True)

            assert built is not None
            assert built.cache_urls == (THUMBNAIL,)
            assert built.message.html.startswith('<img src="tg://photo?id=cover"/>')
            assert len(built.message.media) == 1
            assert built.message.media[0].media.media == "cached-cover"
        finally:
            await database.close()

    asyncio.run(run())


def test_youtube_handler_sends_one_rich_message_with_existing_buttons(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
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
                enable_hashtags=True,
                include_sender_quote=False,
                sender_quote_mode="name",
            )

            sent = await _try_send_rich_youtube_card(update, context, _card(), None, settings, None)

            assert sent.message_id == 101
            assert len(bot.calls) == 1
            call = bot.calls[0]
            assert call["reply_parameters"].message_id == 7
            assert len(call["reply_markup"].inline_keyboard) == 1
            assert len(call["reply_markup"].inline_keyboard[0]) == 2
            delivery = await database.get_delivery_for_message(-100, 101)
            assert delivery is not None
            assert delivery["requester_user_id"] == 42
        finally:
            await database.close()

    asyncio.run(run())
