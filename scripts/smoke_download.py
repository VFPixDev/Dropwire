import asyncio
import tempfile
from pathlib import Path

from src.services.youtube_downloader import YtDlpDownloader

VIDEO_ID = "jNQXAC9IVRw"  # A short public YouTube video used for the live conversion check.


async def _ignore_progress(stage: str, percent: int | None) -> None:
    return None


async def main() -> int:
    download_dir = Path(tempfile.gettempdir()) / "dropwire-download-smoke"
    downloader = YtDlpDownloader(str(download_dir))
    downloaded = None
    try:
        downloaded = await downloader.download(VIDEO_ID, "360", _ignore_progress)
        print(f"youtube download: ok ({downloaded.format_note}, {downloaded.final_size} bytes)")
        return 0
    except Exception as exc:
        print(f"youtube download: failed ({type(exc).__name__})")
        return 1
    finally:
        if downloaded is not None:
            await downloader.cleanup(downloaded.cleanup_paths)
        await downloader.cleanup([download_dir])


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
