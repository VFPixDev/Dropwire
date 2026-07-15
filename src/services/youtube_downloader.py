import asyncio
import json
import logging
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from src.providers.youtube_urls import VIDEO_ID_RE

logger = logging.getLogger(__name__)


@dataclass
class FormatOption:
    key: str
    label: str


@dataclass
class DownloadedFile:
    file_path: Path
    final_size: int
    format_note: str
    cleanup_paths: list[Path]


class YtDlpDownloader:
    def __init__(self, base_download_dir: str) -> None:
        self.base_download_dir = Path(base_download_dir)
        self.base_download_dir.mkdir(parents=True, exist_ok=True)

    async def get_available_format_options(self, video_url: str) -> list[FormatOption]:
        info = await asyncio.to_thread(self._extract_info_sync, video_url)
        formats = info.get("formats", [])

        available_heights: set[int] = set()
        for item in formats:
            if item.get("vcodec") == "none":
                continue
            height = item.get("height")
            if isinstance(height, int):
                available_heights.add(height)

        targets = [360, 480, 720, 1080]
        options: list[FormatOption] = []
        used_source_heights: set[int] = set()
        for target in targets:
            candidate = max((height for height in available_heights if height <= target), default=None)
            if candidate is not None and candidate not in used_source_heights:
                options.append(FormatOption(key=str(target), label=f"🎞 {target}p"))
                used_source_heights.add(candidate)

        options.append(FormatOption(key="audio", label="🎵 Только аудио"))
        return options

    async def get_duration_seconds(self, video_id: str) -> int:
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        info = await asyncio.to_thread(self._extract_info_sync, video_url)
        duration = info.get("duration") or 0
        return max(int(duration), 0)

    async def download(self, video_id: str, quality: str, progress_callback) -> DownloadedFile:
        if not VIDEO_ID_RE.fullmatch(video_id):
            raise ValueError("Некорректный YouTube video id")
        if quality not in {"360", "480", "720", "1080", "audio"}:
            raise ValueError("Некорректное качество загрузки")
        temp_dir = self.base_download_dir / f"job_{video_id}_{uuid4().hex[:8]}"
        temp_dir.mkdir(parents=True, exist_ok=True)
        video_url = f"https://www.youtube.com/watch?v={video_id}"

        loop = asyncio.get_running_loop()
        last_progress_emit_percent = -1
        last_progress_emit_ts = 0.0

        async def emit(stage: str, percent: int | None = None) -> None:
            try:
                await progress_callback(stage, percent)
            except Exception:
                logger.exception("Progress callback failed: stage=%s percent=%s", stage, percent)

        def sync_emit(stage: str, percent: int | None = None) -> None:
            nonlocal last_progress_emit_percent, last_progress_emit_ts
            if stage == "downloading" and percent is not None:
                now = time.monotonic()
                if percent == last_progress_emit_percent and now - last_progress_emit_ts < 1.5:
                    return
                if (
                    last_progress_emit_percent >= 0
                    and percent - last_progress_emit_percent < 2
                    and now - last_progress_emit_ts < 1.5
                ):
                    return
                last_progress_emit_percent = percent
                last_progress_emit_ts = now
            loop.call_soon_threadsafe(asyncio.create_task, emit(stage, percent))

        try:
            sync_emit("info")
            final_file = await asyncio.to_thread(self._download_sync, video_url, quality, temp_dir, sync_emit)

            stored_file = self.base_download_dir / f"{video_id}_{uuid4().hex[:10]}{final_file.suffix}"
            shutil.move(str(final_file), str(stored_file))
            await self.cleanup([temp_dir])

            format_note = "audio" if quality == "audio" else f"{quality}p"
            return DownloadedFile(
                file_path=stored_file,
                final_size=stored_file.stat().st_size,
                format_note=format_note,
                cleanup_paths=[stored_file],
            )
        except DownloadError as exc:
            await self.cleanup([temp_dir])
            raise RuntimeError(f"Ошибка yt-dlp: {exc}") from exc
        except Exception:
            await self.cleanup([temp_dir])
            raise

    async def cleanup(self, paths: list[Path]) -> None:
        for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
            try:
                if path.is_file():
                    path.unlink(missing_ok=True)
                elif path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                logger.exception("Не удалось удалить временный путь: %s", path)

    def _extract_info_sync(self, video_url: str) -> dict[str, Any]:
        with YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True}) as ydl:
            return ydl.extract_info(video_url, download=False)

    def _build_format_selector(self, quality: str) -> str:
        if quality == "audio":
            return "bestaudio[ext=m4a][acodec^=mp4a]/bestaudio[ext=m4a]/bestaudio/best"

        quality_int = int(quality)
        return (
            f"bestvideo[height<={quality_int}][ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a][acodec^=mp4a]/"
            f"bestvideo[height<={quality_int}][ext=mp4]+bestaudio[ext=m4a]/"
            f"best[height<={quality_int}][ext=mp4][vcodec^=avc1][acodec^=mp4a]/"
            f"best[height<={quality_int}][ext=mp4]/best[height<={quality_int}]"
        )

    def _download_sync(self, video_url: str, quality: str, temp_dir: Path, sync_emit) -> Path:
        def hook(data: dict[str, Any]) -> None:
            status = data.get("status")
            if status == "downloading":
                downloaded = data.get("downloaded_bytes") or 0
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                if total:
                    sync_emit("downloading", min(max(int(downloaded / total * 100), 0), 100))
            elif status == "finished":
                sync_emit("merging")

        ydl_opts: dict[str, Any] = {
            "format": self._build_format_selector(quality),
            "outtmpl": str(temp_dir / "%(id)s_%(format_id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "merge_output_format": "mp4",
            "progress_hooks": [hook],
            "retries": 3,
            "fragment_retries": 3,
        }
        if quality == "audio":
            ydl_opts["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "m4a",
                    "preferredquality": "0",
                }
            ]
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])

        if quality == "audio":
            audio_candidates = [file for file in temp_dir.glob("*.m4a") if file.is_file()]
            source_file = max(audio_candidates, key=lambda file: file.stat().st_size) if audio_candidates else None
        else:
            source_file = self._pick_final_file(temp_dir)
        if source_file is None:
            raise RuntimeError("Не удалось найти скачанный файл")
        if quality == "audio":
            self._verify_iphone_media(source_file, audio_only=True)
            return source_file

        sync_emit("converting")
        output_file = temp_dir / "iphone_ready.mp4"
        self._transcode_for_iphone(source_file, output_file)
        self._verify_iphone_media(output_file, audio_only=False)
        return output_file

    def _transcode_for_iphone(self, source_file: Path, output_file: Path) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise RuntimeError("FFmpeg не установлен")
        command = self._build_iphone_ffmpeg_command(ffmpeg, source_file, output_file)
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=1800)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            stderr = getattr(exc, "stderr", b"") or b""
            logger.error("FFmpeg conversion failed: %s", stderr.decode("utf-8", errors="replace")[-1000:])
            raise RuntimeError("Не удалось подготовить совместимый MP4-файл") from exc

    @staticmethod
    def _build_iphone_ffmpeg_command(ffmpeg: str, source_file: Path, output_file: Path) -> list[str]:
        return [
            ffmpeg,
            "-y",
            "-i",
            str(source_file),
            "-map",
            "0:v:0",
            "-map",
            "0:a:0?",
            "-vf",
            "scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v",
            "libx264",
            "-profile:v",
            "high",
            "-preset",
            "veryfast",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-sn",
            str(output_file),
        ]

    def _verify_iphone_media(self, file_path: Path, audio_only: bool) -> None:
        ffprobe = shutil.which("ffprobe")
        if not ffprobe:
            raise RuntimeError("FFprobe не установлен")
        command = [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type,codec_name,pix_fmt:format=format_name",
            "-of",
            "json",
            str(file_path),
        ]
        try:
            result = subprocess.run(command, check=True, capture_output=True, timeout=60)
            payload = json.loads(result.stdout.decode("utf-8"))
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            raise RuntimeError("Не удалось проверить формат готового файла") from exc

        streams = payload.get("streams", [])
        audio_streams = [item for item in streams if item.get("codec_type") == "audio"]
        video_streams = [item for item in streams if item.get("codec_type") == "video"]
        format_name = str(payload.get("format", {}).get("format_name", ""))
        if not audio_streams or audio_streams[0].get("codec_name") != "aac":
            raise RuntimeError("Готовый файл не содержит совместимую AAC-аудиодорожку")
        if not any(name in format_name.split(",") for name in {"mov", "mp4", "m4a"}):
            raise RuntimeError("Готовый файл имеет несовместимый контейнер")
        if audio_only:
            return
        if not video_streams or video_streams[0].get("codec_name") != "h264":
            raise RuntimeError("Готовый файл не содержит H.264-видео")
        if video_streams[0].get("pix_fmt") not in {"yuv420p", "yuvj420p"}:
            raise RuntimeError("Готовый файл имеет несовместимый формат пикселей")

    async def cleanup_stale_files(self, max_age_seconds: int, exclude_paths: set[Path] | None = None) -> None:
        safe_age_seconds = max(int(max_age_seconds), 300)
        cutoff = time.time() - safe_age_seconds
        excludes = {path.resolve() for path in (exclude_paths or set())}
        for file in self.base_download_dir.iterdir():
            try:
                resolved = file.resolve()
                if resolved in excludes:
                    continue
                if file.is_file() and file.stat().st_mtime < cutoff:
                    file.unlink(missing_ok=True)
                elif file.is_dir() and file.stat().st_mtime < cutoff:
                    shutil.rmtree(file, ignore_errors=True)
            except Exception:
                logger.exception("Не удалось удалить устаревший файл: %s", file)

    def _pick_final_file(self, temp_dir: Path) -> Path | None:
        candidates = [
            file
            for file in temp_dir.glob("*")
            if file.is_file() and not file.name.endswith(".part") and not file.name.endswith(".ytdl")
        ]
        return max(candidates, key=lambda file: file.stat().st_size) if candidates else None
