import asyncio
import time

from src.telegram_runtime import BadRequest, ContextTypes, NetworkError, RetryAfter, TelegramError


class MessageProgress:
    def __init__(
        self,
        context: ContextTypes.DEFAULT_TYPE,
        chat_id: int,
        message_id: int,
        min_interval_seconds: float = 2.0,
        min_percent_step: int = 5,
    ) -> None:
        self._context = context
        self._chat_id = chat_id
        self._message_id = message_id
        self._min_interval_seconds = min_interval_seconds
        self._min_percent_step = min_percent_step
        self._last_update_ts = 0.0
        self._last_percent = -1
        self._last_text = ""
        self._suppress_until_ts = 0.0
        self._lock = asyncio.Lock()

    async def set_text(self, text: str, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now < self._suppress_until_ts:
            return
        if not force and text == self._last_text and now - self._last_update_ts < self._min_interval_seconds:
            return

        async with self._lock:
            now = time.monotonic()
            if not force and now < self._suppress_until_ts:
                return
            if not force and text == self._last_text and now - self._last_update_ts < self._min_interval_seconds:
                return
            try:
                await self._context.bot.edit_message_text(
                    text=text,
                    chat_id=self._chat_id,
                    message_id=self._message_id,
                )
            except BadRequest as exc:
                if "message is not modified" in str(exc).lower():
                    return
                raise
            except RetryAfter as exc:
                self._suppress_until_ts = max(self._suppress_until_ts, time.monotonic() + float(exc.retry_after) + 0.5)
                self._last_update_ts = now
                self._last_text = text
            except NetworkError:
                self._suppress_until_ts = max(self._suppress_until_ts, time.monotonic() + 3.0)
                self._last_update_ts = now
            except TelegramError:
                raise
            else:
                self._last_update_ts = now
                self._last_text = text

    async def set_download_percent(self, percent: int) -> None:
        now = time.monotonic()
        if self._last_percent >= 0 and percent - self._last_percent < self._min_percent_step:
            if now - self._last_update_ts < self._min_interval_seconds:
                return

        self._last_percent = percent
        await self.set_text(f"📥 Скачивание: {percent}%")
