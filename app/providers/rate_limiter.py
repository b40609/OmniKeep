"""
Adaptive client-side rate limiter for LLM providers.

All LLM traffic (queue worker, radar scheduler, direct ingest) shares one
limiter instance so the provider's per-key request-rate budget is respected
globally. 429 responses stretch the pacing interval automatically; success
streaks ease it back down. This complements the queue worker's long-cooldown
logic: the limiter absorbs short blips (seconds), the worker handles real
quota outages (minutes).
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Optional

logger = logging.getLogger("omnikeep.rate_limiter")


class AdaptiveRateLimiter:
    def __init__(self, min_interval: float = 1.0, max_interval: float = 30.0, max_concurrency: int = 2):
        self._min_interval = max(0.05, min_interval)
        self._max_interval = max(min_interval, max_interval)
        self._interval = self._min_interval
        self._lock = asyncio.Lock()
        self._next_slot = 0.0
        self._sem = asyncio.Semaphore(max(1, max_concurrency))
        self._success_streak = 0

    @asynccontextmanager
    async def slot(self):
        """Acquire a concurrency slot and a pacing gap before one LLM request."""
        await self._sem.acquire()
        try:
            async with self._lock:
                now = time.monotonic()
                wait = max(0.0, self._next_slot - now)
                self._next_slot = max(now, self._next_slot) + self._interval
            if wait > 0:
                await asyncio.sleep(wait)
            yield
        finally:
            self._sem.release()

    @property
    def interval(self) -> float:
        return self._interval

    def on_rate_limited(self, retry_after: Optional[float] = None) -> None:
        self._success_streak = 0
        if retry_after and retry_after > 0:
            self._interval = min(max(self._interval, retry_after + 0.5), self._max_interval)
        else:
            self._interval = min(self._interval * 1.8 + 0.5, self._max_interval)
        logger.info(f"[Rate Limiter] 429 seen — pacing interval now {self._interval:.1f}s")

    def on_success(self) -> None:
        self._success_streak += 1
        if self._success_streak >= 8 and self._interval > self._min_interval:
            self._interval = max(self._min_interval, self._interval * 0.8)
            self._success_streak = 0
            logger.info(f"[Rate Limiter] Healthy streak — easing interval to {self._interval:.1f}s")


# Shared across every provider instance in the process (one API account = one budget).
def _build_limiter() -> AdaptiveRateLimiter:
    try:
        from app.config import settings
        return AdaptiveRateLimiter(
            min_interval=settings.LLM_MIN_REQUEST_INTERVAL,
            max_concurrency=settings.LLM_MAX_CONCURRENCY,
        )
    except Exception:
        return AdaptiveRateLimiter()


limiter = _build_limiter()
