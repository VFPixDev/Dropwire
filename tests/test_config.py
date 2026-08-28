from src.config import Config


def test_ui_settings_are_not_loaded_from_environment(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "123:test")
    monkeypatch.setenv("REPLY_IN_GROUPS", "1")
    monkeypatch.setenv("REMOVE_MESSAGE_IN_GROUPS", "1")
    monkeypatch.setenv("REPLY_TO_MESSAGE", "0")
    monkeypatch.setenv("CAPTION_ABOVE_MEDIA", "0")
    monkeypatch.setenv("ENABLE_HASHTAGS", "0")
    monkeypatch.setenv("INCLUDE_SENDER_QUOTE", "0")
    monkeypatch.setenv("SENDER_QUOTE_MODE", "mention")

    parsed = Config.from_env()

    assert parsed.REPLY_IN_GROUPS is False
    assert parsed.REMOVE_MESSAGE_IN_GROUPS is False
    assert parsed.REPLY_TO_MESSAGE is True
    assert parsed.CAPTION_ABOVE_MEDIA is True
    assert parsed.ENABLE_HASHTAGS is True
    assert parsed.INCLUDE_SENDER_QUOTE is True
    assert parsed.SENDER_QUOTE_MODE == "name"
