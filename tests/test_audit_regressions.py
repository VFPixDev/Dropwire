import asyncio
from contextlib import suppress
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.methods import SendRichMessage
from aiogram.types import BufferedInputFile, InputRichBlockPhoto, InputRichMessageContent

from src.handlers import messages
from src.handlers.inline import _build_inline_result
from src.rendering.twitter_rich import MEDIA_UNAVAILABLE, build_twitter_rich_message
from src.services.database import Database
from src.services.download_queue import DownloadQueue
from src.services.download_token import TokenError, verify_download_token
from src.services.settings import PRIVATE_SETTINGS, get_translation_language, set_translation_language
from src.twitter.loader import fetch_complete_tweet
from src.twitter.models import MediaItem, QuotedTweet, Tweet
from src.twitter.parser import parse_tweet_html
from src.twitter.parser_api import parse_tweet_api
from src.utils.text_format import format_tweet_footer, translated_or_original_text

DEEPL_ERROR = (
    "You're using an older version of DeepL. To continue using the app, please update to the latest version.\n\n"
    "Вы используете старую версию DeepL. Чтобы продолжить работу с приложением, обновите его до последней версии."
)
URL = "https://x.com/author/status/123"
PHOTO = "https://pbs.twimg.com/media/photo.jpg"


def tweet(**overrides):
    values = dict(display_name="Author", username="author", url=URL, text="Original post", date=datetime(2026, 11, 12))
    values.update(overrides)
    return Tweet(**values)


def plain(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(plain(item) for item in value)
    return plain(getattr(value, "text", ""))


def fixtures(bot=None):
    update = SimpleNamespace(
        effective_chat=SimpleNamespace(id=-100, type="supergroup"),
        effective_user=SimpleNamespace(id=42),
        message=SimpleNamespace(message_id=7, is_topic_message=True, message_thread_id=88, text=URL),
        get_bot=lambda: SimpleNamespace(username="dropwire_bot"),
    )
    update.message.chat = update.effective_chat
    context = SimpleNamespace(bot=bot or SimpleNamespace(), application=SimpleNamespace(bot_data={}))
    return update, context


@pytest.mark.parametrize("nested", [False, True])
def test_api_rejects_deepl_service_notice(nested):
    raw = {
        "author": {"name": "Author", "screen_name": "author"},
        "text": "Original post",
        "translation": {"text": DEEPL_ERROR, "source_lang": "en"},
    }
    data = {"tweet": raw}
    if nested:
        data = {"tweet": {"author": raw["author"], "text": "Outer", "quote": raw}}
    result = parse_tweet_api(data, URL)
    item = result.quoted_tweet if nested else result
    assert item.translated_text is None
    assert item.source_language is None
    assert item.text == "Original post"
    assert "Переведено" not in format_tweet_footer(result)


def test_html_service_notice_cannot_become_post_text():
    html = (
        f'<meta property="og:title" content="Author (@author)"><meta property="og:description" content="{DEEPL_ERROR}">'
    )
    assert parse_tweet_html(html, URL) is None


def test_renderer_defensively_preserves_original_and_omits_false_attribution():
    item = tweet(translated_text=DEEPL_ERROR, source_language="en")
    assert translated_or_original_text(item) == "Original post"
    assert format_tweet_footer(item) == ""
    item.translated_text = "Перевод"
    assert "английского" in format_tweet_footer(item)


def test_localization_exception_does_not_discard_original(monkeypatch):
    async def fetch_data(tweet_id, username, language):
        if language:
            raise ValueError("bad translation response")
        return {"tweet": {"author": {"screen_name": "author"}, "text": "Original post"}}

    monkeypatch.setattr("src.twitter.loader.fetch_tweet_data", fetch_data)
    result = asyncio.run(fetch_complete_tweet(URL, "123", "author", "ru"))
    assert result.text == "Original post"
    assert result.translated_text is None


def test_failed_video_preserves_other_media_and_quote_positions(monkeypatch):
    monkeypatch.setattr("src.rendering.twitter_rich.download_media", AsyncMock(return_value=None))
    item = tweet(
        media=[MediaItem("video", "https://video.twimg.com/failed.mp4"), MediaItem("photo", PHOTO)],
        quoted_tweet=QuotedTweet(
            "Quoted",
            "quoted",
            "https://x.com/quoted/status/1",
            "Quote",
            media=[MediaItem("photo", "https://pbs.twimg.com/media/quote.jpg")],
        ),
    )
    built = asyncio.run(build_twitter_rich_message(None, None, item))
    blocks = built.message.blocks
    assert isinstance(blocks[2], InputRichBlockPhoto)
    assert blocks[2].photo.media == PHOTO
    assert blocks[3].blocks[2].photo.media.endswith("/quote.jpg")
    assert any(plain(block) == MEDIA_UNAVAILABLE for block in blocks)


def test_untrusted_media_is_omitted_without_downloading(monkeypatch):
    download = AsyncMock()
    monkeypatch.setattr("src.rendering.twitter_rich.download_media", download)
    built = asyncio.run(
        build_twitter_rich_message(None, None, tweet(media=[MediaItem("video", "https://evil.example/v.mp4")]))
    )
    assert MEDIA_UNAVAILABLE in "".join(plain(block) for block in built.message.blocks)
    download.assert_not_called()


def test_rich_rejection_retries_uploaded_photo_without_legacy_album(monkeypatch):
    calls = []

    async def send(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TelegramBadRequest(SendRichMessage(chat_id=-100, rich_message=kwargs["rich_message"]), "bad media")
        return SimpleNamespace(message_id=10)

    monkeypatch.setattr("src.rendering.twitter_rich.download_media", AsyncMock(return_value=b"photo"))
    bot = SimpleNamespace(send_rich_message=send)
    update, context = fixtures(bot)
    asyncio.run(
        messages.send_tweet_card(
            update, context, tweet(media=[MediaItem("photo", PHOTO)]), 88, settings=PRIVATE_SETTINGS
        )
    )
    assert len(calls) == 2
    assert isinstance(calls[1]["rich_message"].blocks[2].photo.media, BufferedInputFile)
    assert all(call["message_thread_id"] == 88 for call in calls)
    assert all(call["reply_markup"].inline_keyboard[0][0].url == URL for call in calls)


def test_stale_cached_file_is_invalidated_before_upload_retry(tmp_path, monkeypatch):
    calls = []

    async def send(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            raise TelegramBadRequest(
                SendRichMessage(chat_id=-100, rich_message=kwargs["rich_message"]), "wrong file identifier"
            )
        return SimpleNamespace(message_id=10)

    monkeypatch.setattr("src.rendering.twitter_rich.download_media", AsyncMock(return_value=b"photo"))

    async def run():
        database = Database(str(tmp_path / "cache.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await database.upsert_cached_media(PHOTO, "photo", "expired-file-id")
            update, context = fixtures(SimpleNamespace(send_rich_message=send))
            context.application.bot_data["database"] = database
            await messages.send_tweet_card(
                update, context, tweet(media=[MediaItem("photo", PHOTO)]), 88, settings=PRIVATE_SETTINGS
            )
            assert calls[0]["rich_message"].blocks[2].photo.media == "expired-file-id"
            assert isinstance(calls[1]["rich_message"].blocks[2].photo.media, BufferedInputFile)
            assert await database.get_cached_media(PHOTO) is None
            assert await database.get_delivery_for_message(-100, 10) is not None
        finally:
            await database.close()

    asyncio.run(run())


def test_media_rejection_falls_back_to_rich_text_with_source_button(monkeypatch):
    calls = []

    async def send(**kwargs):
        calls.append(kwargs)
        if len(calls) < 3:
            raise TelegramBadRequest(SendRichMessage(chat_id=-100, rich_message=kwargs["rich_message"]), "bad media")
        return SimpleNamespace(message_id=10)

    monkeypatch.setattr("src.rendering.twitter_rich.download_media", AsyncMock(return_value=b"photo"))
    update, context = fixtures(SimpleNamespace(send_rich_message=send))
    asyncio.run(
        messages.send_tweet_card(
            update, context, tweet(media=[MediaItem("photo", PHOTO)]), 88, settings=PRIVATE_SETTINGS
        )
    )
    assert len(calls) == 3
    assert not any(isinstance(block, InputRichBlockPhoto) for block in calls[-1]["rich_message"].blocks)
    assert MEDIA_UNAVAILABLE in "".join(plain(block) for block in calls[-1]["rich_message"].blocks)
    assert calls[-1]["reply_markup"].inline_keyboard[0][0].url == URL


def test_unsupported_rich_server_sends_only_actionable_notice():
    async def send(**kwargs):
        raise TelegramBadRequest(SendRichMessage(chat_id=-100, rich_message=kwargs["rich_message"]), "unsupported")

    bot = SimpleNamespace(send_rich_message=send, send_message=AsyncMock(return_value=SimpleNamespace(message_id=10)))
    update, context = fixtures(bot)
    asyncio.run(messages.send_tweet_card(update, context, tweet(), 88, settings=PRIVATE_SETTINGS))
    call = bot.send_message.call_args.kwargs
    assert call["reply_markup"].inline_keyboard[0][0].url == URL
    assert call["message_thread_id"] == 88
    assert "Original post" not in call["text"]
    assert "👆" not in call["text"]


def test_ambiguous_network_delivery_is_not_retried():
    bot = SimpleNamespace(
        send_rich_message=AsyncMock(
            side_effect=TelegramNetworkError(SendRichMessage(chat_id=-100, rich_message={"blocks": []}), "timeout")
        )
    )
    update, context = fixtures(bot)
    assert asyncio.run(messages.send_tweet_card(update, context, tweet(), 88, settings=PRIVATE_SETTINGS)) is False
    assert bot.send_rich_message.await_count == 1


@pytest.mark.parametrize("media_type", ["photo", "video", "animation"])
def test_inline_without_cache_still_uses_rich_layout(monkeypatch, media_type):
    item = tweet(media=[MediaItem(media_type, PHOTO)])
    monkeypatch.setattr("src.handlers.inline._fetch_tweet", AsyncMock(return_value=item))
    from src.providers.link_router import LinkMatch

    update, _ = fixtures()
    built = asyncio.run(
        _build_inline_result(update, None, LinkMatch("twitter", URL, 0), PRIVATE_SETTINGS, update.effective_user, None)
    )
    assert isinstance(built.primary.input_message_content, InputRichMessageContent)
    assert MEDIA_UNAVAILABLE in built.primary.input_message_content.rich_message.html
    assert built.primary.reply_markup.inline_keyboard[0][0].url == URL
    assert "Original post" not in built.fallback.input_message_content.message_text


@pytest.mark.parametrize("scope,owner_id", [("group", -100), ("dm", 42)])
def test_translation_off_blocks_inherited_language(tmp_path, scope, owner_id):
    async def run():
        database = Database(str(tmp_path / "test.sqlite3"))
        await database.connect()
        await database.init_schema()
        try:
            await set_translation_language(database, "global", 0, "ru")
            await set_translation_language(database, scope, owner_id, "off")
            update, _ = fixtures()
            assert await get_translation_language(database, update) is None
            assert await database.get_translation_language(scope, owner_id) == "off"
        finally:
            await database.close()

    asyncio.run(run())


@pytest.mark.parametrize("cancel_waiting", [False, True])
def test_cancelled_queue_job_does_not_block_following_jobs(cancel_waiting):
    async def run():
        queue = DownloadQueue(1)
        release = asyncio.Event()
        started = asyncio.Event()
        first = (await queue.enqueue(release.wait))[2]
        second = (await queue.enqueue(release.wait))[2]
        cancelled = second if cancel_waiting else first
        cancelled.cancel()
        with suppress(asyncio.CancelledError):
            await cancelled
        third = (await queue.enqueue(lambda: mark_started(started)))[2]
        release.set()
        await asyncio.wait_for(started.wait(), 1)
        await asyncio.gather(first, second, third, return_exceptions=True)

    async def mark_started(started):
        started.set()

    asyncio.run(run())


def test_non_ascii_download_token_is_validation_error():
    with pytest.raises(TokenError):
        verify_download_token("тест.signature", "secret")


@pytest.mark.parametrize(
    "results,limit,delete", [([True, False], 8, False), ([True, True], 1, False), ([True, True], 8, True)]
)
def test_source_deleted_only_after_all_links_succeed(monkeypatch, results, limit, delete):
    from dataclasses import replace

    settings = replace(PRIVATE_SETTINGS, reply_in_groups=True, remove_message_in_groups=True)
    monkeypatch.setattr(messages, "get_effective_settings", AsyncMock(return_value=settings))
    monkeypatch.setattr(messages, "process_tweet_url", AsyncMock(side_effect=results))
    monkeypatch.setattr(messages.rate_limiter, "wait_until_allowed", AsyncMock(return_value=True))
    monkeypatch.setattr(messages.config, "MAX_LINKS_PER_MESSAGE", limit)
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)),
        delete_message=AsyncMock(),
        edit_message_text=AsyncMock(),
    )
    update, context = fixtures(bot)
    update.message.text = URL + " https://x.com/other/status/456"
    asyncio.run(messages.handle_message(update, context))
    deleted = [call.kwargs["message_id"] for call in bot.delete_message.call_args_list]
    assert (7 in deleted) is delete
    assert all(call.kwargs["message_thread_id"] == 88 for call in bot.send_message.call_args_list)


def test_caption_link_is_processed_and_mention_is_case_insensitive(monkeypatch):
    from dataclasses import replace

    settings = replace(PRIVATE_SETTINGS, reply_in_groups=False)
    monkeypatch.setattr(messages, "get_effective_settings", AsyncMock(return_value=settings))
    process = AsyncMock(return_value=True)
    monkeypatch.setattr(messages, "process_tweet_url", process)
    monkeypatch.setattr(messages.rate_limiter, "wait_until_allowed", AsyncMock(return_value=True))
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)), delete_message=AsyncMock()
    )
    update, context = fixtures(bot)
    update.message.text = None
    update.message.caption = "@DROPWIRE_BOT " + URL
    asyncio.run(messages.handle_message(update, context))
    process.assert_awaited_once()
    assert process.call_args.args[4] == ""


@pytest.mark.parametrize("attachment", ["photo", "video", "document", "animation", "audio"])
def test_caption_processing_never_deletes_user_attachment(monkeypatch, attachment):
    from dataclasses import replace

    settings = replace(PRIVATE_SETTINGS, reply_in_groups=True, remove_message_in_groups=True)
    monkeypatch.setattr(messages, "get_effective_settings", AsyncMock(return_value=settings))
    process = AsyncMock(return_value=True)
    monkeypatch.setattr(messages, "process_tweet_url", process)
    monkeypatch.setattr(messages.rate_limiter, "wait_until_allowed", AsyncMock(return_value=True))
    bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=99)), delete_message=AsyncMock()
    )
    update, context = fixtures(bot)
    update.message.text = None
    update.message.caption = URL
    setattr(update.message, attachment, SimpleNamespace(file_id="user-attachment"))

    asyncio.run(messages.handle_message(update, context))

    process.assert_awaited_once()
    deleted_ids = [call.kwargs["message_id"] for call in bot.delete_message.call_args_list]
    assert 7 not in deleted_ids
    assert 99 in deleted_ids
