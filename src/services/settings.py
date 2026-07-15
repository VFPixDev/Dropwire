from dataclasses import dataclass

from telegram import Update

from src.config import config
from src.services.database import Database
from src.twitter.translate import SUPPORTED_LANGUAGES

GLOBAL_OWNER_ID = 0
VALID_SCOPES = {"global", "group", "dm"}


BOOLEAN_SETTINGS = {
    "reply_in_groups": ("Ответы в группах", "REPLY_IN_GROUPS"),
    "remove_message_in_groups": ("Удалять исходное", "REMOVE_MESSAGE_IN_GROUPS"),
    "reply_to_message": ("Отвечать реплаем", "REPLY_TO_MESSAGE"),
    "caption_above_media": ("Подпись над медиа", "CAPTION_ABOVE_MEDIA"),
    "enable_hashtags": ("Хештеги", "ENABLE_HASHTAGS"),
    "include_sender_quote": ("Цитата отправителя", "INCLUDE_SENDER_QUOTE"),
}

SETTING_SCOPES = {
    "reply_in_groups": {"global", "group"},
    "remove_message_in_groups": {"global", "group"},
    "reply_to_message": {"global", "group", "dm"},
    "caption_above_media": {"global", "group", "dm"},
    "enable_hashtags": {"global", "group", "dm"},
    "include_sender_quote": {"global", "group", "dm"},
}

SENDER_QUOTE_MODES = {
    "name": "Имя",
    "username": "@username",
    "mention": "Mention с уведомлением",
}


@dataclass(frozen=True)
class EffectiveSettings:
    reply_in_groups: bool
    remove_message_in_groups: bool
    reply_to_message: bool
    caption_above_media: bool
    enable_hashtags: bool
    include_sender_quote: bool
    sender_quote_mode: str


def bool_to_db(value: bool) -> str:
    return "1" if value else "0"


def db_to_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def default_bool(name: str) -> bool:
    return bool(getattr(config, BOOLEAN_SETTINGS[name][1]))


def setting_names_for_scope(scope: str) -> list[str]:
    return [name for name in BOOLEAN_SETTINGS if scope in SETTING_SCOPES[name]]


def is_setting_allowed_for_scope(name: str, scope: str) -> bool:
    return name in SETTING_SCOPES and scope in SETTING_SCOPES[name]


async def get_effective_settings(database: Database | None, update: Update) -> EffectiveSettings:
    scope, owner_id = _scope_for_update(update)
    values = await _merged_settings(database, scope, owner_id)
    return EffectiveSettings(
        reply_in_groups=db_to_bool(values.get("reply_in_groups"), config.REPLY_IN_GROUPS),
        remove_message_in_groups=db_to_bool(values.get("remove_message_in_groups"), config.REMOVE_MESSAGE_IN_GROUPS),
        reply_to_message=db_to_bool(values.get("reply_to_message"), config.REPLY_TO_MESSAGE),
        caption_above_media=db_to_bool(values.get("caption_above_media"), config.CAPTION_ABOVE_MEDIA),
        enable_hashtags=db_to_bool(values.get("enable_hashtags"), config.ENABLE_HASHTAGS),
        include_sender_quote=db_to_bool(values.get("include_sender_quote"), config.INCLUDE_SENDER_QUOTE),
        sender_quote_mode=values.get("sender_quote_mode", config.SENDER_QUOTE_MODE),
    )


async def get_translation_language(database: Database | None, update: Update) -> str | None:
    user = update.effective_user
    chat = update.effective_chat
    if database is not None and chat is not None and chat.type in {"group", "supergroup"}:
        group_lang = await database.get_translation_language("group", chat.id)
        if group_lang in SUPPORTED_LANGUAGES:
            return group_lang
    if database is not None and user is not None:
        user_lang = await database.get_translation_language("dm", user.id)
        if user_lang in SUPPORTED_LANGUAGES:
            return user_lang
    if database is not None:
        global_lang = await database.get_translation_language("global", GLOBAL_OWNER_ID)
        if global_lang in SUPPORTED_LANGUAGES:
            return global_lang
    return None


async def set_translation_language(database: Database, scope: str, owner_id: int, language: str) -> None:
    _validate_scope_owner(scope, owner_id)
    if language != "off" and language not in SUPPORTED_LANGUAGES:
        raise ValueError(f"Unsupported language: {language}")
    await database.set_translation_language(scope, owner_id, language)


async def get_scope_settings(database: Database | None, scope: str, owner_id: int) -> dict[str, str]:
    _validate_scope_owner(scope, owner_id)
    return await _merged_settings(database, scope, owner_id)


async def toggle_bool_setting(database: Database, scope: str, owner_id: int, name: str) -> bool:
    _validate_scope_owner(scope, owner_id)
    if name not in BOOLEAN_SETTINGS:
        raise ValueError(f"Unknown boolean setting: {name}")
    if not is_setting_allowed_for_scope(name, scope):
        raise ValueError(f"Setting {name} is not available for {scope}")
    values = await _merged_settings(database, scope, owner_id)
    current = db_to_bool(values.get(name), default_bool(name))
    next_value = not current
    await database.set_setting(scope, owner_id, name, bool_to_db(next_value))
    return next_value


async def set_sender_quote_mode(database: Database, scope: str, owner_id: int, mode: str) -> None:
    _validate_scope_owner(scope, owner_id)
    if mode not in SENDER_QUOTE_MODES:
        raise ValueError(f"Unknown sender quote mode: {mode}")
    await database.set_setting(scope, owner_id, "sender_quote_mode", mode)


async def remember_group(database: Database | None, update: Update) -> None:
    chat = update.effective_chat
    if database is None or chat is None or chat.type not in {"group", "supergroup"}:
        return
    await database.upsert_group(chat.id, chat.title or str(chat.id), chat.type)


def is_admin(user_id: int) -> bool:
    return user_id in config.BOT_ADMIN_IDS


def is_user_allowed(user_id: int) -> bool:
    return config.TELEGRAM_USER_IDS is None or user_id in config.TELEGRAM_USER_IDS


async def _merged_settings(database: Database | None, scope: str, owner_id: int) -> dict[str, str]:
    values: dict[str, str] = {}
    if database is not None:
        values.update(await database.get_settings("global", GLOBAL_OWNER_ID))
        if scope != "global":
            values.update(await database.get_settings(scope, owner_id))
    return values


def _validate_scope_owner(scope: str, owner_id: int) -> None:
    if scope not in VALID_SCOPES:
        raise ValueError(f"Unknown settings scope: {scope}")
    if scope == "global" and owner_id != GLOBAL_OWNER_ID:
        raise ValueError("Global settings owner must be 0")
    if scope == "dm" and owner_id <= 0:
        raise ValueError("DM settings owner must be a Telegram user id")
    if scope == "group" and owner_id >= 0:
        raise ValueError("Group settings owner must be a Telegram chat id")


def _scope_for_update(update: Update) -> tuple[str, int]:
    chat = update.effective_chat
    user = update.effective_user
    if chat is not None and chat.type in {"group", "supergroup"}:
        return "group", chat.id
    if user is not None:
        return "dm", user.id
    return "global", GLOBAL_OWNER_ID
