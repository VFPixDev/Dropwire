"""Live validation of Telegram Rich Messages without a cache channel."""

import asyncio
from datetime import datetime

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import config
from src.handlers.inline import _build_rich_twitter_result
from src.providers.link_router import LinkMatch
from src.services.database import Database
from src.services.settings import EffectiveSettings
from src.telegram_runtime import BotAdapter, Update
from src.twitter.models import MediaItem, Tweet

TEST_MEDIA = [
    MediaItem(
        type="video",
        url="https://video.twimg.com/amplify_video/2092881459765772288/vid/avc1/1080x1920/X4QGDads6kz9Rejj.mp4?tag=29",
        width=1080,
        height=1920,
        duration=74,
    ),
    MediaItem(type="photo", url="https://pbs.twimg.com/media/HQtomVVWUAAZWWx.jpg?name=orig"),
    MediaItem(type="photo", url="https://pbs.twimg.com/media/HQtomWNWAAA6GNO.jpg?name=orig"),
]


def _settings() -> EffectiveSettings:
    return EffectiveSettings(
        reply_in_groups=True,
        remove_message_in_groups=False,
        reply_to_message=False,
        caption_above_media=True,
        enable_hashtags=True,
        include_sender_quote=False,
        sender_quote_mode="name",
    )


async def main() -> int:
    raw_bot = Bot(config.BOT_TOKEN)
    bot = BotAdapter(raw_bot)
    database = Database(config.DATABASE_PATH)
    await database.connect()
    try:
        await database.init_schema()
        if not config.BOT_ADMIN_IDS:
            print("rich: skipped (BOT_ADMIN_IDS is empty)")
            return 0
        chat_id = config.BOT_ADMIN_IDS[0]
        link = LinkMatch("twitter", "https://x.com/Dropwire/status/1", 0)
        tweet = Tweet(
            display_name="Dropwire smoke",
            username="Dropwire",
            url=link.url,
            text="Mixed video and photo Rich Message validation",
            date=datetime.now(),
            media=TEST_MEDIA,
        )
        await database.delete_cached_media([item.url for item in tweet.media])
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Open original", url=link.url)]]
        )
        built = await _build_rich_twitter_result(
            Update(update_id=0, bot=bot),
            database,
            link,
            tweet,
            "Dropwire Rich Message",
            "Live mixed-media validation",
            "Text above media",
            tweet.media[0].url,
            keyboard,
            _settings(),
            staging_chat_id=chat_id,
        )
        if built is None:
            print("rich: failed (DM staging or Rich media preparation failed)")
            return 1
        rich_message = built.primary.input_message_content.rich_message
        sent = await raw_bot.send_rich_message(chat_id=chat_id, rich_message=rich_message, reply_markup=keyboard)
        await raw_bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
        attachments = len(rich_message.media or [])
        print(f"rich: ok (attachments={attachments})")
        return 0 if attachments == 3 else 1
    finally:
        await database.close()
        await raw_bot.session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
