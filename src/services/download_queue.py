import asyncio
from collections import deque
from collections.abc import Awaitable, Callable


class DownloadQueue:
    def __init__(self, max_concurrent: int, max_pending: int = 32) -> None:
        self._max_concurrent = max(1, max_concurrent)
        self._max_pending = max(0, max_pending)
        self._closed = False
        self._active = 0
        self._waiting: deque[asyncio.Event] = deque()
        self._lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()
        self._job_events: dict[asyncio.Task[None], asyncio.Event] = {}

    async def enqueue(self, job: Callable[[], Awaitable[None]]) -> tuple[bool, int, asyncio.Task[None]]:
        wait_event = asyncio.Event()
        started_immediately = False

        async with self._lock:
            if self._closed or (self._active >= self._max_concurrent and len(self._waiting) >= self._max_pending):
                raise RuntimeError("Download queue is unavailable")
            if self._active < self._max_concurrent:
                self._active += 1
                wait_event.set()
                started_immediately = True
                position = 0
            else:
                self._waiting.append(wait_event)
                position = len(self._waiting)

        async def runner() -> None:
            await wait_event.wait()
            await job()

        task = asyncio.create_task(runner())
        self._tasks.add(task)
        self._job_events[task] = wait_event

        def finished(done: asyncio.Task[None]) -> None:
            self._tasks.discard(done)
            self._job_events.pop(done, None)
            cleanup = asyncio.create_task(self._release_slot(wait_event))
            self._tasks.add(cleanup)
            cleanup.add_done_callback(self._tasks.discard)

        # A done callback also runs when cancelled before runner() first executes.
        task.add_done_callback(finished)
        return started_immediately, position, task

    async def _release_slot(self, wait_event: asyncio.Event) -> None:
        async with self._lock:
            if not wait_event.is_set():
                self._waiting.remove(wait_event)
                return
            if self._waiting:
                self._waiting.popleft().set()
            else:
                self._active = max(self._active - 1, 0)

    async def pending_count(self) -> int:
        async with self._lock:
            return len(self._waiting)

    async def shutdown(self) -> None:
        self._closed = True
        for task, event in tuple(self._job_events.items()):
            if not event.is_set():
                task.cancel()
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
            await asyncio.sleep(0)
