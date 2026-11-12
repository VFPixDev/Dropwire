import re
from urllib.parse import urlparse

TWITTER_HOSTS = {
    f"{prefix}{host}"
    for prefix in ("", "www.")
    for host in ("x.com", "twitter.com", "fxtwitter.com", "fixupx.com", "vxtwitter.com")
}
STATUS_PATH = re.compile(r"/([A-Za-z0-9_]{1,15})/status/(\d+)(?:/.*)?$")
WEB_STATUS_PATH = re.compile(r"/i/web/status/(\d+)(?:/.*)?$")


def _tweet_parts(url: str) -> tuple[str, str] | None:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or parsed.hostname not in TWITTER_HOSTS:
            return None
        if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return None
    except ValueError:
        return None
    match = STATUS_PATH.fullmatch(parsed.path)
    if match:
        return match.group(1), match.group(2)
    match = WEB_STATUS_PATH.fullmatch(parsed.path)
    return ("i", match.group(1)) if match else None


def extract_tweet_id(url: str) -> str | None:
    parts = _tweet_parts(url)
    return parts[1] if parts else None


def extract_username(url: str) -> str | None:
    parts = _tweet_parts(url)
    return parts[0] if parts else None


def normalize_url(url: str) -> str | None:
    parts = _tweet_parts(url)
    return f"https://x.com/{parts[0]}/status/{parts[1]}" if parts else None


def find_tweet_urls(text: str) -> list[str]:
    urls = [match.group().rstrip('.,;:!?)"}]') for match in re.finditer(r"https?://[^\s<>()]+", text, re.IGNORECASE)]
    return [url for url in urls if _tweet_parts(url)]
