"""Live validation of a mixed-media Telegram Rich Message."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import config
from src.rendering.twitter_rich import build_twitter_rich_message
from src.services.database import Database
from src.services.media_cache import cache_tweet_media, remember_sent_rich_media
from src.twitter.loader import fetch_complete_tweet


def _count_media_blocks(blocks) -> int:
    count = 0
    for block in blocks or []:
        if any(getattr(block, field, None) is not None for field in ("photo", "video", "animation")):
            count += 1
        count += _count_media_blocks(getattr(block, "blocks", None))
    return count


async def main() -> int:
    bot = Bot(config.BOT_TOKEN)
    try:
        if not config.BOT_ADMIN_IDS:
            print("rich: skipped (BOT_ADMIN_IDS is empty)")
            return 0
        chat_id = config.BOT_ADMIN_IDS[0]
        url = "https://x.com/ogivus/status/2092881563969007632"
        tweet = await fetch_complete_tweet(url, "2092881563969007632", "ogivus", "ru")
        if tweet is None:
            print("rich: failed (tweet fetch failed)")
            return 1
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Open original", url=url)]]
        )
        built = await build_twitter_rich_message(bot, None, tweet)
        if built is None:
            print("rich: failed (media preparation failed)")
            return 1
        sent = await bot.send_rich_message(
            chat_id=chat_id,
            rich_message=built.message,
            reply_markup=keyboard,
        )
        try:
            requested_media = _count_media_blocks(built.message.blocks)
            returned_media = _count_media_blocks(sent.rich_message.blocks)
            with TemporaryDirectory() as temp_dir:
                database = Database(str(Path(temp_dir) / "smoke.sqlite3"))
                await database.connect()
                try:
                    await database.init_schema()
                    await remember_sent_rich_media(database, tweet, sent.rich_message)
                    cached = await cache_tweet_media(database, tweet.media)
                finally:
                    await database.close()
        finally:
            await bot.delete_message(chat_id=chat_id, message_id=sent.message_id)
        print(f"rich: ok (requested={requested_media}, returned={returned_media}, cached={len(cached)})")
        return 0 if requested_media == returned_media == len(cached) == 3 else 1
    finally:
        await bot.session.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
