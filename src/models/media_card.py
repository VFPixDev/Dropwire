from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class CardStats:
    views: Optional[int] = None
    likes: Optional[int] = None
    replies: Optional[int] = None
    reposts: Optional[int] = None


@dataclass
class Button:
    text: str
    url: Optional[str] = None
    callback_data: Optional[str] = None


@dataclass
class MediaCard:
    source: str
    media_type: str
    original_url: str
    title: Optional[str] = None
    text: Optional[str] = None
    author_name: Optional[str] = None
    author_handle: Optional[str] = None
    author_url: Optional[str] = None
    published_at: Optional[datetime] = None
    thumbnail_url: Optional[str] = None
    duration_text: Optional[str] = None
    stats: CardStats = field(default_factory=CardStats)
    buttons: list[Button] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
