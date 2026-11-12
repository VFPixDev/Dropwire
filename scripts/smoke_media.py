"""Exercise real FFmpeg conversion without external services or Telegram sends."""

import asyncio
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory

from src.media.compress import probe_video
from src.media.prepare import prepare_upload
from src.services.youtube_downloader import YtDlpDownloader


async def main() -> None:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError("FFmpeg is required")
    with TemporaryDirectory(prefix="dropwire_media_smoke_") as directory:
        root = Path(directory)
        source = root / "source.mp4"
        subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=240x320:r=10:d=1",
                "-vf",
                "setsar=4/3",
                "-c:v",
                "mpeg4",
                "-y",
                str(source),
            ],
            check=True,
            timeout=20,
        )
        downloader = YtDlpDownloader(str(root))
        target = root / "iphone.mp4"
        downloader._transcode_for_iphone(source, target)
        downloader._verify_iphone_media(target, audio_only=False)
        metadata = probe_video(str(target))
        assert metadata and (metadata.width, metadata.height, metadata.sample_aspect_ratio) == (320, 320, "1:1")
        content, metadata = await prepare_upload(source.read_bytes(), "video")
        assert content and metadata and metadata.video_codec == "h264"
        assert (metadata.width, metadata.height, metadata.sample_aspect_ratio) == (320, 320, "1:1")
        print("silent video, aspect ratio and Telegram upload conversion: ok")


if __name__ == "__main__":
    asyncio.run(main())
