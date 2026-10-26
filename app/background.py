"""Bounded, owned follow-up work shared by radar and entity expansion."""
import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.config import settings

logger = logging.getLogger(__name__)


class FollowUpPool:
    def __init__(self):
        self._queue = None
        self._workers = []
        self._accepting = False

    def start(self):
        if self._accepting:
            return
        self._queue = asyncio.Queue(maxsize=max(1, settings.RELEVANCE_QUEUE_SIZE))
        self._accepting = True
        self._workers = [asyncio.create_task(self._consume())
                         for _ in range(max(1, settings.RELEVANCE_CONCURRENCY))]

    def submit(self, factory: Callable[[], Awaitable[object]]) -> bool:
        # A factory avoids creating an unawaited coroutine when the queue is full.
        if not self._accepting:
            return False
        try:
            self._queue.put_nowait(factory)
            return True
        except asyncio.QueueFull:
            logger.warning("Follow-up queue is full; work was not scheduled")
            return False

    async def _consume(self):
        while True:
            factory = await self._queue.get()
            try:
                await factory()
            except Exception as exc:
                logger.warning("Follow-up failed (%s)", type(exc).__name__)
            finally:
                self._queue.task_done()

    async def stop(self, timeout=10.0):
        self._accepting = False
        try:
            if self._queue is not None:
                await asyncio.wait_for(self._queue.join(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.warning("Follow-up drain timed out; cancelling remaining work")
        finally:
            for worker in self._workers:
                worker.cancel()
            await asyncio.gather(*self._workers, return_exceptions=True)
            self._workers = []
            self._queue = None


follow_up_pool = FollowUpPool()
