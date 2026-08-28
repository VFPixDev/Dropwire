import asyncio
from types import SimpleNamespace

from aiogram.types import User

from scripts.smoke_providers import SOUNDCLOUD_URL, SPOTIFY_URL, TWITTER_URL, YOUTUBE_URL
from src.handlers.inline import _build_inline_result
from src.providers.link_router import find_supported_links
from src.services.settings import EffectiveSettings
from src.telegram_runtime import Update


def _settings() -> EffectiveSettings:
    return EffectiveSettings(
        reply_in_groups=True,
        remove_message_in_groups=False,
        reply_to_message=False,
        caption_above_media=True,
        enable_hashtags=True,
        include_sender_quote=True,
        sender_quote_mode="name",
    )


async def main() -> int:
    user = User(id=1, first_name="Inline Smoke", is_bot=False, username="inline_smoke")
    failures = 0
    for index, url in enumerate((TWITTER_URL, YOUTUBE_URL, SPOTIFY_URL, SOUNDCLOUD_URL), start=1):
        link = find_supported_links(url)[0]
        update = Update(update_id=index, bot=SimpleNamespace())
        try:
            result = await _build_inline_result(update, None, link, _settings(), user, None)
            if result is None:
                raise RuntimeError("empty inline result")
            result.primary.model_dump(exclude_none=True)
            result.fallback.model_dump(exclude_none=True)
            print(f"inline {link.source}: ok ({type(result.primary).__name__})")
        except Exception as exc:
            failures += 1
            print(f"inline {link.source}: failed ({type(exc).__name__})")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
