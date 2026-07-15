import json
import logging
from pathlib import Path
from typing import Optional

from src.config import config

logger = logging.getLogger(__name__)

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

# Обратный маппинг (название -> код)
LANGUAGE_NAME_TO_CODE = {v.lower(): k for k, v in SUPPORTED_LANGUAGES.items()}


class TranslateSettings:
    def __init__(self, storage_path: str | None = None, default_language: str = "off"):
        self.storage_path = Path(storage_path or config.TRANSLATE_SETTINGS_PATH)
        self.default_language = default_language if default_language in SUPPORTED_LANGUAGES else "off"
        self.settings = self._load()

    def _load(self) -> dict[str, str]:
        """Загружает настройки из файла."""
        if self.storage_path.exists():
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return {str(k): str(v) for k, v in data.items()}
            except Exception as exc:
                logger.warning("Не удалось загрузить настройки перевода: %s", exc)
        return {}

    def _save(self) -> None:
        """Атомарно сохраняет настройки в файл."""
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.settings, f, ensure_ascii=False, indent=2)
            tmp_path.replace(self.storage_path)
        except Exception as exc:
            logger.error("Ошибка сохранения настроек перевода: %s", exc)

    def get_language(self, user_id: int) -> Optional[str]:
        """Получает язык перевода для пользователя (2-буквенный код или None)."""
        lang = self.settings.get(str(user_id), self.default_language)
        if lang and lang != "off" and lang in SUPPORTED_LANGUAGES:
            return lang
        return None

    def set_language(self, user_id: int, language: str) -> None:
        """Устанавливает язык перевода для пользователя."""
        if language not in SUPPORTED_LANGUAGES:
            raise ValueError(f"Неподдерживаемый язык перевода: {language}")
        self.settings[str(user_id)] = language
        self._save()

    def disable(self, user_id: int) -> None:
        """Отключает перевод для пользователя."""
        self.settings[str(user_id)] = "off"
        self._save()


def parse_language_input(input_text: str) -> Optional[str]:
    """Преобразует ввод пользователя в 2-буквенный код языка."""
    input_lower = input_text.lower().strip()

    # Проверка на специальные команды
    if input_lower in ["off", "status", "list"]:
        return input_lower

    # Проверка прямого кода
    if input_lower in SUPPORTED_LANGUAGES:
        return input_lower

    # Проверка по названию
    if input_lower in LANGUAGE_NAME_TO_CODE:
        return LANGUAGE_NAME_TO_CODE[input_lower]

    # Частичное совпадение по названию
    for name, code in LANGUAGE_NAME_TO_CODE.items():
        if input_lower in name or name.startswith(input_lower):
            return code

    return None


def get_supported_languages_text() -> str:
    """Возвращает текст со списком поддерживаемых языков."""
    lines = ["<b>Поддерживаемые языки:</b>\n"]
    for code, name in sorted(SUPPORTED_LANGUAGES.items(), key=lambda x: x[1]):
        lines.append(f"• {name} (<code>{code}</code>)")
    return "\n".join(lines)


# Глобальный экземпляр
translate_settings = TranslateSettings(default_language=config.DEFAULT_TRANSLATE_LANG)
