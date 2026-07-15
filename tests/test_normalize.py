from src.twitter.normalize import extract_tweet_id, normalize_url, find_tweet_urls


def test_extract_tweet_id():
    """Тест извлечения ID твита"""
    assert extract_tweet_id("https://x.com/user/status/1234567890") == "1234567890"
    assert extract_tweet_id("https://twitter.com/user/status/9876543210") == "9876543210"
    assert extract_tweet_id("https://fxtwitter.com/user/status/1111111111") == "1111111111"
    assert extract_tweet_id("invalid url") is None


def test_normalize_url():
    """Тест нормализации URL"""
    assert normalize_url("https://twitter.com/elonmusk/status/123") == "https://x.com/elonmusk/status/123"
    assert normalize_url("https://fxtwitter.com/user/status/456") == "https://x.com/user/status/456"
    assert normalize_url("https://x.com/test/status/789") == "https://x.com/test/status/789"


def test_find_tweet_urls():
    """Тест поиска ссылок в тексте"""
    text = "Check this tweet https://x.com/user/status/123 and this https://twitter.com/other/status/456"
    urls = find_tweet_urls(text)
    assert len(urls) == 2
    assert "https://x.com/user/status/123" in urls
    assert "https://twitter.com/other/status/456" in urls
