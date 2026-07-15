import time

import pytest

from src.services.download_token import TokenError, generate_download_token, verify_download_token
from src.web import app, download


def test_download_token_rejects_tampered_payload():
    token = generate_download_token("video.mp4", "secret", 60)
    payload, signature = token.split(".", maxsplit=1)

    with pytest.raises(TokenError):
        verify_download_token(f"{payload}x.{signature}", "secret")


def test_download_token_rejects_expired_link():
    token = generate_download_token("video.mp4", "secret", -1)
    time.sleep(0.01)

    with pytest.raises(TokenError):
        verify_download_token(token, "secret")


def test_path_prefix_bypass_shape_is_not_inside_download_dir(tmp_path):
    download_dir = (tmp_path / "downloads").resolve()
    sibling = (tmp_path / "downloads_evil" / "file.mp4").resolve()

    assert str(sibling).startswith(str(download_dir))
    with pytest.raises(ValueError):
        sibling.relative_to(download_dir)


@pytest.mark.parametrize("path", ["../secret.mp4", "/absolute.mp4", "folder\\file.mp4", "./file.mp4"])
def test_download_token_rejects_unsafe_paths(path):
    token = generate_download_token(path, "secret", 60)
    with pytest.raises(TokenError):
        verify_download_token(token, "secret")


def test_web_download_uses_native_mp4_content_type(tmp_path, monkeypatch):
    download_dir = tmp_path / "downloads"
    download_dir.mkdir()
    video = download_dir / "video.mp4"
    video.write_bytes(b"fake mp4")
    monkeypatch.setattr("src.web.config.DOWNLOAD_DIR", str(download_dir))
    monkeypatch.setattr("src.web.config.DOWNLOAD_TOKEN_SECRET", "test-secret")
    token = generate_download_token("video.mp4", "test-secret", 60)

    import asyncio

    response = asyncio.run(download(token))
    assert response.media_type == "video/mp4"
    assert response.headers["accept-ranges"] == "bytes"
    assert app.docs_url is None
