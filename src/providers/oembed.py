import json
from dataclasses import dataclass

import httpx

from src.config import config


class OEmbedError(RuntimeError):
    pass


@dataclass(frozen=True)
class OEmbedData:
    title: str
    thumbnail_url: str | None
    author_name: str | None
    author_url: str | None
    html: str | None


async def fetch_oembed(endpoint: str, shared_url: str, expected_provider: str) -> OEmbedData:
    timeout = httpx.Timeout(15.0, connect=8.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        response = await client.get(endpoint, params={"format": "json", "url": shared_url})

    if response.status_code == 404:
        raise ValueError(f"Ссылка {expected_provider} не найдена или недоступна")
    if response.status_code != 200:
        raise OEmbedError(f"{expected_provider} временно недоступен (HTTP {response.status_code})")

    max_bytes = config.PROVIDER_RESPONSE_MAX_KB * 1024
    if len(response.content) > max_bytes:
        raise OEmbedError(f"Ответ {expected_provider} превышает допустимый размер")

    try:
        payload = json.loads(response.content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OEmbedError(f"{expected_provider} вернул некорректный ответ") from exc

    if str(payload.get("provider_name", "")).lower() != expected_provider.lower():
        raise OEmbedError(f"Неожиданный источник метаданных {expected_provider}")

    title = str(payload.get("title", "")).strip()
    if not title:
        raise ValueError(f"У {expected_provider}-ссылки нет доступного названия")

    return OEmbedData(
        title=title[:500],
        thumbnail_url=_optional_text(payload.get("thumbnail_url"), 2048),
        author_name=_optional_text(payload.get("author_name"), 200),
        author_url=_optional_text(payload.get("author_url"), 2048),
        html=_optional_text(payload.get("html"), 10_000),
    )


def _optional_text(value: object, max_length: int) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()[:max_length]
