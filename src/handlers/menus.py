"""Inline menus for Dropwire."""

from html import escape

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from src.config import config
from src.services.settings import (
    BOOLEAN_SETTINGS,
    SENDER_QUOTE_MODES,
    db_to_bool,
    default_bool,
    setting_names_for_scope,
)
from src.twitter.translate import SUPPORTED_LANGUAGES
from src.services.providers import PROVIDERS

LANGUAGE_FLAGS = {
    "ru": "🇷🇺",
    "en": "🇬🇧",
    "uk": "🇺🇦",
    "es": "🇪🇸",
    "fr": "🇫🇷",
    "de": "🇩🇪",
    "it": "🇮🇹",
    "pt": "🇵🇹",
    "ja": "🇯🇵",
    "ko": "🇰🇷",
    "zh": "🇨🇳",
    "ar": "🇸🇦",
    "tr": "🇹🇷",
    "pl": "🇵🇱",
    "nl": "🇳🇱",
}

CALLBACK_MAIN_MENU = "main_menu"
CALLBACK_HELP = "help"
CALLBACK_SETTINGS = "settings"
CALLBACK_TRANSLATE = "translate"
CALLBACK_DOWNLOADS = "downloads"
CALLBACK_ADMIN = "admin"
CB_ADMIN_PROVIDER = "admin:provider:"

CB_SETTINGS_GLOBAL = "st:global"
CB_SETTINGS_DM = "st:dm"
CB_SETTINGS_GROUPS = "st:groups"
CB_SETTINGS_GROUP = "st:group:"
CB_SETTINGS_TOGGLE = "st:tog:"
CB_SETTINGS_SENDER = "st:sender:"
CB_SETTINGS_SENDER_SET = "st:sender_set:"
CB_SETTINGS_RESET = "st:reset:"

CB_TRANSLATE_USER = "tr:user"
CB_TRANSLATE_GROUP = "tr:group"
CB_TRANSLATE_SET = "tr:set:"


def get_main_menu_text() -> str:
    return f"""<b>👋 Привет! Я {config.APP_NAME}.</b>

Отправьте ссылку из Twitter/X, YouTube, Spotify или SoundCloud, и я оформлю ее в удобную карточку.

Настройки разделены на:
• Глобальные
• Групповые
• Личные

Выберите действие:"""


def get_main_menu_keyboard(is_private: bool = True, is_admin: bool = False) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("⚙️ Настройки", callback_data=CALLBACK_SETTINGS),
            InlineKeyboardButton("🌐 Перевод", callback_data=CALLBACK_TRANSLATE),
        ],
    ]
    if is_private:
        rows.append([InlineKeyboardButton("📥 Мои загрузки", callback_data=CALLBACK_DOWNLOADS)])
        if is_admin:
            rows.append([InlineKeyboardButton("🛡 Управление ботом", callback_data=CALLBACK_ADMIN)])
    rows.append([InlineKeyboardButton("❓ Помощь", callback_data=CALLBACK_HELP)])
    return InlineKeyboardMarkup(rows)


def get_help_text() -> str:
    return f"""<b>📖 Справка по {config.APP_NAME}</b>

<b>Поддерживаемые ссылки:</b>
• https://x.com/username/status/123
• https://twitter.com/username/status/123
• https://youtu.be/VIDEO_ID
• https://youtube.com/watch?v=VIDEO_ID
• https://open.spotify.com/track/ID
• https://soundcloud.com/artist/track

<b>Inline-режим:</b>
Введите в любом чате <code>@dropwire_bot ссылка</code>, выберите результат, и карточка появится в этом чате.
Применяются личные и глобальные настройки; настройки конкретной группы Telegram не передаёт.

<b>Настройки:</b>
• Глобальные — базовое поведение всего бота
• Групповые — выбираются и меняются только в ЛС с ботом
• Личные — применяются в ЛС
• В группе можно менять только перевод: для себя или для группы

<b>Команды:</b>
/start — главное меню
/settings — настройки
/downloads — доступные загрузки
/status — состояние бота"""


def get_help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_MAIN_MENU)]])


def get_settings_hub_text(is_private: bool, is_admin: bool) -> str:
    if is_private:
        global_line = "✅ доступно" if is_admin else "🔒 только админ"
        return f"""<b>⚙️ Настройки {config.APP_NAME}</b>

<b>Глобальные:</b> {global_line}
<b>Групповые:</b> выбираются здесь, в ЛС
<b>Личные:</b> только для этого чата с ботом

Выберите раздел:"""

    return """<b>⚙️ Настройки группы</b>

В группе доступна только настройка перевода.
Все остальные групповые настройки меняются в ЛС с ботом."""


def get_settings_hub_keyboard(is_private: bool, is_admin: bool, has_group: bool = False) -> InlineKeyboardMarkup:
    if not is_private:
        rows = [[InlineKeyboardButton("🌐 Перевод", callback_data=CALLBACK_TRANSLATE)]]
        rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_MAIN_MENU)])
        return InlineKeyboardMarkup(rows)

    rows = []
    if is_admin:
        rows.append([InlineKeyboardButton("🌍 Глобальные", callback_data=CB_SETTINGS_GLOBAL)])
    rows.append([InlineKeyboardButton("👤 ЛС", callback_data=CB_SETTINGS_DM)])
    rows.append([InlineKeyboardButton("👥 Группы", callback_data=CB_SETTINGS_GROUPS)])
    rows.append([InlineKeyboardButton("🌐 Перевод", callback_data=CALLBACK_TRANSLATE)])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_MAIN_MENU)])
    return InlineKeyboardMarkup(rows)


def get_scope_settings_text(
    scope: str, scope_title: str, values: dict[str, str], translation: str | None = None
) -> str:
    lines = [f"<b>⚙️ {escape(scope_title)}</b>", ""]
    for name in setting_names_for_scope(scope):
        label = BOOLEAN_SETTINGS[name][0]
        value = db_to_bool(values.get(name), default_bool(name))
        lines.append(f"• {label}: {'✅' if value else '❌'}")

    mode = values.get("sender_quote_mode", config.SENDER_QUOTE_MODE)
    lines.append(f"• Отправитель в цитате: {SENDER_QUOTE_MODES.get(mode, mode)}")

    if translation:
        lines.append(f"• Перевод: {SUPPORTED_LANGUAGES.get(translation, translation)}")
    else:
        lines.append("• Перевод: ❌")
    return "\n".join(lines)


def get_scope_settings_keyboard(scope: str, owner_id: int) -> InlineKeyboardMarkup:
    rows = []
    for name in setting_names_for_scope(scope):
        label = BOOLEAN_SETTINGS[name][0]
        rows.append(
            [
                InlineKeyboardButton(
                    f"Переключить: {label}", callback_data=f"{CB_SETTINGS_TOGGLE}{scope}:{owner_id}:{name}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("Отправитель в цитате", callback_data=f"{CB_SETTINGS_SENDER}{scope}:{owner_id}")])
    rows.append([InlineKeyboardButton("🌐 Перевод", callback_data=f"{CB_TRANSLATE_SET}{scope}:{owner_id}:menu")])
    if scope in {"dm", "group"}:
        rows.append(
            [InlineKeyboardButton("↩️ Сбросить к глобальным", callback_data=f"{CB_SETTINGS_RESET}{scope}:{owner_id}")]
        )
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_SETTINGS)])
    return InlineKeyboardMarkup(rows)


def get_sender_mode_keyboard(scope: str, owner_id: int, current: str) -> InlineKeyboardMarkup:
    rows = []
    for mode, label in SENDER_QUOTE_MODES.items():
        prefix = "✅ " if mode == current else ""
        rows.append(
            [
                InlineKeyboardButton(
                    f"{prefix}{label}", callback_data=f"{CB_SETTINGS_SENDER_SET}{scope}:{owner_id}:{mode}"
                )
            ]
        )
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=_scope_callback(scope, owner_id))])
    return InlineKeyboardMarkup(rows)


def get_groups_text(groups_count: int, page: int = 0, total_pages: int = 1) -> str:
    if groups_count == 0:
        return "<b>👥 Группы</b>\n\nЗдесь появятся группы, куда вы добавили бота или где являетесь администратором."
    page_text = f"\n\nСтраница {page + 1} из {total_pages}." if total_pages > 1 else ""
    return f"<b>👥 Группы</b>\n\nВыберите группу, которой вы управляете:{page_text}"


def get_groups_keyboard(groups, page: int = 0, page_size: int = 10) -> InlineKeyboardMarkup:
    rows = []
    total_pages = max((len(groups) + page_size - 1) // page_size, 1)
    safe_page = min(max(page, 0), total_pages - 1)
    start = safe_page * page_size
    for group in groups[start : start + page_size]:
        title = str(group["title"])
        rows.append([InlineKeyboardButton(title[:60], callback_data=f"{CB_SETTINGS_GROUP}{group['chat_id']}")])
    navigation = []
    if safe_page > 0:
        navigation.append(InlineKeyboardButton("⬅️", callback_data=f"{CB_SETTINGS_GROUPS}:{safe_page - 1}"))
    if safe_page + 1 < total_pages:
        navigation.append(InlineKeyboardButton("➡️", callback_data=f"{CB_SETTINGS_GROUPS}:{safe_page + 1}"))
    if navigation:
        rows.append(navigation)
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_SETTINGS)])
    return InlineKeyboardMarkup(rows)


def get_translate_scope_text(is_group: bool) -> str:
    if is_group:
        return """<b>🌐 Перевод</b>

Выберите, куда применить перевод:
• Себе — только для ваших ссылок/ЛС
• Группе — для всех ссылок в этой группе"""
    return "<b>🌐 Перевод</b>\n\nВ ЛС перевод настраивается для вас. Группы выбираются в разделе настроек групп."


def get_translate_scope_keyboard(is_group: bool) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton("👤 Себе", callback_data=CB_TRANSLATE_USER)]]
    if is_group:
        rows.append([InlineKeyboardButton("👥 Группе", callback_data=CB_TRANSLATE_GROUP)])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_SETTINGS)])
    return InlineKeyboardMarkup(rows)


def get_translate_language_text(scope_title: str, current_lang: str | None = None) -> str:
    current = SUPPORTED_LANGUAGES.get(current_lang, current_lang) if current_lang else "выключен"
    return f"<b>🌐 Перевод: {scope_title}</b>\n\nТекущий режим: {current}\n\nВыберите язык:"


def get_translate_language_keyboard(
    scope: str,
    owner_id: int,
    current_lang: str | None = None,
    back_callback: str | None = None,
) -> InlineKeyboardMarkup:
    priority_langs = ["ru", "en", "uk", "es", "de", "fr"]
    rows = []
    for i in range(0, len(priority_langs), 2):
        row = []
        for code in priority_langs[i : i + 2]:
            flag = LANGUAGE_FLAGS.get(code, "")
            prefix = "✅ " if code == current_lang else ""
            row.append(
                InlineKeyboardButton(
                    f"{prefix}{flag} {SUPPORTED_LANGUAGES[code]}",
                    callback_data=f"{CB_TRANSLATE_SET}{scope}:{owner_id}:{code}",
                )
            )
        rows.append(row)
    rows.append([InlineKeyboardButton("❌ Выключить", callback_data=f"{CB_TRANSLATE_SET}{scope}:{owner_id}:off")])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=back_callback or _scope_callback(scope, owner_id))])
    return InlineKeyboardMarkup(rows)


def _scope_callback(scope: str, owner_id: int) -> str:
    if scope == "global":
        return CB_SETTINGS_GLOBAL
    if scope == "dm":
        return CB_SETTINGS_DM
    if scope == "group":
        return f"{CB_SETTINGS_GROUP}{owner_id}"
    return CALLBACK_SETTINGS


def get_downloads_text(total: int, available: int) -> str:
    if total == 0:
        return (
            "<b>📥 Мои загрузки</b>\n\nГотовых файлов пока нет. Скачивание запускается кнопкой под карточкой YouTube."
        )
    return (
        "<b>📥 Мои загрузки</b>\n\n"
        f"Последних записей: {total}\n"
        f"Файлов ещё доступно: {available}\n\n"
        f"Новая ссылка действует {config.DOWNLOAD_LINK_TTL_MINUTES} минут."
    )


def get_downloads_keyboard(items: list[dict[str, str]]) -> InlineKeyboardMarkup:
    rows = []
    for item in items:
        rows.append([InlineKeyboardButton(item["label"][:64], url=item["url"])])
    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data=CALLBACK_DOWNLOADS)])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_MAIN_MENU)])
    return InlineKeyboardMarkup(rows)


def get_admin_text(stats: dict[str, int], provider_states: dict[str, tuple[bool, str]]) -> str:
    lines = [
        f"<b>🛡 Управление {escape(config.APP_NAME)}</b>",
        "",
        f"• Пользователи: {stats.get('users', 0)}",
        f"• Группы: {stats.get('groups', 0)}",
        f"• Готовые загрузки: {stats.get('downloads', 0)}",
        f"• Активные загрузки: {stats.get('active_downloads', 0)}",
        "",
        "<b>Источники:</b>",
    ]
    for source, label in PROVIDERS.items():
        enabled, capability = provider_states[source]
        lines.append(f"• {label}: {'✅' if enabled else '❌'} · {escape(capability)}")
    lines.append("")
    lines.append(f"• Web-загрузки: {'✅' if config.WEB_BASE_URL else '❌ WEB_BASE_URL не задан'}")
    return "\n".join(lines)


def get_admin_keyboard(provider_states: dict[str, tuple[bool, str]]) -> InlineKeyboardMarkup:
    rows = []
    for source, label in PROVIDERS.items():
        enabled = provider_states[source][0]
        rows.append(
            [InlineKeyboardButton(f"{'✅' if enabled else '❌'} {label}", callback_data=f"{CB_ADMIN_PROVIDER}{source}")]
        )
    rows.append([InlineKeyboardButton("🔄 Обновить", callback_data=CALLBACK_ADMIN)])
    rows.append([InlineKeyboardButton("⬅️ Назад", callback_data=CALLBACK_MAIN_MENU)])
    return InlineKeyboardMarkup(rows)
