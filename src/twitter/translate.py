"""Translation languages and validation of upstream translation responses."""

from html import unescape
import re


def valid_translation(text: str | None) -> str | None:
    """Reject service notices returned as successful translations by FxTwitter."""
    if not isinstance(text, str) or not text.strip():
        return None
    normalized = re.sub(r"\s+", " ", unescape(text)).casefold().replace("’", "'")
    if "deepl" in normalized and any(
        marker in normalized
        for marker in (
            "older version of deepl",
            "old version of deepl",
            "update to the latest version",
            "старая версия deepl",
            "старую версию deepl",
            "обновите его до последней версии",
            "ancienne version de deepl",
            "alte version von deepl",
            "ältere version von deepl",
            "旧版本的 deepl",
            "deeplの古いバージョン",
            "versión antigua de deepl",
            "старою версією deepl",
            "versione precedente di deepl",
            "deepl'in eski bir sürümünü",
            "starszej wersji deepl",
            "versão mais antiga do deepl",
            "oudere versie van deepl",
            "deepl versi lama",
            "starší verzi deepl",
            "quota exceeded",
            "too many requests",
            "service unavailable",
            "authentication failed",
        )
    ):
        return None
    return text.strip()


# Поддерживаемые языки
SUPPORTED_LANGUAGES = {
    "ru": "Русский",
    "en": "English",
    "uk": "Українська",
    "es": "Español",
    "fr": "Français",
    "de": "Deutsch",
    "it": "Italiano",
    "pt": "Português",
    "ja": "日本語",
    "ko": "한국어",
    "zh": "中文",
    "ar": "العربية",
    "tr": "Türkçe",
    "pl": "Polski",
    "nl": "Nederlands",
}
