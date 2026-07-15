from pathlib import Path

from src.services.database import Database
from src.services.download_links import create_download_url
from src.services.providers import PROVIDERS, is_provider_enabled, provider_capability


async def build_download_menu_data(database: Database, user_id: int) -> tuple[int, list[dict[str, str]]]:
    rows = await database.list_recent_downloads_for_user(user_id, limit=10)
    items: list[dict[str, str]] = []
    for row in rows:
        path = Path(str(row["file_path"]))
        try:
            url = create_download_url(path)
        except (FileNotFoundError, RuntimeError, ValueError):
            continue
        size_mb = int(row["final_size"]) / (1024 * 1024)
        quality = str(row["format_note"] or "файл")
        video_id = str(row["video_id"])
        items.append({"url": url, "label": f"{video_id} · {quality} · {size_mb:.1f} MB"})
    return len(rows), items


async def build_provider_states(database: Database) -> dict[str, tuple[bool, str]]:
    return {source: (await is_provider_enabled(database, source), provider_capability(source)) for source in PROVIDERS}
