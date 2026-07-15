from html import escape

from telegram import User


def format_sender_quote(user: User, comment: str | None, mode: str) -> str:
    sender = format_sender(user, mode)
    cleaned_comment = (comment or "").strip()
    if cleaned_comment:
        return f"<blockquote>{sender}: {escape(cleaned_comment)}</blockquote>"
    return f"<blockquote>{sender}</blockquote>"


def format_sender(user: User, mode: str) -> str:
    if mode == "mention":
        return user.mention_html()
    if mode == "username" and user.username:
        return f"@{escape(user.username)}"
    return escape(user.full_name or user.username or str(user.id))
