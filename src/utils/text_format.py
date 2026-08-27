import re
from datetime import datetime
from src.twitter.models import Poll, QuotedTweet, Tweet
from html import escape
from typing import Optional


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
    if include_translation and item.translated_text:
        return item.translated_text
    return item.text


def format_translation_attribution(tweet: Tweet) -> str:
    sources: list[str] = []
    for item in (tweet, tweet.quoted_tweet, tweet.parent_tweet):
        if item is None or not item.translated_text or not item.source_language:
            continue
        raw = item.source_language.strip()
        label = TRANSLATION_LANGUAGE_LABELS.get(raw.lower(), raw)
        if label not in sources:
            sources.append(label)
    if not sources:
        return ""
    return f"<i>Переведено с {escape(', '.join(sources))}</i>"


def has_tweet_translation(tweet: Tweet) -> bool:
    return any(item is not None and bool(item.translated_text) for item in (tweet, tweet.quoted_tweet, tweet.parent_tweet))


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
    lines = [f"<b>{escape(poll.question)}</b>\n"]

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


def format_tweet_card(tweet: Tweet, include_translation: bool = False, user_comment: Optional[str] = None) -> str:
    """Форматирует карточку твита"""
    date_str, time_str = format_date(tweet.date)

    def find_quoting_marker(text: str) -> tuple[int, int] | None:
        markers = ["quoting", "цитируя", "цитирует", "を引用"]
        lowered = text.lower()
        best_pos: Optional[int] = None
        best_len: Optional[int] = None
        for marker in markers:
            pos = lowered.find(marker)
            if pos >= 0 and (best_pos is None or pos < best_pos):
                best_pos = pos
                best_len = len(marker)
        if best_pos is None or best_len is None:
            return None
        return best_pos, best_len

    def extract_main_text(text: str) -> str:
        marker = find_quoting_marker(text)
        if marker:
            quoting_pos, _ = marker
            main = text[:quoting_pos].strip()
        else:
            main = text.strip()

        # Если в конце "главного текста" торчит строка с автором — убираем её
        if marker or tweet.quoted_tweet:
            normalized = re.sub(r"<br\s*/?>", "\n", main)
            lines = [line for line in normalized.split("\n") if line.strip() != ""]
            if lines and is_author_only_line(lines[-1].strip()):
                lines = lines[:-1]
            main = "\n".join(lines).strip()
        return main

    def extract_author_line_from_main(text: str) -> str:
        marker = find_quoting_marker(text)
        if not marker:
            return ""
        quoting_pos, _ = marker
        main = text[:quoting_pos].strip()
        normalized = re.sub(r"<br\s*/?>", "\n", main)
        lines = [line for line in normalized.split("\n") if line.strip() != ""]
        if lines and is_author_only_line(lines[-1].strip()):
            return lines[-1].strip()
        return ""

    def strip_quoting_markers(text: str) -> str:
        marker = find_quoting_marker(text)
        if marker:
            quoting_pos, _ = marker
            return text[:quoting_pos].strip()
        return text.strip()

    def is_author_only_line(text: str) -> bool:
        if not text:
            return False
        if f"@{tweet.username}" not in text:
            return False
        cleaned = text
        cleaned = cleaned.replace(tweet.display_name, "")
        cleaned = cleaned.replace(f"@{tweet.username}", "")
        cleaned = re.sub(r'[\s\(\)\[\]\{\}«»"\'“”‘’|｜—–\-·•:]', "", cleaned)
        return cleaned == ""

    lines = []
    # Первая строка: автор РЕТВИТА, username РЕТВИТА, дата
    lines.append(
        f'{escape(tweet.display_name)} (<a href="https://x.com/{escape(tweet.username)}">@{escape(tweet.username)}</a>) — {date_str}, {time_str}'
    )
    # Флаг: был ли текст основного твита
    has_main_text = False
    has_card_content = False

    source_text = translated_or_original_text(tweet, include_translation)
    if source_text:
        # Проверяем если есть "Quoting" - берём только текст ДО него
        text_to_display = extract_main_text(source_text)

        if text_to_display:  # Отправляем только если есть текст до Quoting
            has_quote_marker = find_quoting_marker(source_text) is not None
            if (tweet.quoted_tweet or has_quote_marker) and is_author_only_line(text_to_display):
                text_to_display = ""

            cleaned_text = clean_tweet_text(text_to_display)
            if cleaned_text.strip():
                lines.append("")
                lines.append(cleaned_text)
                has_main_text = True
                has_card_content = True

    # Quoted tweet - blockquote (содержит данные ОРИГИНАЛЬНОГО автора)
    if tweet.quoted_tweet:
        # Пустая строка перед цитатой ТОЛЬКО если был текст основного твита
        if has_main_text:
            lines.append("")
        elif not has_card_content:
            lines.append("")

        q = tweet.quoted_tweet
        q_date_str = ""
        if q.date:
            q_date, q_time = format_date(q.date)
            q_date_str = f" — {q_date}, {q_time}"

        # Blockquote для quoted с правильной ссылкой на профиль оригинального автора
        quoted_lines = []
        quoted_lines.append(
            f'{escape(q.display_name)} (<a href="https://x.com/{escape(q.username)}">@{escape(q.username)}</a>){q_date_str}'
        )

        # Quoted текст внутри blockquote - добавляем только если не пустой
        cleaned_q_text = clean_tweet_text(translated_or_original_text(q, include_translation))
        if cleaned_q_text.strip():  # Проверяем что текст не пустой
            quoted_lines.append(cleaned_q_text)

        quoted_content = "\n".join(quoted_lines)
        lines.append(f"<blockquote>{quoted_content}</blockquote>")
        has_card_content = True
    else:
        # Если нет quoted_tweet объекта, ищем Quoting/Цитируя в тексте и оформляем как blockquote
        marker = find_quoting_marker(source_text)
        if marker:
            # Пустая строка перед цитатой ТОЛЬКО если был текст основного твита
            if has_main_text:
                lines.append("")
            elif not has_card_content:
                lines.append("")

            # Находим позицию маркера и берём текст после него
            quoting_pos, marker_len = marker
            quoting_text = source_text[quoting_pos + marker_len :].strip()
            if quoting_text:
                # Если есть заголовок, оставляем его внутри цитаты
                raw_lines = quoting_text.split("\n")
                header = raw_lines[0].strip() if raw_lines else ""
                body = "\n".join(raw_lines[1:]).strip() if len(raw_lines) > 1 else ""
                if header:
                    cleaned_header = clean_tweet_text(header)
                    cleaned_body = clean_tweet_text(body)
                    quoted_parts = []
                    author_line = extract_author_line_from_main(source_text)
                    if author_line and not is_author_only_line(header):
                        quoted_parts.append(clean_tweet_text(author_line))
                        quoted_parts.append("")
                    quoted_parts.append(cleaned_header)
                    if cleaned_body.strip():
                        quoted_parts.append("")
                        quoted_parts.append(cleaned_body)
                    quoted_text = "\n".join(quoted_parts)
                    lines.append(f"<blockquote>{quoted_text}</blockquote>")
                    has_card_content = True
                else:
                    quoting_text = clean_tweet_text(quoting_text)
                    author_line = extract_author_line_from_main(source_text)
                    if author_line:
                        cleaned_author = clean_tweet_text(author_line)
                        lines.append(f"<blockquote>{cleaned_author}\n{quoting_text}</blockquote>")
                    else:
                        lines.append(f"<blockquote>{quoting_text}</blockquote>")
                    has_card_content = True

    if tweet.parent_tweet:
        lines.append("")
        parent = tweet.parent_tweet
        parent_lines = [
            f'↩️ В ответ на {escape(parent.display_name)} '
            f'(<a href="https://x.com/{escape(parent.username)}">@{escape(parent.username)}</a>)'
        ]
        cleaned_parent = clean_tweet_text(translated_or_original_text(parent, include_translation))
        if cleaned_parent.strip():
            parent_lines.append(cleaned_parent)
        parent_content = "\n".join(parent_lines)
        lines.append(f"<blockquote>{parent_content}</blockquote>")
        has_card_content = True

    if has_card_content:
        lines.append("")

    # Опрос (если есть) - ДО статистики
    if tweet.poll:
        if not has_card_content:
            lines.append("")
        lines.append(format_poll(tweet.poll))
        lines.append("")

    while lines and not lines[-1]:
        lines.pop()
    lines.append("")

    # Статистика
    stats = tweet.stats
    stats_parts = []

    if stats.replies is not None:
        stats_parts.append(f"💬 {format_number(stats.replies)}")
    else:
        stats_parts.append("💬 —")

    if stats.reposts is not None:
        stats_parts.append(f"🔁 {format_number(stats.reposts)}")
    else:
        stats_parts.append("🔁 —")

    if stats.likes is not None:
        stats_parts.append(f"❤️ {format_number(stats.likes)}")
    else:
        stats_parts.append("❤️ —")

    if stats.views is not None:
        stats_parts.append(f"👁 {format_number(stats.views)}")
    else:
        stats_parts.append("👁 —")

    lines.append("  ".join(stats_parts))

    return "\n".join(lines)


def shorten_text_for_caption(text: str, max_length: int = 1024) -> tuple[str, bool]:
    """Укорачивает текст для caption, возвращает (текст, был_обрезан)"""
    if len(text) <= max_length:
        return text, False

    # Обрезаем с многоточием
    return text[: max_length - 3] + "...", True
