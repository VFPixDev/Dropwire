import logging
import os
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ALLOWED_FX_HOSTS = {
    "fxtwitter.com",
    "fixupx.com",
    "vxtwitter.com",
}


def _parse_bool(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _parse_int(name: str, default: int, min_value: int | None = None) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть целым числом") from exc
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} должен быть >= {min_value}")
    return value


def _parse_float(name: str, default: float, min_value: float | None = None) -> float:
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} должен быть числом") from exc
    if min_value is not None and value < min_value:
        raise ValueError(f"{name} должен быть >= {min_value}")
    return value


def _parse_user_ids(name: str) -> Optional[list[int]]:
    user_ids_str = os.getenv(name, "")
    if not user_ids_str:
        return None
    try:
        return [int(uid.strip()) for uid in user_ids_str.split(",") if uid.strip()]
    except ValueError as exc:
        raise ValueError(f"{name} должен быть списком числовых ID через запятую") from exc


def _parse_retry_status_codes() -> list[int]:
    retry_status_codes_str = os.getenv("RETRY_STATUS_CODES", "408,429")
    retry_status_codes: list[int] = []
    for part in retry_status_codes_str.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            retry_status_codes.append(int(part))
        except ValueError as exc:
            raise ValueError("RETRY_STATUS_CODES должен быть списком HTTP-кодов через запятую") from exc
    return retry_status_codes


def _parse_fx_base_url() -> str:
    raw_url = os.getenv("FX_BASE_URL", "https://fxtwitter.com").rstrip("/")
    parsed = urlparse(raw_url)
    if parsed.scheme != "https":
        raise ValueError("FX_BASE_URL должен использовать https")
    if parsed.netloc not in ALLOWED_FX_HOSTS:
        allowed = ", ".join(sorted(ALLOWED_FX_HOSTS))
        raise ValueError(f"FX_BASE_URL должен быть одним из: {allowed}")
    if parsed.path or parsed.query or parsed.fragment:
        raise ValueError("FX_BASE_URL должен содержать только схему и домен")
    return raw_url


def _parse_sender_quote_mode() -> str:
    mode = os.getenv("SENDER_QUOTE_MODE", "name").strip().lower()
    if mode not in {"name", "username", "mention"}:
        raise ValueError("SENDER_QUOTE_MODE должен быть name, username или mention")
    return mode


def _parse_web_base_url() -> str:
    raw_url = os.getenv("WEB_BASE_URL", "").strip().rstrip("/")
    if not raw_url:
        return ""

    parsed = urlparse(raw_url)
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("WEB_BASE_URL должен быть абсолютным http(s) URL")
    if parsed.scheme != "https" and parsed.hostname not in local_hosts:
        raise ValueError("WEB_BASE_URL должен использовать https (http разрешён только для localhost)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("WEB_BASE_URL не должен содержать логин, пароль, query или fragment")
    return raw_url


@dataclass
class Config:
    BOT_TOKEN: str
    APP_NAME: str = "Dropwire"
    MODE: str = "polling"
    TELEGRAM_USER_IDS: Optional[list[int]] = None
    BOT_ADMIN_IDS: list[int] = field(default_factory=list)
    REPLY_IN_GROUPS: bool = False
    REMOVE_MESSAGE_IN_GROUPS: bool = False
    COMPRESS_MEDIA: bool = True
    MAX_MEDIA_MB: int = 20
    FX_BASE_URL: str = "https://fxtwitter.com"
    INCLUDE_QUOTED_MEDIA: bool = False
    DEFAULT_TRANSLATE_LANG: str = "off"
    LOG_LEVEL: str = "INFO"
    RATE_LIMIT_SECONDS: int = 5
    RATE_LIMIT_CHAT_SECONDS: int = 3
    REPLY_TO_MESSAGE: bool = True
    CAPTION_ABOVE_MEDIA: bool = True
    DUMP_TWEET_HTML: bool = False
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_WAIT_MIN: float = 0.5
    RETRY_WAIT_MAX: float = 4.0
    RETRY_WAIT_MULTIPLIER: float = 0.5
    RETRY_STATUS_CODES: list[int] = field(default_factory=lambda: [408, 429])
    TRANSLATE_SETTINGS_PATH: str = "data/translate_settings.json"
    ENABLE_HASHTAGS: bool = True
    YOUTUBE_API_KEY: str = ""
    SPOTIFY_CLIENT_ID: str = ""
    SPOTIFY_CLIENT_SECRET: str = ""
    DATABASE_PATH: str = "data/dropwire.sqlite3"
    DOWNLOAD_DIR: str = "downloads"
    MAX_VIDEO_DURATION_MINUTES: int = 20
    MAX_FILE_SIZE_MB: int = 1900
    MAX_CONCURRENT_DOWNLOADS: int = 2
    WEB_BASE_URL: str = ""
    DOWNLOAD_TOKEN_SECRET: str = ""
    DOWNLOAD_LINK_TTL_MINUTES: int = 60
    DOWNLOAD_FILE_RETENTION_HOURS: int = 24
    MAX_ACTIVE_DOWNLOADS_PER_USER: int = 3
    MAX_LINKS_PER_MESSAGE: int = 5
    PROVIDER_RESPONSE_MAX_KB: int = 512
    TELEGRAM_CONNECT_TIMEOUT: float = 15.0
    TELEGRAM_READ_TIMEOUT: float = 30.0
    TELEGRAM_WRITE_TIMEOUT: float = 60.0
    TELEGRAM_POOL_TIMEOUT: float = 15.0
    INCLUDE_SENDER_QUOTE: bool = True
    SENDER_QUOTE_MODE: str = "name"

    @classmethod
    def from_env(cls) -> "Config":
        bot_token = os.getenv("BOT_TOKEN")
        if not bot_token:
            raise ValueError("BOT_TOKEN обязателен")

        mode = os.getenv("MODE", "polling")
        if mode not in {"polling", "webhook"}:
            raise ValueError("MODE должен быть polling или webhook")

        allowed_user_ids = _parse_user_ids("TELEGRAM_USER_IDS")
        admin_user_ids = _parse_user_ids("BOT_ADMIN_IDS")
        download_token_secret = os.getenv("DOWNLOAD_TOKEN_SECRET", "").strip()
        if download_token_secret and len(download_token_secret) < 32:
            raise ValueError("DOWNLOAD_TOKEN_SECRET должен содержать не менее 32 символов")

        return cls(
            BOT_TOKEN=bot_token,
            APP_NAME=os.getenv("APP_NAME", "Dropwire").strip() or "Dropwire",
            MODE=mode,
            TELEGRAM_USER_IDS=allowed_user_ids,
            BOT_ADMIN_IDS=admin_user_ids or allowed_user_ids or [],
            REPLY_IN_GROUPS=_parse_bool("REPLY_IN_GROUPS"),
            REMOVE_MESSAGE_IN_GROUPS=_parse_bool("REMOVE_MESSAGE_IN_GROUPS"),
            COMPRESS_MEDIA=_parse_bool("COMPRESS_MEDIA", "1"),
            MAX_MEDIA_MB=_parse_int("MAX_MEDIA_MB", 20, min_value=1),
            FX_BASE_URL=_parse_fx_base_url(),
            INCLUDE_QUOTED_MEDIA=_parse_bool("INCLUDE_QUOTED_MEDIA"),
            DEFAULT_TRANSLATE_LANG=os.getenv("DEFAULT_TRANSLATE_LANG", "off").strip().lower(),
            LOG_LEVEL=os.getenv("LOG_LEVEL", "INFO").upper(),
            RATE_LIMIT_SECONDS=_parse_int("RATE_LIMIT_SECONDS", 5, min_value=0),
            RATE_LIMIT_CHAT_SECONDS=_parse_int("RATE_LIMIT_CHAT_SECONDS", 3, min_value=0),
            REPLY_TO_MESSAGE=_parse_bool("REPLY_TO_MESSAGE", "1"),
            CAPTION_ABOVE_MEDIA=_parse_bool("CAPTION_ABOVE_MEDIA", "1"),
            DUMP_TWEET_HTML=_parse_bool("DUMP_TWEET_HTML"),
            RETRY_MAX_ATTEMPTS=_parse_int("RETRY_MAX_ATTEMPTS", 3, min_value=1),
            RETRY_WAIT_MIN=_parse_float("RETRY_WAIT_MIN", 0.5, min_value=0),
            RETRY_WAIT_MAX=_parse_float("RETRY_WAIT_MAX", 4.0, min_value=0),
            RETRY_WAIT_MULTIPLIER=_parse_float("RETRY_WAIT_MULTIPLIER", 0.5, min_value=0),
            RETRY_STATUS_CODES=_parse_retry_status_codes(),
            TRANSLATE_SETTINGS_PATH=os.getenv(
                "TRANSLATE_SETTINGS_PATH",
                "data/translate_settings.json",
            ),
            ENABLE_HASHTAGS=_parse_bool("ENABLE_HASHTAGS", "1"),
            YOUTUBE_API_KEY=os.getenv("YOUTUBE_API_KEY", "").strip(),
            SPOTIFY_CLIENT_ID=os.getenv("SPOTIFY_CLIENT_ID", "").strip(),
            SPOTIFY_CLIENT_SECRET=os.getenv("SPOTIFY_CLIENT_SECRET", "").strip(),
            DATABASE_PATH=os.getenv("DATABASE_PATH", "data/dropwire.sqlite3").strip(),
            DOWNLOAD_DIR=os.getenv("DOWNLOAD_DIR", "downloads").strip(),
            MAX_VIDEO_DURATION_MINUTES=_parse_int("MAX_VIDEO_DURATION_MINUTES", 20, min_value=1),
            MAX_FILE_SIZE_MB=_parse_int("MAX_FILE_SIZE_MB", 1900, min_value=1),
            MAX_CONCURRENT_DOWNLOADS=_parse_int("MAX_CONCURRENT_DOWNLOADS", 2, min_value=1),
            WEB_BASE_URL=_parse_web_base_url(),
            DOWNLOAD_TOKEN_SECRET=download_token_secret,
            DOWNLOAD_LINK_TTL_MINUTES=_parse_int("DOWNLOAD_LINK_TTL_MINUTES", 60, min_value=1),
            DOWNLOAD_FILE_RETENTION_HOURS=_parse_int("DOWNLOAD_FILE_RETENTION_HOURS", 24, min_value=1),
            MAX_ACTIVE_DOWNLOADS_PER_USER=_parse_int("MAX_ACTIVE_DOWNLOADS_PER_USER", 3, min_value=1),
            MAX_LINKS_PER_MESSAGE=_parse_int("MAX_LINKS_PER_MESSAGE", 5, min_value=1),
            PROVIDER_RESPONSE_MAX_KB=_parse_int("PROVIDER_RESPONSE_MAX_KB", 512, min_value=16),
            TELEGRAM_CONNECT_TIMEOUT=_parse_float("TELEGRAM_CONNECT_TIMEOUT", 15.0, min_value=1.0),
            TELEGRAM_READ_TIMEOUT=_parse_float("TELEGRAM_READ_TIMEOUT", 30.0, min_value=1.0),
            TELEGRAM_WRITE_TIMEOUT=_parse_float("TELEGRAM_WRITE_TIMEOUT", 60.0, min_value=1.0),
            TELEGRAM_POOL_TIMEOUT=_parse_float("TELEGRAM_POOL_TIMEOUT", 15.0, min_value=1.0),
            INCLUDE_SENDER_QUOTE=_parse_bool("INCLUDE_SENDER_QUOTE", "1"),
            SENDER_QUOTE_MODE=_parse_sender_quote_mode(),
        )


config = Config.from_env()
