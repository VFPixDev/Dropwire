import logging
import os
import shutil
import json
from dataclasses import dataclass
# ffmpeg is invoked with argument lists and without a shell.
import subprocess  # nosec B404
import tempfile

from PIL import Image

from src.config import config
from src.media.download import get_file_size_mb

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class VideoMetadata:
    width: int | None = None
    height: int | None = None
    duration: int | None = None
    video_codec: str | None = None
    audio_codec: str | None = None
    pixel_format: str | None = None
    sample_aspect_ratio: str | None = None
    rotation: int = 0


def probe_video(input_path: str) -> VideoMetadata | None:
    """Read media geometry without trusting filename or container metadata alone."""
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        input_path,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, timeout=15, check=True)  # nosec B603
        payload = json.loads(result.stdout)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
        logger.warning("Не удалось прочитать метаданные видео: %s", input_path)
        return None

    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        return None
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not isinstance(video, dict):
        return None

    rotation = 0
    tags = video.get("tags")
    if isinstance(tags, dict):
        try:
            rotation = int(tags.get("rotate", 0)) % 360
        except (TypeError, ValueError):
            rotation = 0
    for side_data in video.get("side_data_list") or []:
        if isinstance(side_data, dict) and side_data.get("rotation") is not None:
            try:
                rotation = int(side_data["rotation"]) % 360
            except (TypeError, ValueError):
                pass

    raw_duration = video.get("duration") or (payload.get("format") or {}).get("duration")
    try:
        duration = max(0, round(float(raw_duration))) if raw_duration is not None else None
    except (TypeError, ValueError):
        duration = None

    return VideoMetadata(
        width=_positive_int(video.get("width")),
        height=_positive_int(video.get("height")),
        duration=duration,
        video_codec=_text_or_none(video.get("codec_name")),
        audio_codec=_text_or_none(audio.get("codec_name")) if isinstance(audio, dict) else None,
        pixel_format=_text_or_none(video.get("pix_fmt")),
        sample_aspect_ratio=_text_or_none(video.get("sample_aspect_ratio")),
        rotation=rotation,
    )


def _positive_int(value) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _text_or_none(value) -> str | None:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


def _needs_compatibility_transcode(metadata: VideoMetadata | None, is_animation: bool) -> bool:
    if metadata is None:
        return False
    dimensions_invalid = bool(
        metadata.width and metadata.height and (metadata.width % 2 != 0 or metadata.height % 2 != 0)
    )
    sar = metadata.sample_aspect_ratio
    non_square_pixels = sar not in {None, "1:1", "0:1", "n/a"}
    incompatible_audio = not is_animation and metadata.audio_codec not in {None, "aac"}
    return any(
        (
            metadata.video_codec != "h264",
            metadata.pixel_format not in {None, "yuv420p"},
            incompatible_audio,
            non_square_pixels,
            dimensions_invalid,
            metadata.rotation != 0,
        )
    )


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


def compress_video(input_path: str, max_size_mb: float | None = None, *, is_animation: bool = False) -> str:
    """Normalize video for Telegram/iPhone and reduce it when it exceeds the limit."""
    if max_size_mb is None:
        max_size_mb = config.MAX_MEDIA_MB

    current_size = get_file_size_mb(input_path)
    metadata = probe_video(input_path)
    needs_compatibility = _needs_compatibility_transcode(metadata, is_animation)
    needs_compression = current_size > max_size_mb
    if not needs_compatibility and (not needs_compression or not config.COMPRESS_MEDIA):
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

        crf = "28" if needs_compression else "23"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            input_path,
            "-map_metadata",
            "-1",
            "-vf",
            "scale=trunc(iw*sar/2)*2:trunc(ih/2)*2,setsar=1",
            "-c:v",
            "libx264",
            "-crf",
            crf,
            "-preset",
            "fast",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
        ]
        if is_animation:
            cmd.append("-an")
        else:
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        cmd.extend(["-y", output_path])

        result = subprocess.run(cmd, capture_output=True, timeout=120)  # nosec B603

        if result.returncode == 0 and os.path.exists(output_path):
            new_size = get_file_size_mb(output_path)
            logger.info("Видео подготовлено: %.2fMB -> %.2fMB", current_size, new_size)
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
