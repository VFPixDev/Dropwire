from telegram import InlineQueryResultArticle, InlineQueryResultPhoto, User

from src.handlers.inline import _build_result, _prepend_sender_quote, _url_only_keyboard
from src.models.media_card import Button, MediaCard
from src.providers.link_router import LinkMatch
from src.services.settings import EffectiveSettings


def _settings(**overrides) -> EffectiveSettings:
    values = {
        "reply_in_groups": True,
        "remove_message_in_groups": False,
        "reply_to_message": False,
        "caption_above_media": True,
        "enable_hashtags": True,
        "include_sender_quote": True,
        "sender_quote_mode": "username",
    }
    values.update(overrides)
    return EffectiveSettings(**values)


def test_inline_photo_has_article_fallback_and_url_only_buttons():
    link = LinkMatch("youtube", "https://youtu.be/dQw4w9WgXcQ", 0)
    card = MediaCard(
        source="youtube",
        media_type="video",
        original_url=link.url,
        title="Video",
        thumbnail_url="https://example.com/thumb.jpg",
        buttons=[
            Button("Open", url=link.url),
            Button("Download", callback_data="download:youtube:dQw4w9WgXcQ"),
        ],
    )
    keyboard = _url_only_keyboard(card)

    built = _build_result(link, "Video", "YouTube", "Card", card.thumbnail_url, keyboard, _settings())

    assert isinstance(built.primary, InlineQueryResultPhoto)
    assert isinstance(built.fallback, InlineQueryResultArticle)
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].url == link.url
    assert len(keyboard.inline_keyboard) == 1


def test_long_inline_caption_uses_article():
    link = LinkMatch("spotify", "https://open.spotify.com/track/abc", 0)
    built = _build_result(
        link,
        "Track",
        "Spotify",
        "x" * 1025,
        "https://example.com/cover.jpg",
        None,
        _settings(),
    )

    assert isinstance(built.primary, InlineQueryResultArticle)
    assert built.primary is built.fallback


def test_inline_sender_quote_uses_personal_mode_and_comment():
    user = User(id=123, first_name="Alice", is_bot=False, username="alice")

    text = _prepend_sender_quote("Card", user, "look", _settings())

    assert text == "<blockquote>@alice: look</blockquote>\n\nCard"
