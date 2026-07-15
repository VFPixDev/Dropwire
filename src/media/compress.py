import logging
import os
import shutil
# ffmpeg is invoked with argument lists and without a shell.
import subprocess  # nosec B404
import tempfile

from PIL import Image

from src.config import config
from src.media.download import get_file_size_mb

logger = logging.getLogger(__name__)


def _is_within_limit(path: str, max_size_mb: float) -> bool:
    return get_file_size_mb(path) <= max_size_mb


def compress_image(input_path: str, max_size_mb: float | None = None) -> str:
    """Сжимает изображение и возвращает путь только к файлу в пределах лимита, если это возможно."""
    if max_size_mb is None:
        max_size_mb = config.MAX_MEDIA_MB

    if not config.COMPRESS_MEDIA:
        return input_path

    current_size = get_file_size_mb(input_path)
    if current_size <= max_size_mb:
        return input_path

    try:
        with Image.open(input_path) as img:
            # Конвертируем в RGB если нужно
            if img.mode in ("RGBA", "LA", "P"):
                working_image = img.convert("RGBA") if img.mode == "P" else img
                background = Image.new("RGB", working_image.size, (255, 255, 255))
                background.paste(
                    working_image,
                    mask=working_image.split()[-1] if working_image.mode in ("RGBA", "LA") else None,
                )
                rgb_image = background
            else:
                rgb_image = img.convert("RGB")

            fd, output_path = tempfile.mkstemp(suffix=".jpg", dir=tempfile.gettempdir(), prefix="compressed_")
            os.close(fd)

            quality = 85
            rgb_image.save(output_path, "JPEG", quality=quality, optimize=True)

            while not _is_within_limit(output_path, max_size_mb) and quality > 30:
                quality -= 5
                rgb_image.save(output_path, "JPEG", quality=quality, optimize=True)

        new_size = get_file_size_mb(output_path)
        logger.info("Изображение сжато: %.2fMB -> %.2fMB", current_size, new_size)
        if new_size <= max_size_mb:
            return output_path

        logger.warning("Сжатое изображение всё ещё больше лимита: %.2fMB > %.2fMB", new_size, max_size_mb)
        return input_path
    except Exception as exc:
        logger.error("Ошибка сжатия изображения: %s", exc)
        return input_path


def compress_video(input_path: str, max_size_mb: float | None = None) -> str:
    """Сжимает видео через ffmpeg (если доступен)."""
    if max_size_mb is None:
        max_size_mb = config.MAX_MEDIA_MB

    if not config.COMPRESS_MEDIA:
        return input_path

    current_size = get_file_size_mb(input_path)
    if current_size <= max_size_mb:
        return input_path

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        logger.warning("ffmpeg не найден, сжатие видео недоступно")
        return input_path

    try:
        subprocess.run([ffmpeg, "-version"], capture_output=True, check=True)  # nosec B603
    except subprocess.CalledProcessError:
        logger.warning("ffmpeg недоступен, сжатие видео невозможно")
        return input_path

    try:
        fd, output_path = tempfile.mkstemp(suffix=".mp4", dir=tempfile.gettempdir(), prefix="compressed_")
        os.close(fd)

        cmd = [
            ffmpeg,
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-crf",
            "28",
            "-preset",
            "fast",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            "-y",
            output_path,
        ]

        result = subprocess.run(cmd, capture_output=True, timeout=120)  # nosec B603

        if result.returncode == 0 and os.path.exists(output_path):
            new_size = get_file_size_mb(output_path)
            logger.info("Видео сжато: %.2fMB -> %.2fMB", current_size, new_size)
            if new_size <= max_size_mb:
                return output_path
            logger.warning("Сжатое видео всё ещё больше лимита: %.2fMB > %.2fMB", new_size, max_size_mb)
        else:
            logger.error("Ошибка сжатия видео через ffmpeg: %s", result.stderr.decode(errors="ignore")[:500])
        return input_path
    except subprocess.TimeoutExpired:
        logger.error("Timeout сжатия видео")
        return input_path
    except Exception as exc:
        logger.error("Ошибка сжатия видео: %s", exc)
        return input_path
