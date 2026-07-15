from src.config import config
from src.services.database import Database
from src.services.settings import GLOBAL_OWNER_ID, db_to_bool

PROVIDERS = {
    "twitter": "Twitter/X",
    "youtube": "YouTube",
    "spotify": "Spotify",
    "soundcloud": "SoundCloud",
}


async def is_provider_enabled(database: Database | None, source: str) -> bool:
    _validate_provider(source)
    if database is None:
        return True
    value = await database.get_setting("global", GLOBAL_OWNER_ID, _setting_name(source))
    return db_to_bool(value, True)


async def toggle_provider(database: Database, source: str) -> bool:
    enabled = not await is_provider_enabled(database, source)
    await database.set_setting("global", GLOBAL_OWNER_ID, _setting_name(source), "1" if enabled else "0")
    return enabled


def provider_capability(source: str) -> str:
    _validate_provider(source)
    if source == "youtube":
        return (
            "карточки + загрузка"
            if config.YOUTUBE_API_KEY and config.WEB_BASE_URL
            else ("только карточки" if config.YOUTUBE_API_KEY else "нет YOUTUBE_API_KEY")
        )
    if source == "spotify":
        if config.SPOTIFY_CLIENT_ID and config.SPOTIFY_CLIENT_SECRET:
            return "расширенные метаданные"
        return "базовые метаданные"
    return "готов"


def _setting_name(source: str) -> str:
    return f"provider_enabled_{source}"


def _validate_provider(source: str) -> None:
    if source not in PROVIDERS:
        raise ValueError(f"Unknown provider: {source}")
