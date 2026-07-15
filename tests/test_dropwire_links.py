from src.providers.link_router import detect_source, find_supported_links
from src.providers.youtube_urls import extract_video_id
from src.rendering.hashtags import build_hashtags, normalize_hashtag, render_hashtags


def test_extract_video_id():
    assert extract_video_id("https://youtu.be/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://youtube.com/shorts/dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert extract_video_id("https://example.com/watch?v=dQw4w9WgXcQ") is None


def test_find_supported_links_keeps_order():
    text = (
        "first https://youtu.be/dQw4w9WgXcQ then https://x.com/user/status/123 and https://open.spotify.com/track/abc"
    )
    links = find_supported_links(text)
    assert [link.source for link in links] == ["youtube", "twitter", "spotify"]


def test_twitter_status_with_media_suffix_is_not_duplicated():
    text = "https://x.com/de3dsoul/status/2073270583589040581/photo/1"
    links = find_supported_links(text)
    assert len(links) == 1
    assert links[0].source == "twitter"
    assert links[0].url == text


def test_detect_source_uses_exact_hosts():
    assert detect_source("https://spotify.link/example") == "spotify"
    assert detect_source("https://on.soundcloud.com/example") == "soundcloud"
    assert detect_source("https://open.spotify.com.evil.example/track/abc") is None
    assert detect_source("https://x.com.evil.example/user/status/123") is None


def test_hashtag_normalization():
    assert normalize_hashtag("@The Real Underground") == "#the_real_underground"
    assert normalize_hashtag("самый настоящий андеграунд") == "#самый_настоящий_андеграунд"
    assert normalize_hashtag("123") == "#u_123"
    assert render_hashtags(build_hashtags("youtube", "video", "The Real Underground")) == (
        "#youtube #video #the_real_underground"
    )
