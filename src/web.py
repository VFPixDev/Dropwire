from pathlib import Path
import mimetypes

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse

from src.config import config
from src.services.download_token import TokenError, verify_download_token

app = FastAPI(title="Dropwire Downloader", docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
    return response


@app.get("/")
async def index() -> dict[str, str]:
    return {"service": "dropwire-web", "status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/download/{token}")
async def download(token: str):
    secret = config.DOWNLOAD_TOKEN_SECRET or config.BOT_TOKEN
    try:
        payload = verify_download_token(token, secret)
    except TokenError as exc:
        return HTMLResponse(
            content=(f"<h2>Link is invalid</h2><p>{str(exc)}</p><p>Return to Telegram and request a fresh link.</p>"),
            status_code=400,
        )

    relative_path = str(payload["p"])
    download_dir = Path(config.DOWNLOAD_DIR).resolve()
    file_path = (download_dir / relative_path).resolve()

    try:
        file_path.relative_to(download_dir)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid file path") from exc

    if not file_path.exists() or not file_path.is_file():
        return HTMLResponse(
            content=(
                "<h2>File unavailable</h2>"
                "<p>The file was deleted or the storage window has expired.</p>"
                "<p>Request a fresh link in Telegram.</p>"
            ),
            status_code=404,
        )

    media_type = (
        {
            ".mp4": "video/mp4",
            ".m4a": "audio/mp4",
        }.get(file_path.suffix.lower())
        or mimetypes.guess_type(file_path.name)[0]
        or "application/octet-stream"
    )
    return FileResponse(
        path=file_path,
        filename=file_path.name,
        media_type=media_type,
        headers={"Accept-Ranges": "bytes"},
    )
