from src.utils.rate_limit import RateLimiter


def test_rejected_chat_limit_does_not_consume_user_limit(monkeypatch):
    limiter = RateLimiter()
    monkeypatch.setattr("src.utils.rate_limit.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("src.utils.rate_limit.config.RATE_LIMIT_SECONDS", 5)
    monkeypatch.setattr("src.utils.rate_limit.config.RATE_LIMIT_CHAT_SECONDS", 5)
    limiter.chat_timestamps[-100] = 100.0

    assert limiter.is_allowed(42, -100) is False
    assert 42 not in limiter.user_timestamps
    assert limiter.is_allowed(42, -200) is True
