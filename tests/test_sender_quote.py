from telegram import User

from src.utils.sender_quote import format_sender_quote


def test_sender_quote_name_without_comment():
    user = User(id=123, first_name="Ivan", last_name="Petrov", is_bot=False, username="ivan")
    assert format_sender_quote(user, None, "name") == "<blockquote>Ivan Petrov</blockquote>"


def test_sender_quote_username_with_comment():
    user = User(id=123, first_name="Ivan", is_bot=False, username="ivan")
    assert format_sender_quote(user, "look", "username") == "<blockquote>@ivan: look</blockquote>"


def test_sender_quote_mention_escapes_comment():
    user = User(id=123, first_name="Ivan", is_bot=False, username="ivan")
    assert format_sender_quote(user, "<tag>", "mention") == (
        '<blockquote><a href="tg://user?id=123">Ivan</a>: &lt;tag&gt;</blockquote>'
    )
