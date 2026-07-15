import logging
import os
import tempfile
from typing import Optional

from src.config import config
from src.twitter.fetcher import download_media

logger = logging.getLogger(__name__)


def _media_extension(url: str, media_type: str) -> str:
    if media_type == "video":
        return ".mp4"

    lowered_url = url.lower()
    if ".png" in lowered_url:
        return ".png"
    if ".webp" in lowered_url:
        return ".webp"
    if ".gif" in lowered_url:
        return ".gif"
    return ".jpg"


async def download_media_file(url: str, media_type: str = "photo") -> Optional[str]:
    """Скачивает медиа файл во временную директорию."""
    max_bytes = config.MAX_MEDIA_MB * 1024 * 1024
    content = await download_media(url, max_bytes=max_bytes)
    if not content:
        return None

    ext = _media_extension(url, media_type)

    try:
        fd, temp_path = tempfile.mkstemp(suffix=ext, dir="/tmp", prefix="tweet_media_")
        os.close(fd)

        with open(temp_path, "wb") as f:
            f.write(content)

        logger.info("Медиа скачано: %s (%s байт)", temp_path, len(content))
        return temp_path
    except Exception as exc:
        logger.error("Ошибка сохранения медиа: %s", exc)
        return None


def get_file_size_mb(file_path: str) -> float:
    """Возвращает размер файла в МБ."""
    try:
        size_bytes = os.path.getsize(file_path)
        return size_bytes / (1024 * 1024)
    except Exception:
        return 0.0
