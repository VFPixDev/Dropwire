import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from src.twitter.normalize import TWITTER_HOSTS, extract_tweet_id, find_tweet_urls
from src.providers.youtube_urls import extract_video_id

SourceName = Literal["twitter", "youtube", "spotify", "soundcloud"]

SPOTIFY_HOSTS = {"open.spotify.com", "spotify.link"}
SOUNDCLOUD_HOSTS = {"soundcloud.com", "www.soundcloud.com", "m.soundcloud.com", "on.soundcloud.com", "snd.sc"}

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)


@dataclass(frozen=True)
class LinkMatch:
    source: SourceName
    url: str
    start: int


def detect_source(url: str) -> SourceName | None:
    if extract_video_id(url):
        return "youtube"
    try:
        parsed = urlparse(url)
        if parsed.username or parsed.password or parsed.port not in {None, 80, 443}:
            return None
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return None
    if host in TWITTER_HOSTS and extract_tweet_id(url):
        return "twitter"
    if host in SPOTIFY_HOSTS:
        return "spotify"
    if host in SOUNDCLOUD_HOSTS:
        return "soundcloud"
    return None


def find_supported_links(text: str) -> list[LinkMatch]:
    matches: list[LinkMatch] = []
    for match in URL_RE.finditer(text or ""):
        url = match.group(0).rstrip('.,;:!?)"]}')
        source = detect_source(url)
        if source:
            matches.append(LinkMatch(source=source, url=url, start=match.start()))

    # Keep compatibility with stricter Twitter extraction for unusual punctuation.
    found_urls = {item.url for item in matches}
    for tweet_url in find_tweet_urls(text or ""):
        if tweet_url not in found_urls:
            matches.append(LinkMatch(source="twitter", url=tweet_url, start=(text or "").find(tweet_url)))

    return _dedupe_links(sorted(matches, key=lambda item: item.start))


def _dedupe_links(matches: list[LinkMatch]) -> list[LinkMatch]:
    result: list[LinkMatch] = []
    seen: set[str] = set()
    for match in matches:
        key = _dedupe_key(match)
        if key in seen:
            continue
        seen.add(key)
        result.append(match)
    return result


def _dedupe_key(match: LinkMatch) -> str:
    if match.source == "twitter":
        tweet_id = extract_tweet_id(match.url)
        if tweet_id:
            return f"twitter:{tweet_id}"

    if match.source == "youtube":
        video_id = extract_video_id(match.url)
        if video_id:
            return f"youtube:{video_id}"

    parsed = urlparse(match.url)
    return f"{match.source}:{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"
