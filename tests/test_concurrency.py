import asyncio

from src.bot import build_application
from src.config import config
from src.services.download_queue import DownloadQueue


def test_application_enables_bounded_concurrent_updates(monkeypatch):
    monkeypatch.setattr(config, "BOT_TOKEN", "123456:test-token")
    monkeypatch.setattr(config, "MAX_CONCURRENT_UPDATES", 8)

    application = build_application()

    assert application.update_processor.max_concurrent_updates == 8


def test_download_queue_runs_two_jobs_concurrently():
    async def scenario() -> None:
        queue = DownloadQueue(max_concurrent=2)
        release = asyncio.Event()
        started = [asyncio.Event() for _ in range(3)]

        async def job(index: int) -> None:
            started[index].set()
            await release.wait()

        first = await queue.enqueue(lambda: job(0))
        second = await queue.enqueue(lambda: job(1))
        third = await queue.enqueue(lambda: job(2))

        await asyncio.wait_for(asyncio.gather(started[0].wait(), started[1].wait()), timeout=1)
        assert started[2].is_set() is False
        assert first[:2] == (True, 0)
        assert second[:2] == (True, 0)
        assert third[:2] == (False, 1)

        release.set()
        await asyncio.wait_for(asyncio.gather(first[2], second[2], third[2]), timeout=1)

    asyncio.run(scenario())
