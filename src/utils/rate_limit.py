import time
from collections import defaultdict, deque
from src.config import config


class RateLimiter:
    def __init__(self):
        self.user_timestamps = defaultdict(float)
        self.chat_timestamps: defaultdict[int, deque[float]] = defaultdict(deque)

    def check_user_limit(self, user_id: int) -> bool:
        """Проверяет, может ли пользователь сделать запрос"""
        now = time.monotonic()
        last_request = self.user_timestamps.get(user_id, 0)

        if now - last_request < config.RATE_LIMIT_SECONDS:
            return False

        self.user_timestamps[user_id] = now
        return True

    def check_chat_limit(self, chat_id: int) -> bool:
        """Проверяет, может ли чат сделать запрос"""
        return self._consume_chat_slot(chat_id, time.monotonic())

    def is_allowed(self, user_id: int, chat_id: int) -> bool:
        """Проверяет оба лимита"""
        now = time.monotonic()
        user_limited = now - self.user_timestamps.get(user_id, 0) < config.RATE_LIMIT_SECONDS
        if user_limited:
            return False
        if not self._consume_chat_slot(chat_id, now):
            return False

        self.user_timestamps[user_id] = now
        return True

    def _consume_chat_slot(self, chat_id: int, now: float) -> bool:
        window = config.RATE_LIMIT_CHAT_SECONDS
        if window <= 0:
            return True

        timestamps = self.chat_timestamps[chat_id]
        while timestamps and now - timestamps[0] >= window:
            timestamps.popleft()
        if len(timestamps) >= config.RATE_LIMIT_CHAT_BURST:
            return False
        timestamps.append(now)
        return True

    def cleanup_old_entries(self, max_age: int = 3600):
        """Очищает старые записи (старше max_age секунд)"""
        now = time.monotonic()

        # Очистка пользователей
        old_users = [uid for uid, ts in self.user_timestamps.items() if now - ts > max_age]
        for uid in old_users:
            del self.user_timestamps[uid]

        # Очистка чатов
        old_chats = []
        for chat_id, timestamps in self.chat_timestamps.items():
            while timestamps and now - timestamps[0] > max_age:
                timestamps.popleft()
            if not timestamps:
                old_chats.append(chat_id)
        for chat_id in old_chats:
            del self.chat_timestamps[chat_id]


rate_limiter = RateLimiter()
