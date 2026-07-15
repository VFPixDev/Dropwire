import time
from collections import defaultdict
from src.config import config


class RateLimiter:
    def __init__(self):
        self.user_timestamps = defaultdict(float)
        self.chat_timestamps = defaultdict(float)

    def check_user_limit(self, user_id: int) -> bool:
        """Проверяет, может ли пользователь сделать запрос"""
        now = time.time()
        last_request = self.user_timestamps.get(user_id, 0)

        if now - last_request < config.RATE_LIMIT_SECONDS:
            return False

        self.user_timestamps[user_id] = now
        return True

    def check_chat_limit(self, chat_id: int) -> bool:
        """Проверяет, может ли чат сделать запрос"""
        now = time.time()
        last_request = self.chat_timestamps.get(chat_id, 0)

        if now - last_request < config.RATE_LIMIT_CHAT_SECONDS:
            return False

        self.chat_timestamps[chat_id] = now
        return True

    def is_allowed(self, user_id: int, chat_id: int) -> bool:
        """Проверяет оба лимита"""
        return self.check_user_limit(user_id) and self.check_chat_limit(chat_id)

    def cleanup_old_entries(self, max_age: int = 3600):
        """Очищает старые записи (старше max_age секунд)"""
        now = time.time()

        # Очистка пользователей
        old_users = [uid for uid, ts in self.user_timestamps.items() if now - ts > max_age]
        for uid in old_users:
            del self.user_timestamps[uid]

        # Очистка чатов
        old_chats = [cid for cid, ts in self.chat_timestamps.items() if now - ts > max_age]
        for cid in old_chats:
            del self.chat_timestamps[cid]


rate_limiter = RateLimiter()
