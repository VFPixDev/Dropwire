import asyncio
import os

import httpx

from src.providers.soundcloud import fetch_soundcloud_card
from src.providers.spotify import fetch_spotify_card
from src.providers.youtube import fetch_youtube_card
from src.twitter.fetcher import fetch_tweet_data, fetch_tweet_html
from src.twitter.parser import parse_tweet_html
from src.twitter.parser_api import parse_tweet_api

TWITTER_URL = "https://x.com/Magicpika1/status/2077299922492395991"
YOUTUBE_URL = "https://youtu.be/dQw4w9WgXcQ"
SPOTIFY_URL = "https://open.spotify.com/track/11dFghVXANMlKmJXsNCbNl"
SOUNDCLOUD_URL = "https://soundcloud.com/forss/flickermood"


async def _check_telegram() -> bool:
    token = os.getenv("BOT_TOKEN", "")
    if not token:
        print("telegram: skipped (BOT_TOKEN is not configured)")
        return True

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(f"https://api.telegram.org/bot{token}/getMe")
    payload = response.json() if response.is_success else {}
    result = payload.get("result") if isinstance(payload, dict) else None
    username = result.get("username", "") if isinstance(result, dict) else ""
    inline_enabled = bool(result.get("supports_inline_queries")) if isinstance(result, dict) else False
    ok = response.is_success and payload.get("ok") is True
    inline_state = "inline=on" if inline_enabled else "inline=off"
    print(f"telegram: {'ok' if ok else 'failed'} {username} ({inline_state})".rstrip())
    return ok


async def _check_card(name: str, fetcher, url: str) -> bool:
    try:
        card = await fetcher(url)
    except Exception as exc:
        print(f"{name}: failed ({type(exc).__name__})")
        return False
    ok = bool(card.title and card.original_url and card.buttons)
    print(f"{name}: {'ok' if ok else 'incomplete'}")
    return ok


async def _check_twitter() -> bool:
    tweet_id = "2077299922492395991"
    username = "Magicpika1"
    data = await fetch_tweet_data(tweet_id, username)
    tweet = parse_tweet_api(data, TWITTER_URL) if data else None
    if tweet is None:
        html = await fetch_tweet_html(tweet_id, username)
        tweet = parse_tweet_html(html, TWITTER_URL) if html else None
    ok = tweet is not None and bool(tweet.text and tweet.username)
    print(f"twitter: {'ok' if ok else 'failed'}")
    return ok


async def main() -> int:
    checks = await asyncio.gather(
        _check_telegram(),
        _check_twitter(),
        _check_card("youtube", fetch_youtube_card, YOUTUBE_URL),
        _check_card("spotify", fetch_spotify_card, SPOTIFY_URL),
        _check_card("soundcloud", fetch_soundcloud_card, SOUNDCLOUD_URL),
    )
    return 0 if all(checks) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
