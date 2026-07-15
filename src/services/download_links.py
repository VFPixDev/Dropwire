from pathlib import Path

from src.config import config
from src.services.download_token import generate_download_token


def create_download_url(file_path: str | Path) -> str:
    if not config.WEB_BASE_URL:
        raise RuntimeError("WEB_BASE_URL не настроен")

    download_dir = Path(config.DOWNLOAD_DIR).resolve()
    resolved_path = Path(file_path).resolve()
    try:
        relative_path = resolved_path.relative_to(download_dir)
    except ValueError as exc:
        raise ValueError("Файл находится вне каталога загрузок") from exc
    if not resolved_path.is_file():
        raise FileNotFoundError("Файл загрузки уже удалён")

    secret = config.DOWNLOAD_TOKEN_SECRET or config.BOT_TOKEN
    token = generate_download_token(
        relative_path=str(relative_path).replace("\\", "/"),
        secret=secret,
        ttl_seconds=config.DOWNLOAD_LINK_TTL_MINUTES * 60,
    )
    return f"{config.WEB_BASE_URL}/download/{token}"
