import asyncio
from types import SimpleNamespace

from src.handlers.callbacks import _ensure_scope_write_allowed, _parse_quality_callback, _youtube_quality_keyboard
from src.handlers.callbacks import _manageable_groups_for_user, _user_can_manage_group
from src.services.database import Database
from src.services.youtube_downloader import FormatOption


class FakeBot:
    def __init__(self, statuses):
        self.statuses = statuses

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=self.statuses[(chat_id, user_id)])


def test_parse_quality_callback():
    assert _parse_quality_callback("download:youtube:q:12:720") == (12, "720")
    assert _parse_quality_callback("download:youtube:q:bad:720") is None
    assert _parse_quality_callback("download:youtube:q:12") is None


def test_youtube_quality_keyboard_uses_request_bound_callbacks():
    keyboard = _youtube_quality_keyboard([FormatOption("360", "360p"), FormatOption("audio", "audio")], 9)

    callbacks = [button.callback_data for row in keyboard.inline_keyboard for button in row]

    assert "download:youtube:q:9:360" in callbacks
    assert "download:youtube:q:9:audio" in callbacks
    assert "download:youtube:c:9" in callbacks


def test_group_management_allows_adder_or_telegram_admin(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.upsert_group(-100, "Added", "supergroup")
            await database.upsert_group(-200, "Admin", "supergroup")
            await database.upsert_group(-300, "Member", "supergroup")
            await database.link_user_group(42, -100)
            context = SimpleNamespace(
                bot=FakeBot(
                    {
                        (-200, 42): "administrator",
                        (-300, 42): "member",
                    }
                )
            )

            assert await _user_can_manage_group(context, database, 42, -100) is True
            assert await _user_can_manage_group(context, database, 42, -200) is True
            assert await _user_can_manage_group(context, database, 42, -300) is False

            groups = await _manageable_groups_for_user(context, database, 42)
            assert {group["chat_id"] for group in groups} == {-100, -200}
        finally:
            await database.close()

    asyncio.run(run())


def test_dm_settings_cannot_target_another_user(tmp_path):
    async def run():
        database = Database(str(tmp_path / "dropwire.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            answers = []

            class Query:
                message = SimpleNamespace(chat=SimpleNamespace(type="private", id=42))

                async def answer(self, text=None, show_alert=False):
                    answers.append((text, show_alert))

            context = SimpleNamespace(bot=FakeBot({}))
            allowed = await _ensure_scope_write_allowed(Query(), context, database, 42, "dm", 7)
            assert allowed is False
            assert "только себе" in answers[-1][0]
        finally:
            await database.close()

    asyncio.run(run())
