import asyncio
from datetime import datetime, timedelta, timezone
import gzip
import json
import logging
import os
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import EditMessageText, SendMessage

from src.config import Config, config
from src.handlers import inline
from src.handlers.callbacks import handle_youtube_quality_selected
from src.handlers.chat_members import handle_my_chat_member
from src.providers.http import ResponseTooLargeError, read_response_limited, request_provider
from src.providers.link_router import detect_source, find_supported_links
from src.providers.youtube_urls import extract_video_id
from src.services.database import Database
from src.services.download_queue import DownloadQueue
from src.services.media_cache import cache_tweet_media
from src.services.youtube_downloader import DownloadedFile, YtDlpDownloader
from src.twitter.models import MediaItem
from src.twitter.normalize import normalize_url
from src.twitter.parser_api import parse_tweet_api
from src.utils.logging_config import RedactingFormatter
from src.services.download_token import generate_download_token
from src.web import app


async def open_database(tmp_path):
    database = Database(str(tmp_path / "audit.sqlite3"))
    await database.connect()
    await database.init_schema()
    return database


def test_whitelist_does_not_grant_owner_rights(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("BOT_ADMIN_IDS", "")
    monkeypatch.setenv("TELEGRAM_USER_IDS", "42,43")
    parsed = Config.from_env()
    assert parsed.TELEGRAM_USER_IDS == [42, 43]
    assert parsed.BOT_ADMIN_IDS == []


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_non_finite_timeouts_are_rejected(monkeypatch, value):
    monkeypatch.setenv("TELEGRAM_READ_TIMEOUT", value)
    with pytest.raises(ValueError, match="конечным"):
        Config.from_env()


def test_unimplemented_webhook_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("MODE", "webhook")
    with pytest.raises(ValueError, match="polling"):
        Config.from_env()


@pytest.mark.parametrize(
    "old_status,new_status,is_adder",
    [("left", "member", True), ("member", "administrator", False), ("administrator", "member", False)],
)
def test_changing_bot_permissions_does_not_create_permanent_group_owner(tmp_path, old_status, new_status, is_adder):
    async def run():
        database = await open_database(tmp_path)
        try:
            event = SimpleNamespace(
                chat=SimpleNamespace(id=-100, title="Group", type="supergroup"),
                from_user=SimpleNamespace(id=42),
                old_chat_member=SimpleNamespace(status=old_status),
                new_chat_member=SimpleNamespace(status=new_status),
            )
            context = SimpleNamespace(application=SimpleNamespace(bot_data={"database": database}))
            await handle_my_chat_member(SimpleNamespace(my_chat_member=event), context)
            assert await database.user_can_manage_group(42, -100) is is_adder
        finally:
            await database.close()

    asyncio.run(run())


@pytest.mark.parametrize(
    "state,can_cancel",
    [("pending", True), ("queued", True), ("downloading", False), ("sent", False), ("ready", False), ("failed", False)],
)
def test_old_cancel_button_cannot_overwrite_active_or_terminal_download(tmp_path, state, can_cancel):
    async def run():
        database = await open_database(tmp_path)
        try:
            request_id = await database.create_download_request(42, "dQw4w9WgXcQ", 42, 1, status=state)
            assert await database.cancel_download_request(request_id, 42) is can_cancel
            assert not await database.start_download_request(request_id)
            assert (await database.get_download_request(request_id))["status"] == ("cancelled" if can_cancel else state)
        finally:
            await database.close()

    asyncio.run(run())


def test_abandoned_quality_selection_does_not_consume_download_limit_forever(tmp_path):
    async def run():
        database = await open_database(tmp_path)
        try:
            request_id = await database.create_download_request(42, "dQw4w9WgXcQ", 42, 1)
            old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
            await database.conn.execute(
                "UPDATE download_requests SET updated_at = ? WHERE id = ?", (old_time, request_id)
            )
            await database.conn.commit()
            reserved, error = await database.reserve_download_request(42, "dQw4w9WgXcQ", 42, 2, max_active=1)
            assert reserved is not None and error is None
            assert (await database.get_download_request(request_id))["status"] == "failed"
        finally:
            await database.close()

    asyncio.run(run())


def test_prepared_download_survives_failed_notification_and_deleted_progress(tmp_path, monkeypatch):
    async def run():
        database = await open_database(tmp_path)
        download_dir = tmp_path / "downloads"
        downloader = YtDlpDownloader(str(download_dir))
        output = download_dir / "video.mp4"
        output.write_bytes(b"video")
        monkeypatch.setattr(config, "DOWNLOAD_DIR", str(download_dir))
        monkeypatch.setattr(config, "WEB_BASE_URL", "https://download.example")
        downloader.get_duration_seconds = AsyncMock(return_value=30)
        downloader.download = AsyncMock(return_value=DownloadedFile(output, 5, "360p", [output]))
        downloader.cleanup = AsyncMock()
        queue = DownloadQueue(1)
        bot = SimpleNamespace(
            send_message=AsyncMock(side_effect=TelegramNetworkError(SendMessage(chat_id=42, text="link"), "timeout")),
            edit_message_text=AsyncMock(
                side_effect=TelegramBadRequest(
                    EditMessageText(chat_id=42, message_id=1, text="progress"), "message to edit not found"
                )
            ),
        )
        query = SimpleNamespace(
            message=SimpleNamespace(
                chat=SimpleNamespace(id=42, type="private"), message_id=1, edit_reply_markup=AsyncMock()
            ),
            answer=AsyncMock(),
        )
        context = SimpleNamespace(
            bot=bot,
            application=SimpleNamespace(
                bot_data={
                    "database": database,
                    "download_queue": queue,
                    "youtube_downloader": downloader,
                }
            ),
        )
        try:
            request_id = await database.create_download_request(42, "dQw4w9WgXcQ", 42, 1)
            await handle_youtube_quality_selected(query, context, 42, f"download:youtube:q:{request_id}:360")
            await queue.shutdown()
            assert output.exists()
            downloader.download.assert_awaited_once()
            downloader.cleanup.assert_not_awaited()
            assert len(await database.list_recent_downloads_for_user(42)) == 1
            assert (await database.get_download_request(request_id))["status"] == "ready"
        finally:
            await queue.shutdown()
            await database.close()

    asyncio.run(run())


def test_queue_has_a_global_bound_and_drains_active_jobs():
    async def run():
        queue = DownloadQueue(1, max_pending=1)
        release = asyncio.Event()
        started = asyncio.Event()

        async def active():
            started.set()
            await release.wait()

        first = (await queue.enqueue(active))[2]
        queued_job = AsyncMock()
        second = (await queue.enqueue(queued_job))[2]
        with pytest.raises(RuntimeError):
            await queue.enqueue(AsyncMock())
        await started.wait()
        shutdown = asyncio.create_task(queue.shutdown())
        await asyncio.sleep(0)
        assert not shutdown.done()
        release.set()
        await asyncio.wait_for(shutdown, 1)
        assert first.done() and second.cancelled()
        queued_job.assert_not_called()
        with pytest.raises(RuntimeError):
            await queue.enqueue(AsyncMock())

    asyncio.run(run())


def test_provider_stream_stops_before_unbounded_body_is_read():
    class Body(httpx.AsyncByteStream):
        chunks = 0

        async def __aiter__(self):
            for _ in range(100):
                self.chunks += 1
                yield b"x" * 1024

    async def run():
        body = Body()
        response = httpx.Response(200, stream=body, request=httpx.Request("GET", "https://provider.example"))
        with pytest.raises(ResponseTooLargeError):
            await read_response_limited(response, 1500)
        assert body.chunks == 2
        await response.aclose()

    asyncio.run(run())


def test_gzip_response_is_not_decoded_twice():
    async def run():
        raw = b'{"ok": true}'
        transport = httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-encoding": "gzip"}, content=gzip.compress(raw))
        )
        async with httpx.AsyncClient(transport=transport) as client:
            response = await request_provider(client, "https://provider.example")
            assert response.json() == {"ok": True}

    asyncio.run(run())


@pytest.mark.parametrize(
    "url",
    [
        "https://[broken",
        "https://www.www.youtube.com/watch?v=dQw4w9WgXcQ",
        "ftp://youtube.com/watch?v=dQw4w9WgXcQ",
        "https://user:secret@youtube.com/watch?v=dQw4w9WgXcQ",
    ],
)
def test_malformed_or_deceptive_links_are_rejected(url):
    assert detect_source(url) is None
    assert extract_video_id(url) is None
    assert find_supported_links(url) == []


def test_twitter_normalization_checks_host_and_supports_web_status():
    assert normalize_url("https://evilx.com/user/status/123") is None
    assert normalize_url("https://X.COM/i/web/status/123") == "https://x.com/i/status/123"
    assert len(find_supported_links("https://[broken https://X.COM/user/status/123")) == 1


def test_credentials_are_redacted_from_logs_and_tracebacks(monkeypatch):
    monkeypatch.setattr(config, "YOUTUBE_API_KEY", "private-api-key")
    monkeypatch.setattr(config, "BOT_TOKEN", "123:private-bot-token")
    try:
        raise ValueError(
            "https://api.example?key=private-api-key https://api.telegram.org/bot123:private-bot-token/getMe"
        )
    except ValueError:
        import sys

        record = logging.LogRecord("test", logging.ERROR, "", 1, "failed %s", ("private-api-key",), sys.exc_info())
    formatted = RedactingFormatter().format(record)
    assert "private-api-key" not in formatted
    assert "private-bot-token" not in formatted
    assert "ValueError" in formatted and "[REDACTED]" in formatted


def test_silent_h264_video_is_accepted_for_iphone(tmp_path, monkeypatch):
    payload = {
        "format": {"format_name": "mov,mp4"},
        "streams": [{"codec_type": "video", "codec_name": "h264", "pix_fmt": "yuv420p"}],
    }
    monkeypatch.setattr("src.services.youtube_downloader.shutil.which", lambda _: "ffprobe")
    monkeypatch.setattr(
        "src.services.youtube_downloader.subprocess.run",
        lambda *a, **k: SimpleNamespace(stdout=json.dumps(payload).encode()),
    )
    downloader = YtDlpDownloader(str(tmp_path))
    downloader._verify_iphone_media(tmp_path / "silent.mp4", audio_only=False)
    with pytest.raises(RuntimeError):
        downloader._verify_iphone_media(tmp_path / "silent.mp4", audio_only=True)


def test_parallel_cache_requests_upload_one_staging_message(tmp_path):
    async def run():
        database = await open_database(tmp_path)
        try:
            await database.set_setting("global", 0, "inline_cache_chat_id", "-100")
            bot = SimpleNamespace(
                send_photo=AsyncMock(
                    return_value=SimpleNamespace(
                        message_id=9,
                        photo=[SimpleNamespace(file_id="file", file_unique_id="unique", width=10, height=10)],
                    )
                ),
                delete_message=AsyncMock(),
            )
            item = MediaItem("photo", "https://pbs.twimg.com/media/photo.jpg")
            first, second = await asyncio.gather(
                cache_tweet_media(bot, database, [item]), cache_tweet_media(bot, database, [item])
            )
            assert first[0].file_id == second[0].file_id == "file"
            bot.send_photo.assert_awaited_once()
            bot.delete_message.assert_awaited_once()
        finally:
            await database.close()

    asyncio.run(run())


def test_background_inline_loads_keep_concurrency_bound_after_request_timeout(monkeypatch):
    async def run():
        active = 0
        maximum = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def fetch(*args):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            if active == 2:
                started.set()
            await release.wait()
            active -= 1
            return None

        monkeypatch.setattr(inline, "_inline_fetch_slots", asyncio.Semaphore(2))
        monkeypatch.setattr(inline, "fetch_complete_tweet", fetch)
        tasks = [
            asyncio.create_task(inline._fetch_tweet(f"https://x.com/user/status/{9000 + i}", None)) for i in range(8)
        ]
        await asyncio.wait_for(started.wait(), 1)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        assert maximum == 2
        release.set()
        await asyncio.gather(*tuple(inline._tweet_fetch_tasks.values()))
        assert maximum == 2

    asyncio.run(run())


def test_json_tweet_preserves_poll_choices():
    parsed = parse_tweet_api(
        {
            "tweet": {
                "author": {"screen_name": "author"},
                "text": "Choose",
                "poll": {
                    "choices": [{"label": "A", "count": 3}, {"label": "B", "count": 1}],
                    "total_votes": 4,
                    "ended": True,
                },
            }
        },
        "https://x.com/author/status/123",
    )
    assert parsed.poll is not None
    assert [option.percent for option in parsed.poll.options] == [75, 25]
    assert parsed.poll.is_ended


def test_cleanup_keeps_active_job_and_progress_finishes_before_result(tmp_path, monkeypatch):
    async def run():
        downloader = YtDlpDownloader(str(tmp_path / "downloads"))
        started = threading.Event()
        release_worker = threading.Event()
        release_progress = asyncio.Event()
        paths = []

        def worker(url, quality, directory, emit):
            source = directory / "source.mp4"
            source.write_bytes(b"video")
            paths.append(directory)
            os.utime(directory, (0, 0))
            started.set()
            release_worker.wait(2)
            emit("downloading", 100)
            return source

        async def progress(stage, percent):
            if percent == 100:
                await release_progress.wait()

        monkeypatch.setattr(downloader, "_download_sync", worker)
        task = asyncio.create_task(downloader.download("dQw4w9WgXcQ", "360", progress))
        assert await asyncio.to_thread(started.wait, 1)
        await downloader.cleanup_stale_files(300)
        assert paths[0].exists()
        release_worker.set()
        await asyncio.sleep(0.02)
        assert not task.done()
        release_progress.set()
        result = await asyncio.wait_for(task, 2)
        assert result.file_path.exists()
        assert not paths[0].exists()

    asyncio.run(run())


def test_cancelled_download_joins_worker_before_removing_files(tmp_path, monkeypatch):
    async def run():
        downloader = YtDlpDownloader(str(tmp_path / "downloads"))
        started = threading.Event()
        stopped = threading.Event()

        def worker(url, quality, directory, emit):
            started.set()
            try:
                while not stopped.wait(0.01):
                    emit("downloading", 1)
            finally:
                stopped.set()

        monkeypatch.setattr(downloader, "_download_sync", worker)
        task = asyncio.create_task(downloader.download("dQw4w9WgXcQ", "360", AsyncMock()))
        assert await asyncio.to_thread(started.wait, 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert stopped.is_set()
        assert list(downloader.base_download_dir.iterdir()) == []

    asyncio.run(run())


def test_web_download_supports_ranges_and_rejects_invalid_tokens(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOWNLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(config, "DOWNLOAD_TOKEN_SECRET", "audit-secret")
    (tmp_path / "video.mp4").write_bytes(b"0123456789")
    token = generate_download_token("video.mp4", "audit-secret", 60)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="https://test.example") as client:
            response = await client.get(f"/download/{token}", headers={"Range": "bytes=2-5"})
            assert response.status_code == 206
            assert response.content == b"2345"
            assert response.headers["content-range"] == "bytes 2-5/10"
            assert response.headers["cache-control"] == "private, no-store"
            invalid = await client.get("/download/invalid")
            assert invalid.status_code == 400
            expired = generate_download_token("video.mp4", "audit-secret", -1)
            assert (await client.get(f"/download/{expired}")).status_code == 400

    asyncio.run(run())
