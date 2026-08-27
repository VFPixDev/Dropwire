import asyncio
from types import SimpleNamespace

from src.handlers.delete import _can_delete


class FakeBot:
    def __init__(self, status="member"):
        self.status = status
        self.calls = 0

    async def get_chat_member(self, chat_id, user_id):
        self.calls += 1
        return SimpleNamespace(status=self.status)


def test_original_requester_can_delete_without_admin_lookup(monkeypatch):
    monkeypatch.setattr("src.handlers.delete.is_admin", lambda user_id: False)
    bot = FakeBot()

    assert asyncio.run(_can_delete(bot, -100, 42, 42)) is True
    assert bot.calls == 0


def test_group_admin_can_delete_another_users_card(monkeypatch):
    monkeypatch.setattr("src.handlers.delete.is_admin", lambda user_id: False)
    bot = FakeBot(status="administrator")

    assert asyncio.run(_can_delete(bot, -100, 7, 42)) is True


def test_regular_group_member_cannot_delete_another_users_card(monkeypatch):
    monkeypatch.setattr("src.handlers.delete.is_admin", lambda user_id: False)
    bot = FakeBot(status="member")

    assert asyncio.run(_can_delete(bot, -100, 7, 42)) is False
