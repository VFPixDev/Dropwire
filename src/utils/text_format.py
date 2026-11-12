import re
from datetime import datetime
from src.twitter.models import Poll, QuotedTweet, Tweet
from src.twitter.translate import valid_translation
from html import escape


def normalize_line_indents(text: str) -> str:
    """Убирает ведущие пробелы/табуляции и пустые строки по краям"""
    text = text.replace("\u00a0", " ")
    lines = text.split("\n")
    lines = [re.sub(r"^[ \t]+", "", line) for line in lines]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def clean_tweet_text(text: str) -> str:
    """Очищает текст твита от HTML тегов и форматирует его"""
    if not text:
        return ""

    # Сначала убираем HTML теги типа <br>, <br/>
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = normalize_line_indents(text)

    # Теперь экранируем HTML символы
    text = escape(text)

    # Заменяем @mention на ссылку на профиль (после экранирования)
    def replace_mention(match):
        username = match.group(1)
        return f'<a href="https://x.com/{username}">@{username}</a>'

    text = re.sub(r"@([a-zA-Z0-9_]+)", replace_mention, text)

    return text


def format_number(num: int) -> str:
    """Форматирует число с разделителями"""
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M".replace(".0M", "M")
    elif num >= 1_000:
        return f"{num / 1_000:.1f}K".replace(".0K", "K")
    return str(num)


def format_date(dt: datetime) -> tuple[str, str]:
    """Форматирует дату в формат DD.MM.YYYY, HH:MM"""
    return dt.strftime("%d.%m.%Y"), dt.strftime("%H:%M")


TRANSLATION_LANGUAGE_LABELS = {
    "ar": "арабского",
    "zh": "китайского",
    "nl": "нидерландского",
    "en": "английского",
    "fr": "французского",
    "de": "немецкого",
    "it": "итальянского",
    "ja": "японского",
    "ko": "корейского",
    "pl": "польского",
    "pt": "португальского",
    "ru": "русского",
    "es": "испанского",
    "tr": "турецкого",
    "uk": "украинского",
    "arabic": "арабского",
    "chinese": "китайского",
    "dutch": "нидерландского",
    "english": "английского",
    "french": "французского",
    "german": "немецкого",
    "italian": "итальянского",
    "japanese": "японского",
    "korean": "корейского",
    "polish": "польского",
    "portuguese": "португальского",
    "spanish": "испанского",
    "turkish": "турецкого",
    "ukrainian": "украинского",
}


def translated_or_original_text(item: Tweet | QuotedTweet, include_translation: bool = True) -> str:
    translated = valid_translation(item.translated_text) if include_translation else None
    if translated:
        return translated
    return item.text


def format_translation_attribution(tweet: Tweet) -> str:
    sources: list[str] = []
    for item in (tweet, tweet.quoted_tweet, tweet.parent_tweet):
        if item is None or not valid_translation(item.translated_text) or not item.source_language:
            continue
        raw = item.source_language.strip()
        label = TRANSLATION_LANGUAGE_LABELS.get(raw.lower(), raw)
        if label not in sources:
            sources.append(label)
    if not sources:
        return ""
    return f"<i>Переведено с {escape(', '.join(sources))}</i>"


def has_tweet_translation(tweet: Tweet) -> bool:
    return any(
        item is not None and bool(valid_translation(item.translated_text))
        for item in (tweet, tweet.quoted_tweet, tweet.parent_tweet)
    )


def format_tweet_footer(tweet: Tweet, hashtags: str = "") -> str:
    parts = [part for part in (hashtags.strip(), format_translation_attribution(tweet)) if part]
    return " | ".join(parts)


def create_progress_bar(percent: float, length: int = 20) -> str:
    """Создаёт прогресс-бар из символов"""
    filled = int((percent / 100) * length)
    empty = length - filled
    return "█" * filled + "░" * empty


def format_poll(poll: Poll) -> str:
    """Форматирует опрос"""
    lines = [f"<b>{escape(poll.question)}</b>\n"] if poll.question else []

    for option in poll.options:
        bar = create_progress_bar(option.percent)
        votes_text = format_number(option.votes) if option.votes > 0 else ""

        # Форматируем как на скрине: название  процент%  прогресс-бар
        option_line = f"{escape(option.text)}  {option.percent:.0f}%  {bar}"
        if votes_text:
            option_line += f"  ({votes_text})"

        lines.append(f"<code>{option_line}</code>")

    # Итоговая информация
    total_text = format_number(poll.total_votes) if poll.total_votes > 0 else "0"

    if poll.is_ended:
        status = "завершён"
    elif poll.time_left:
        status = poll.time_left
    else:
        status = "идёт голосование"

    lines.append(f"\n{total_text} голосов · {status}")

    return "\n".join(lines)
