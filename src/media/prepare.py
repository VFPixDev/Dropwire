"""Prepare downloaded bytes outside the event loop and clean temporary outputs."""

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory

from src.config import config
from src.media.compress import VideoMetadata, compress_image, compress_video, probe_video


async def prepare_upload(content: bytes, media_type: str) -> tuple[bytes | None, VideoMetadata | None]:
    return await asyncio.to_thread(_prepare_upload, content, media_type)


def _prepare_upload(content: bytes, media_type: str) -> tuple[bytes | None, VideoMetadata | None]:
    max_mb = min(config.MAX_MEDIA_MB, 10 if media_type == "photo" else 50)
    with TemporaryDirectory(prefix="dropwire_prepare_") as directory:
        source = Path(directory) / ("source.jpg" if media_type == "photo" else "source.mp4")
        source.write_bytes(content)
        output = source
        try:
            if media_type == "photo":
                output = Path(compress_image(str(source), max_size_mb=max_mb))
                metadata = None
            else:
                output = Path(compress_video(str(source), max_size_mb=max_mb, is_animation=media_type == "animation"))
                metadata = probe_video(str(output))
            if output.stat().st_size > max_mb * 1024 * 1024:
                return None, None
            return output.read_bytes(), metadata
        finally:
            if output != source:
                output.unlink(missing_ok=True)
