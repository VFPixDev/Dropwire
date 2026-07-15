import logging
from typing import Optional
import ipaddress
from urllib.parse import urljoin, urlparse

import httpx
from tenacity import before_sleep_log, retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import config

logger = logging.getLogger(__name__)

RETRY_STATUS_CODES = set(config.RETRY_STATUS_CODES)
DEFAULT_MEDIA_MAX_BYTES = config.MAX_MEDIA_MB * 1024 * 1024
TRUSTED_TWITTER_MEDIA_HOSTS = {
    "pbs.twimg.com",
    "pbs.fxtwitter.com",
    "video.twimg.com",
    "abs.twimg.com",
    "ton.twimg.com",
}


class MediaTooLargeError(ValueError):
    """Raised when a media response exceeds configured download limits."""


def _is_retry_status(status_code: int) -> bool:
    return status_code in RETRY_STATUS_CODES or 500 <= status_code < 600


@retry(
    reraise=True,
    stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
    wait=wait_exponential(
        multiplier=config.RETRY_WAIT_MULTIPLIER,
        min=config.RETRY_WAIT_MIN,
        max=config.RETRY_WAIT_MAX,
    ),
    retry=retry_if_exception_type(
        (
            httpx.TimeoutException,
            httpx.RequestError,
            httpx.HTTPStatusError,
        )
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def _get_with_retry(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> httpx.Response:
    response = await client.get(url, headers=headers)
    if _is_retry_status(response.status_code):
        raise httpx.HTTPStatusError(
            f"Retryable HTTP {response.status_code}",
            request=response.request,
            response=response,
        )
    return response


async def fetch_tweet_data(tweet_id: str, username: str, lang_code: Optional[str] = None) -> Optional[dict]:
    """Получает данные твита через FxTwitter API."""
    api_url = f"{config.FX_BASE_URL}/api/status/{tweet_id}"

    logger.info("Запрос API твита: %s", api_url)

    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            headers = {
                "User-Agent": "TelegramBot/1.0",
                "Accept": "application/json",
            }

            if lang_code:
                headers["Accept-Language"] = lang_code

            response = await _get_with_retry(client, api_url, headers)

            if response.status_code == 200:
                try:
                    data = response.json()
                    logger.debug(
                        "Получены данные: %s",
                        list(data.keys()) if isinstance(data, dict) else type(data),
                    )
                    return data if isinstance(data, dict) else None
                except Exception as exc:
                    logger.error("Ошибка парсинга JSON: %s", exc)
                    return None
            if response.status_code == 404:
                logger.warning("Твит не найден: %s", api_url)
                return None
            if response.status_code in [403, 401]:
                logger.warning("Твит недоступен: %s", api_url)
                return None

            logger.error("Ошибка HTTP %s: %s", response.status_code, api_url)
            return None
        except httpx.TimeoutException:
            logger.error("Таймаут при запросе: %s", api_url)
            return None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else "unknown"
            logger.error("Ошибка HTTP %s: %s", status, api_url)
            return None
        except Exception as exc:
            logger.error("Ошибка при получении твита: %s", exc)
            return None


async def fetch_tweet_html(tweet_id: str, username: str, lang_code: Optional[str] = None) -> Optional[str]:
    """Получает HTML страницы твита через FxTwitter/FixupX (fallback)."""
    base_url = f"{config.FX_BASE_URL}/{username}/status/{tweet_id}"
    url = f"{base_url}/{lang_code}" if lang_code else base_url

    logger.info("Запрос HTML твита: %s", url)

    timeout = httpx.Timeout(30.0, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        try:
            response = await _get_with_retry(
                client,
                url,
                {"User-Agent": "TelegramBot/1.0 (compatible; +https://t.me/your_bot)"},
            )

            if response.status_code == 200:
                return response.text
            if response.status_code == 404:
                logger.warning("Твит не найден: %s", url)
                return None
            if response.status_code in [403, 401]:
                logger.warning("Твит недоступен (приватный/18+): %s", url)
                return None

            logger.error("Ошибка HTTP %s: %s", response.status_code, url)
            return None
        except httpx.TimeoutException:
            logger.error("Таймаут при запросе: %s", url)
            return None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response else "unknown"
            logger.error("Ошибка HTTP %s: %s", status, url)
            return None
        except Exception as exc:
            logger.error("Ошибка при получении твита: %s", exc)
            return None


@retry(
    reraise=True,
    stop=stop_after_attempt(config.RETRY_MAX_ATTEMPTS),
    wait=wait_exponential(
        multiplier=config.RETRY_WAIT_MULTIPLIER,
        min=config.RETRY_WAIT_MIN,
        max=config.RETRY_WAIT_MAX,
    ),
    retry=retry_if_exception_type(
        (
            httpx.TimeoutException,
            httpx.RequestError,
            httpx.HTTPStatusError,
        )
    ),
    before_sleep=before_sleep_log(logger, logging.WARNING),
)
async def _download_media_once(
    url: str,
    headers: dict[str, str],
    max_bytes: int,
    trusted_twitter_hosts_only: bool = False,
) -> bytes:
    timeout = httpx.Timeout(60.0, connect=10.0)
    current_url = url
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for _ in range(4):
            parsed_current_url = urlparse(current_url)
            if not _is_safe_media_url(parsed_current_url) or (
                trusted_twitter_hosts_only and not _is_trusted_twitter_media_host(parsed_current_url.hostname)
            ):
                raise ValueError("Небезопасный media redirect")
            async with client.stream("GET", current_url, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("Location")
                    if not location:
                        return b""
                    current_url = urljoin(current_url, location)
                    continue
                if _is_retry_status(response.status_code):
                    raise httpx.HTTPStatusError(
                        f"Retryable HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                if response.status_code != 200:
                    logger.error("Ошибка загрузки медиа %s: %s", response.status_code, current_url)
                    return b""

                content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                if content_type and not (
                    content_type.startswith("image/")
                    or content_type.startswith("video/")
                    or content_type == "application/octet-stream"
                ):
                    logger.warning("Медиа URL вернул неподдерживаемый Content-Type: %s", content_type)
                    return b""

                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        declared_size = int(content_length)
                    except ValueError:
                        logger.warning("Некорректный Content-Length для %s: %s", current_url, content_length)
                    else:
                        if declared_size > max_bytes:
                            raise MediaTooLargeError(f"Медиа больше лимита: {declared_size} байт > {max_bytes} байт")

                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise MediaTooLargeError(f"Медиа больше лимита: {len(data)} байт > {max_bytes} байт")
                return bytes(data)
    raise ValueError("Слишком много media redirect")


async def download_media(url: str, max_bytes: int = DEFAULT_MEDIA_MAX_BYTES) -> Optional[bytes]:
    """Скачивает медиа файл с лимитом размера."""
    parsed_url = urlparse(url)
    if not _is_safe_media_url(parsed_url) or not _is_trusted_twitter_media_host(parsed_url.hostname):
        logger.warning("Медиа URL с недоверенным хостом или схемой пропущен: %s", url)
        return None

    try:
        content = await _download_media_once(
            url,
            {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            max_bytes=max_bytes,
            trusted_twitter_hosts_only=True,
        )
        return content or None
    except MediaTooLargeError as exc:
        logger.warning("Медиа пропущено: %s", exc)
        return None
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response else "unknown"
        logger.error("Ошибка загрузки медиа %s: %s", status, url)
        return None
    except Exception as exc:
        logger.error("Ошибка при загрузке медиа: %s", exc)
        return None


def _is_safe_media_url(parsed_url) -> bool:
    if parsed_url.scheme not in {"http", "https"}:
        return False

    hostname = parsed_url.hostname
    if not hostname:
        return False

    lowered = hostname.lower().rstrip(".")
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".localhost"):
        return False

    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return True

    return not (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified
    )


def _is_trusted_twitter_media_host(hostname: str | None) -> bool:
    return bool(hostname and hostname.lower().rstrip(".") in TRUSTED_TWITTER_MEDIA_HOSTS)
