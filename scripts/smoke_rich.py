"""Live validation of the configured Telegram Rich Message media cache."""

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

TEST_IMAGE = "https://pbs.fxtwitter.com/media/HNQNOONaAAAD8zn.jpg"


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
        raw_chat_id = await database.get_setting("global", 0, "inline_cache_chat_id")
        if not raw_chat_id:
            print("rich: skipped (inline media cache is not configured)")
            return 0
        chat_id = int(raw_chat_id)
        link = LinkMatch("twitter", "https://x.com/Dropwire/status/1", 0)
        tweet = Tweet(
            display_name="Dropwire smoke",
            username="Dropwire",
            url=link.url,
            text="Rich Message validation",
            date=datetime.now(),
            media=[
                MediaItem(type="photo", url=f"{TEST_IMAGE}?name=orig"),
                MediaItem(type="photo", url=f"{TEST_IMAGE}?name=large"),
            ],
        )
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Open original", url=link.url)]]
        )
        built = await _build_rich_twitter_result(
            Update(update_id=0, bot=bot),
            database,
            link,
            tweet,
            "Dropwire Rich Message",
            "Live collage validation",
            "Text above media",
            tweet.media[0].url,
            keyboard,
            _settings(),
        )
        if built is None:
            print("rich: failed (media could not be cached)")
            return 1
        rich_message = built.primary.input_message_content.rich_message
        sent = await raw_bot.send_rich_message(chat_id=chat_id, rich_message=rich_message, reply_markup=keyboard)
        await raw_bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
        print(f"rich: ok (attachments={len(rich_message.media or [])})")
        return 0
    finally:
        await database.close()
        await raw_bot.session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
