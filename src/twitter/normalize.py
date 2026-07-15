import re
from typing import Optional


def extract_tweet_id(url: str) -> Optional[str]:
    """Извлекает ID твита из URL"""
    patterns = [
        r"(?:twitter|x)\.com/[\w]+/status/(\d+)",
        r"(?:fxtwitter|fixupx)\.com/[\w]+/status/(\d+)",
        r"/status/(\d+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def extract_username(url: str) -> Optional[str]:
    """Извлекает username из URL"""
    match = re.search(r"\.com/([\w]+)/status/", url)
    if match:
        return match.group(1)
    return None


def normalize_url(url: str) -> Optional[str]:
    """Нормализует URL твита в стандартный формат x.com"""
    tweet_id = extract_tweet_id(url)
    username = extract_username(url)

    if tweet_id and username:
        return f"https://x.com/{username}/status/{tweet_id}"
    return None


def find_tweet_urls(text: str) -> list[str]:
    """Находит все ссылки на твиты в тексте"""
    pattern = r"https?://(?:(?:twitter|x|fxtwitter|fixupx)\.com/[\w]+/status/\d+)"
    return re.findall(pattern, text)
