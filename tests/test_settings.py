import asyncio
from types import SimpleNamespace

from src.services.database import Database
from src.services.settings import (
    GLOBAL_OWNER_ID,
    get_effective_settings,
    get_scope_settings,
    get_translation_language,
    is_admin,
    set_translation_language,
    toggle_bool_setting,
)
from src.services.providers import is_provider_enabled, toggle_provider


def test_group_settings_override_global_while_private_defaults_are_fixed(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.set_setting("global", GLOBAL_OWNER_ID, "enable_hashtags", "1")
            await database.set_setting("global", GLOBAL_OWNER_ID, "caption_above_media", "0")
            await database.set_setting("global", GLOBAL_OWNER_ID, "reply_to_message", "1")
            await database.set_setting("global", GLOBAL_OWNER_ID, "include_sender_quote", "1")
            await database.set_setting("group", -100, "enable_hashtags", "0")

            group_update = SimpleNamespace(
                effective_chat=SimpleNamespace(id=-100, type="supergroup"),
                effective_user=SimpleNamespace(id=42),
            )
            dm_update = SimpleNamespace(
                effective_chat=SimpleNamespace(id=42, type="private"),
                effective_user=SimpleNamespace(id=42),
            )

            group_settings = await get_effective_settings(database, group_update)
            dm_settings = await get_effective_settings(database, dm_update)

            assert group_settings.enable_hashtags is False
            assert dm_settings.enable_hashtags is False
            assert dm_settings.caption_above_media is True
            assert dm_settings.reply_to_message is False
            assert dm_settings.include_sender_quote is False
        finally:
            await database.close()

    asyncio.run(run())


def test_translation_prefers_group_then_user_scope(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await set_translation_language(database, "dm", 42, "en")
            await set_translation_language(database, "group", -100, "ru")

            group_update = SimpleNamespace(
                effective_chat=SimpleNamespace(id=-100, type="group"),
                effective_user=SimpleNamespace(id=42),
            )
            dm_update = SimpleNamespace(
                effective_chat=SimpleNamespace(id=42, type="private"),
                effective_user=SimpleNamespace(id=42),
            )

            assert await get_translation_language(database, group_update) == "ru"
            assert await get_translation_language(database, dm_update) == "en"
        finally:
            await database.close()

    asyncio.run(run())


def test_toggle_bool_setting_uses_merged_defaults(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.set_setting("global", GLOBAL_OWNER_ID, "reply_in_groups", "1")

            enabled = await toggle_bool_setting(database, "group", -100, "reply_in_groups")
            values = await get_scope_settings(database, "group", -100)

            assert enabled is False
            assert values["reply_in_groups"] == "0"
        finally:
            await database.close()

    asyncio.run(run())


def test_group_only_setting_cannot_be_toggled_in_dm(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            try:
                await toggle_bool_setting(database, "dm", 42, "reply_in_groups")
            except ValueError as exc:
                assert "not available for dm" in str(exc)
            else:
                raise AssertionError("reply_in_groups must not be configurable in DM scope")
        finally:
            await database.close()

    asyncio.run(run())


def test_groups_are_listed_only_for_linked_user(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.upsert_group(-100, "First", "supergroup")
            await database.upsert_group(-200, "Second", "supergroup")
            await database.link_user_group(42, -100)
            await database.link_user_group(7, -200)

            groups = await database.list_groups_for_user(42)

            assert [group["chat_id"] for group in groups] == [-100]
            assert await database.user_can_manage_group(42, -100) is True
            assert await database.user_can_manage_group(42, -200) is False
        finally:
            await database.close()

    asyncio.run(run())


def test_download_request_lifecycle(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            request_id = await database.create_download_request(42, "dQw4w9WgXcQ", -100, 55)
            assert await database.count_active_download_requests(42) == 1
            await database.update_download_request(request_id, status="queued", selected_quality="720")
            assert await database.count_active_download_requests(42) == 1
            request = await database.get_download_request(request_id)

            assert request is not None
            assert request["telegram_id"] == 42
            assert request["video_id"] == "dQw4w9WgXcQ"
            assert request["status"] == "queued"
            assert request["selected_quality"] == "720"

            await database.create_download(request_id, "/tmp/video.mp4", 123, "720p")
            await database.update_download_request(request_id, status="sent")
            assert await database.count_active_download_requests(42) == 0
        finally:
            await database.close()

    asyncio.run(run())


def test_download_request_can_only_be_claimed_once(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            request_id = await database.create_download_request(42, "dQw4w9WgXcQ", 42, 55)
            assert await database.claim_download_request(request_id, 42, "720") is True
            assert await database.claim_download_request(request_id, 42, "360") is False
            request = await database.get_download_request(request_id)
            assert request["status"] == "queued"
            assert request["selected_quality"] == "720"
        finally:
            await database.close()

    asyncio.run(run())


def test_download_reservation_is_atomic_for_duplicate_clicks(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            reservations = await asyncio.gather(
                database.reserve_download_request(42, "dQw4w9WgXcQ", 42, 1, 3),
                database.reserve_download_request(42, "dQw4w9WgXcQ", 42, 1, 3),
            )

            assert sum(request_id is not None for request_id, _ in reservations) == 1
            assert sorted(error for _, error in reservations if error) == ["duplicate"]
            assert await database.count_active_download_requests(42) == 1
        finally:
            await database.close()

    asyncio.run(run())


def test_interrupted_downloads_are_failed_on_startup(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            pending_id = await database.create_download_request(42, "dQw4w9WgXcQ", 42, 1)
            queued_id = await database.create_download_request(42, "9bZkp7q19f0", 42, 2, status="queued")
            sent_id = await database.create_download_request(42, "M7lc1UVf-VE", 42, 3, status="sent")

            assert await database.fail_interrupted_downloads() == 2
            assert (await database.get_download_request(pending_id))["status"] == "failed"
            assert (await database.get_download_request(queued_id))["status"] == "failed"
            assert (await database.get_download_request(sent_id))["status"] == "sent"
        finally:
            await database.close()

    asyncio.run(run())


def test_admin_access_requires_explicit_id(monkeypatch):
    monkeypatch.setattr("src.services.settings.config.BOT_ADMIN_IDS", [])
    assert is_admin(42) is False
    monkeypatch.setattr("src.services.settings.config.BOT_ADMIN_IDS", [42])
    assert is_admin(42) is True
    assert is_admin(7) is False


def test_provider_switches_are_global_and_default_to_enabled(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            assert await is_provider_enabled(database, "spotify") is True
            assert await toggle_provider(database, "spotify") is False
            assert await is_provider_enabled(database, "spotify") is False
        finally:
            await database.close()

    asyncio.run(run())


def test_media_cache_round_trip(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.upsert_cached_media(
                "https://pbs.twimg.com/media/example.jpg",
                "photo",
                "telegram-file-id",
                "unique-id",
                width=1200,
                height=800,
            )
            cached = await database.get_cached_media("https://pbs.twimg.com/media/example.jpg")
            assert cached is not None
            assert cached["file_id"] == "telegram-file-id"
            assert cached["width"] == 1200
        finally:
            await database.close()

    asyncio.run(run())


def test_delivery_lookup_returns_every_output_message(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.record_delivery_message(-100, 10, 42, 20)
            await database.record_delivery_message(-100, 10, 42, 21)
            delivery = await database.get_delivery_for_message(-100, 21)
            assert delivery is not None
            assert delivery["requester_user_id"] == 42
            assert delivery["message_ids"] == [20, 21]

            await database.delete_delivery(delivery["id"])
            assert await database.get_delivery_for_message(-100, 20) is None
        finally:
            await database.close()

    asyncio.run(run())


def test_delete_cached_media_removes_only_selected_urls(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.upsert_cached_media("https://pbs.twimg.com/media/one.jpg", "photo", "one")
            await database.upsert_cached_media("https://pbs.twimg.com/media/two.jpg", "photo", "two")
            await database.delete_cached_media(["https://pbs.twimg.com/media/one.jpg"])

            assert await database.get_cached_media("https://pbs.twimg.com/media/one.jpg") is None
            assert await database.get_cached_media("https://pbs.twimg.com/media/two.jpg") is not None
        finally:
            await database.close()

    asyncio.run(run())
