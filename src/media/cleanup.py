import os
import time
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def cleanup_temp_files(temp_dir: str = "/tmp", max_age_seconds: int = 3600):
    """Удаляет старые временные файлы бота"""

    prefixes = ["tweet_media_", "compressed_"]
    temp_path = Path(temp_dir)

    if not temp_path.exists():
        return

    now = time.time()
    deleted_count = 0

    try:
        for file_path in temp_path.iterdir():
            if not file_path.is_file():
                continue

            # Проверяем префикс
            if not any(file_path.name.startswith(prefix) for prefix in prefixes):
                continue

            # Проверяем возраст файла
            try:
                file_age = now - file_path.stat().st_mtime

                if file_age > max_age_seconds:
                    file_path.unlink()
                    deleted_count += 1

            except Exception as e:
                logger.warning(f"Не удалось удалить {file_path}: {e}")

        if deleted_count > 0:
            logger.info(f"Удалено {deleted_count} старых временных файлов")

    except Exception as e:
        logger.error(f"Ошибка при очистке временных файлов: {e}")


def delete_file(file_path: str):
    """Удаляет один файл"""
    try:
        if os.path.exists(file_path):
            os.unlink(file_path)
            logger.debug(f"Удалён файл: {file_path}")
    except Exception as e:
        logger.warning(f"Не удалось удалить файл {file_path}: {e}")


def delete_files(file_paths: list[str]):
    """Удаляет список файлов"""
    for path in file_paths:
        delete_file(path)
