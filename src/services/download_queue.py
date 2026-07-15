import asyncio
from collections import deque
from collections.abc import Awaitable, Callable


class DownloadQueue:
    def __init__(self, max_concurrent: int) -> None:
        self._max_concurrent = max_concurrent
        self._active = 0
        self._waiting: deque[asyncio.Event] = deque()
        self._lock = asyncio.Lock()

    async def enqueue(self, job: Callable[[], Awaitable[None]]) -> tuple[bool, int, asyncio.Task[None]]:
        wait_event: asyncio.Event | None = None
        started_immediately = False

        async with self._lock:
            if self._active < self._max_concurrent:
                self._active += 1
                started_immediately = True
                position = 0
            else:
                wait_event = asyncio.Event()
                self._waiting.append(wait_event)
                position = len(self._waiting)

        async def runner() -> None:
            if wait_event is not None:
                await wait_event.wait()
            try:
                await job()
            finally:
                await self._release_slot()

        task = asyncio.create_task(runner())
        return started_immediately, position, task

    async def _release_slot(self) -> None:
        async with self._lock:
            if self._waiting:
                self._waiting.popleft().set()
            else:
                self._active = max(self._active - 1, 0)

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._waiting)
