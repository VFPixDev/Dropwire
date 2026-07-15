from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PollOption:
    text: str
    votes: int = 0
    percent: float = 0.0


@dataclass
class Poll:
    question: str
    options: list[PollOption]
    total_votes: int = 0
    is_ended: bool = False
    time_left: Optional[str] = None


@dataclass
class TweetStats:
    replies: Optional[int] = None
    reposts: Optional[int] = None
    likes: Optional[int] = None
    views: Optional[int] = None


@dataclass
class MediaItem:
    type: str  # 'photo' или 'video'
    url: str
    thumbnail_url: Optional[str] = None


@dataclass
class QuotedTweet:
    display_name: str
    username: str
    url: str
    text: str
    date: Optional[datetime] = None
    media: list[MediaItem] = field(default_factory=list)


@dataclass
class Tweet:
    display_name: str
    username: str
    url: str
    text: str
    date: datetime
    media: list[MediaItem] = field(default_factory=list)
    quoted_tweet: Optional[QuotedTweet] = None
    stats: TweetStats = field(default_factory=TweetStats)
    poll: Optional[Poll] = None
    translated_text: Optional[str] = None
    source_language: Optional[str] = None
