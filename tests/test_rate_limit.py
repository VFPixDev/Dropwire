from src.utils.rate_limit import RateLimiter


def test_rejected_chat_limit_does_not_consume_user_limit(monkeypatch):
    limiter = RateLimiter()
    monkeypatch.setattr("src.utils.rate_limit.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("src.utils.rate_limit.config.RATE_LIMIT_SECONDS", 5)
    monkeypatch.setattr("src.utils.rate_limit.config.RATE_LIMIT_CHAT_SECONDS", 5)
    monkeypatch.setattr("src.utils.rate_limit.config.RATE_LIMIT_CHAT_BURST", 1)
    limiter.chat_timestamps[-100].append(100.0)

    assert limiter.is_allowed(42, -100) is False
    assert 42 not in limiter.user_timestamps
    assert limiter.is_allowed(42, -200) is True


def test_distinct_users_can_use_same_chat_within_burst(monkeypatch):
    limiter = RateLimiter()
    monkeypatch.setattr("src.utils.rate_limit.time.monotonic", lambda: 100.0)
    monkeypatch.setattr("src.utils.rate_limit.config.RATE_LIMIT_SECONDS", 5)
    monkeypatch.setattr("src.utils.rate_limit.config.RATE_LIMIT_CHAT_SECONDS", 3)
    monkeypatch.setattr("src.utils.rate_limit.config.RATE_LIMIT_CHAT_BURST", 2)

    assert limiter.is_allowed(1, -100) is True
    assert limiter.is_allowed(2, -100) is True
    assert limiter.is_allowed(3, -100) is False
    assert 3 not in limiter.user_timestamps
