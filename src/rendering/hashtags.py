import re
import unicodedata
from typing import Iterable, Optional


def normalize_hashtag(value: str) -> Optional[str]:
    cleaned = unicodedata.normalize("NFKC", value).strip().lower().lstrip("@#")
    cleaned = re.sub(r"[^\w]+", "_", cleaned, flags=re.UNICODE)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        return None
    if cleaned[0].isdigit():
        cleaned = f"u_{cleaned}"
    return f"#{cleaned}"


def build_hashtags(source: str, media_type: str, author: Optional[str] = None) -> list[str]:
    raw_tags = [source, media_type]
    if author:
        raw_tags.append(author)

    tags: list[str] = []
    seen: set[str] = set()
    for value in raw_tags:
        tag = normalize_hashtag(value)
        if tag and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tags


def render_hashtags(tags: Iterable[str]) -> str:
    unique_tags: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = normalize_hashtag(tag)
        if normalized and normalized not in seen:
            unique_tags.append(normalized)
            seen.add(normalized)
    return " ".join(unique_tags)
