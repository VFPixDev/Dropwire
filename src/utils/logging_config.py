"""Redact configured credentials from messages and exception tracebacks."""

import logging
import re
from urllib.parse import quote, quote_plus

from src.config import config


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        for secret in (
            config.BOT_TOKEN,
            config.YOUTUBE_API_KEY,
            config.SPOTIFY_CLIENT_SECRET,
            config.DOWNLOAD_TOKEN_SECRET,
        ):
            if secret:
                for value in {secret, quote(secret, safe=""), quote_plus(secret)}:
                    text = text.replace(value, "[REDACTED]")
        return re.sub(r"(https?://[^\s/]+(?:/[^\s/]*)*/download/)[^\s\"'<>]+", r"\1[REDACTED]", text)


def configure_logging() -> None:
    logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
    formatter = RedactingFormatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    for handler in logging.getLogger().handlers:
        handler.setFormatter(formatter)
    for name in ("httpx", "httpcore", "aiohttp.access"):
        logging.getLogger(name).setLevel(logging.WARNING)
