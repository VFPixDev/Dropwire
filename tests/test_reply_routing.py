import asyncio
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendPhoto

from src.handlers import messages
from src.models.media_card import Button, MediaCard
from src.services.database import Database
from src.services.settings import PRIVATE_SETTINGS
from src.twitter.models import Tweet


def make_update(chat_type="supergroup", target_id=101):
    chat = SimpleNamespace(id=-100 if chat_type != "private" else 42, type=chat_type, title="Group")
    source = SimpleNamespace(
        message_id=7,
        text="https://x.com/author/status/123",
        caption=None,
        chat=chat,
        is_topic_message=chat_type == "supergroup",
        message_thread_id=88 if chat_type == "supergroup" else None,
        reply_to_message=SimpleNamespace(message_id=target_id, chat=chat) if target_id is not None else None,
    )
    return SimpleNamespace(
        message=source,
        effective_chat=chat,
        effective_user=SimpleNamespace(id=42),
        get_bot=lambda: SimpleNamespace(username="dropwire_bot"),
    )


@pytest.mark.parametrize(
    "chat_type,enabled,target_id,expected",
    [
        ("group", True, 101, 101),
        ("supergroup", True, 101, 101),
        ("supergroup", True, None, 7),
        ("supergroup", True, 88, 7),
        ("supergroup", False, 101, None),
        ("private", True, 101, 7),
        ("private", False, 101, None),
    ],
)
def test_reply_routing_respects_group_settings_and_implicit_topic_roots(chat_type, enabled, target_id, expected):
    update = make_update(chat_type, target_id)
    settings = replace(PRIVATE_SETTINGS, reply_to_message=enabled)
    assert messages.get_reply_to_message_id(update, settings) == expected
    parameters = messages.get_reply_parameters(update, settings)
    if expected is None:
        assert parameters is None
    else:
        assert parameters.message_id == expected
        assert parameters.allow_sending_without_reply is True


@pytest.mark.parametrize("provider", ["twitter", "youtube", "spotify", "soundcloud", "photo-fallback"])
@pytest.mark.parametrize("remove_source", [True, False])
def test_group_card_replies_to_recipient_and_only_removes_link_sender_text(
    tmp_path, monkeypatch, provider, remove_source
):
    async def run():
        database = Database(str(tmp_path / "reply.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.set_setting("group", -100, "reply_in_groups", "1")
            await database.set_setting("group", -100, "reply_to_message", "1")
            await database.set_setting("group", -100, "remove_message_in_groups", "1" if remove_source else "0")
            await database.set_setting("group", -100, "include_sender_quote", "0")
            monkeypatch.setattr(messages.rate_limiter, "wait_until_allowed", AsyncMock(return_value=True))
            monkeypatch.setattr(messages, "check_whitelist", lambda _: True)
            urls = {
                "twitter": "https://x.com/author/status/123",
                "youtube": "https://youtu.be/dQw4w9WgXcQ",
                "spotify": "https://open.spotify.com/track/abc",
                "soundcloud": "https://soundcloud.com/artist/track",
                "photo-fallback": "https://open.spotify.com/track/abc",
            }
            update = make_update()
            update.message.text = urls[provider]
            if provider == "twitter":
                tweet = Tweet("Author", "author", urls[provider], "Post", datetime(2026, 11, 13))
                monkeypatch.setattr(messages, "fetch_complete_tweet", AsyncMock(return_value=tweet))
            else:
                source = "spotify" if provider == "photo-fallback" else provider
                card = MediaCard(
                    source,
                    "video" if source == "youtube" else "music",
                    urls[provider],
                    title="Post",
                    thumbnail_url="https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
                    buttons=[Button("Open", url=urls[provider])],
                )
                monkeypatch.setattr(messages, f"fetch_{source}_card", AsyncMock(return_value=card))

            events = []
            sent_cards = []

            async def send_message(**kwargs):
                if kwargs["text"].startswith("⏳"):
                    return SimpleNamespace(message_id=901)
                sent_cards.append(kwargs)
                events.append("card")
                return SimpleNamespace(message_id=900)

            async def send_card(**kwargs):
                if provider == "photo-fallback":
                    raise TelegramBadRequest(SendPhoto(chat_id=-100, photo="file"), "photo rejected")
                sent_cards.append(kwargs)
                events.append("card")
                return SimpleNamespace(message_id=900)

            async def delete_message(chat_id, message_id):
                events.append(message_id)

            bot = SimpleNamespace(
                send_message=send_message,
                send_rich_message=send_card,
                send_photo=send_card,
                delete_message=delete_message,
            )
            context = SimpleNamespace(bot=bot, application=SimpleNamespace(bot_data={"database": database}))

            await messages.handle_message(update, context)

            assert len(sent_cards) == 1
            assert sent_cards[0]["reply_parameters"].message_id == 101
            assert sent_cards[0]["message_thread_id"] == 88
            assert sent_cards[0]["reply_parameters"].allow_sending_without_reply is True
            assert (7 in events) is remove_source
            assert 101 not in events
            assert 901 in events
            if remove_source:
                assert events.index("card") < events.index(7)
            delivery = await database.get_delivery_for_message(-100, 900)
            assert delivery["source_message_id"] == 7
            assert delivery["requester_user_id"] == 42
        finally:
            await database.close()

    asyncio.run(run())
