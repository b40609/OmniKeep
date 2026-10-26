import asyncio
import logging
import time
from app.config import settings
from app.file_lock import FileLock
from typing import Dict, Any, Optional, Set
from app.database import (
    claim_next_task,
    update_task_status,
    reset_stale_tasks,
    get_user_setting,
    find_item_by_canonical_or_url,
    get_db_connection
)
from app.pipeline import run_pipeline
from app.bot.telegram_bot import (
    notify_task_heartbeat,
    notify_task_completed,
    notify_task_failed
)
from app.bot.line_bot import (
    notify_line_completed,
    notify_line_failed
)

logger = logging.getLogger("omnikeep.worker")

# LLM providers answer these when the account quota/plan is exhausted.
_RATE_LIMIT_PATTERNS = ("429", "rate limit", "quota", "resource_exhausted", "too many requests")
_MAX_RATE_LIMIT_RETRIES = 6


def _is_rate_limit_error(exc: Exception) -> bool:
    s = str(exc).lower()
    return any(p in s for p in _RATE_LIMIT_PATTERNS)


class TaskWorker:
    """
    Persistent Asynchronous Queue Worker (Hoarder Pattern):
    - Recovers interrupted tasks on startup (Crash Recovery).
    - Processes tasks with bounded concurrency (Semaphore=2).
    - Instant URL Idempotency Cache: returns existing items in <5ms without re-querying LLM.
    - Decoupled from Ingestion loop for sub-50ms ingestion responsiveness.
    - Supports Multi-Channel Delivery: Telegram (Inline Card) and LINE (Flex Bubble Push).
    - Rate-limit aware: on 429 the whole worker cools down with exponential
      backoff (60s -> 600s) instead of burning retries in seconds; quota is
      account-wide, so all queued tasks wait together and resume automatically.
    """

    def __init__(self, concurrency: int = 2, poll_interval: float = 0.5, max_retries: int = 2):
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.semaphore = asyncio.BoundedSemaphore(concurrency)
        self._ownership = None
        self.running: bool = False
        self._loop_task: Optional[asyncio.Task] = None
        self.active_tasks: Set[asyncio.Task] = set()
        # Rate-limit cooldown state (monotonic clock)
        self._rate_limit_until: float = 0.0
        self._rate_limit_backoff: float = 60.0

    def start(self) -> asyncio.Task:
        if self.running and self._loop_task and not self._loop_task.done():
            return self._loop_task

        # 1. Crash recovery: reset stale 'processing' tasks back to 'queued'
        self._ownership = FileLock(settings.DATABASE_PATH + ".worker.lock")
        if not self._ownership.acquire():
            raise RuntimeError("Another queue worker owns this database")
        try:
            recovered = reset_stale_tasks(exclusive_owner=True)
        except BaseException:
            self._ownership.release()
            raise
        if recovered > 0:
            logger.info(f"[Queue Worker] Crash recovery: reset {recovered} stale task(s) to queued")

        self.running = True
        self.semaphore = asyncio.BoundedSemaphore(self.concurrency)
        self._loop_task = asyncio.create_task(self._run_loop())
        logger.info(f"[Queue Worker] Started with concurrency={self.concurrency}, poll_interval={self.poll_interval}s")
        return self._loop_task

    async def stop(self, timeout: float = 10.0):
        self.running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
            try:
                await self._loop_task
            except (asyncio.CancelledError, Exception):
                pass

        if self.active_tasks:
            logger.info(f"[Queue Worker] Waiting for {len(self.active_tasks)} active task(s) to finish...")
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self.active_tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning("[Queue Worker] Graceful stop timeout exceeded, canceling running tasks")
                for t in self.active_tasks:
                    t.cancel()
                await asyncio.gather(*self.active_tasks, return_exceptions=True)

        if self._ownership:
            self._ownership.release()

        logger.info("[Queue Worker] Stopped successfully")

    async def _run_loop(self):
        while self.running:
            acquired = False
            try:
                # Global rate-limit cooldown: hold off claiming while the LLM
                # quota recovers instead of retrying into a wall.
                now = time.monotonic()
                if now < self._rate_limit_until:
                    await asyncio.sleep(min(self._rate_limit_until - now, 5.0))
                    continue

                # Acquire concurrency slot before claiming from DB
                await self.semaphore.acquire()
                acquired = True

                if not self.running:
                    break

                task = claim_next_task()
                if not task:
                    self.semaphore.release()
                    acquired = False
                    await asyncio.sleep(self.poll_interval)
                    continue

                # Spawn background execution under semaphore control
                t = asyncio.create_task(self._process_task_wrapper(task))
                acquired = False  # The wrapper now owns this slot.
                self.active_tasks.add(t)
                t.add_done_callback(self.active_tasks.discard)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Queue Worker] Loop iteration error: {e}")
                await asyncio.sleep(self.poll_interval)
            finally:
                if acquired:
                    self.semaphore.release()

    async def _process_task_wrapper(self, task: Dict[str, Any]):
        try:
            await self._process_task(task)
        except Exception as e:
            logger.error(f"[Queue Worker] Unhandled task error for {task.get('id')}: {e}")
        finally:
            self.semaphore.release()

    async def _process_task(self, task: Dict[str, Any]):
        task_id = task["id"]
        url = task["url"]
        source = task.get("source", "telegram")
        chat_id = task.get("chat_id")
        message_id = task.get("message_id")
        retry_count = int(task.get("retry_count") or 0)

        logger.info(f"[Queue Worker] Processing task {task_id} (source: {source}) -> {url[:60]}")

        # 1. Idempotency Cache Check: Instant return if URL or repo is already in second brain
        existing_item = find_item_by_canonical_or_url(url)
        if existing_item:
            logger.info(f"[Queue Worker] Idempotency Hit: URL already indexed as item {existing_item.get('id')}")
            update_task_status(task_id, status="completed", item_id=existing_item.get("id"))
            if source == "telegram" and chat_id and message_id:
                try:
                    await notify_task_completed(int(chat_id), int(message_id), existing_item)
                except Exception as e:
                    logger.warning(f"[Queue Worker] Telegram completion notify error: {e}")
            elif source == "line" and chat_id:
                await notify_line_completed(str(chat_id), existing_item)
            return

        # 2. Telegram Heartbeat notification if user is in heartbeat mode
        if source == "telegram" and chat_id and message_id:
            mode = get_user_setting(chat_id)
            if mode == "heartbeat":
                try:
                    await notify_task_heartbeat(
                        int(chat_id),
                        int(message_id),
                        "⚡ <b>正在下載並進行視聽雙軌情報解析 (L1/L2)...</b>"
                    )
                except Exception as e:
                    logger.warning(f"[Queue Worker] Telegram heartbeat error: {e}")

        try:
            # 3. Execute intelligence pipeline
            item = await run_pipeline(url)

            # Mark completed in DB
            update_task_status(task_id, status="completed", item_id=item.get("id"))
            self._rate_limit_backoff = 60.0  # quota healthy again — reset backoff
            logger.info(f"[Queue Worker] Task {task_id} completed successfully (item_id: {item.get('id')})")

            # 4. Multi-channel delivery
            if source == "telegram" and chat_id and message_id:
                await notify_task_completed(int(chat_id), int(message_id), item)
            elif source == "line" and chat_id:
                await notify_line_completed(str(chat_id), item)

        except Exception as exc:
            logger.error(f"[Queue Worker] Task {task_id} failed on attempt {retry_count + 1}: {exc}")

            if _is_rate_limit_error(exc):
                # 429 = account-wide quota; retry patiently with global backoff.
                if retry_count < _MAX_RATE_LIMIT_RETRIES:
                    backoff = self._rate_limit_backoff
                    self._rate_limit_backoff = min(self._rate_limit_backoff * 2, 600.0)
                    self._rate_limit_until = time.monotonic() + backoff
                    conn = get_db_connection()
                    c = conn.cursor()
                    c.execute(
                        "UPDATE ingest_tasks SET status = 'queued', retry_count = retry_count + 1, error_message = ? WHERE id = ?",
                        (f"AI 額度限流，{int(backoff)} 秒後自動重試（第 {retry_count + 1}/{_MAX_RATE_LIMIT_RETRIES} 次）", task_id)
                    )
                    conn.commit()
                    conn.close()
                    logger.warning(
                        f"[Queue Worker] Rate limited. Worker cooling down {int(backoff)}s; "
                        f"task {task_id} re-queued (attempt {retry_count + 1}/{_MAX_RATE_LIMIT_RETRIES})"
                    )
                    if source == "telegram" and chat_id and message_id:
                        try:
                            await notify_task_heartbeat(
                                int(chat_id), int(message_id),
                                f"⚠️ <b>AI 額度限流中</b>\n\n任務已排入延遲重試（第 {retry_count + 1} 次），約 {int(backoff)} 秒後自動繼續，無需重發。",
                            )
                        except Exception as e:
                            logger.warning(f"[Queue Worker] Telegram heartbeat error: {e}")
                    return
                # Out of rate-limit retries — fail with actionable guidance.
                friendly = (
                    "AI 服務額度已用盡（免費方案限流），自動重試 6 次仍未恢復。"
                    "可升級 LLM 供應商方案，或於 .env 加入 GEMINI_API_KEYS 作為備援後重新轉發此訊息。"
                )
                update_task_status(task_id, status="failed", error_message=friendly)
                if source == "telegram" and chat_id and message_id:
                    await notify_task_failed(int(chat_id), int(message_id), friendly)
                elif source == "line" and chat_id:
                    await notify_line_failed(str(chat_id), friendly)
                return

            # Non-rate-limit error: reset backoff so a later 429 starts gentle.
            self._rate_limit_backoff = 60.0

            # Transient error retry policy: up to max_retries (default 2 retries)
            if retry_count < self.max_retries:
                conn = get_db_connection()
                c = conn.cursor()
                c.execute(
                    "UPDATE ingest_tasks SET status = 'queued', retry_count = retry_count + 1, error_message = ? WHERE id = ?",
                    (f"Attempt {retry_count + 1} failed: {str(exc)}", task_id)
                )
                conn.commit()
                conn.close()
                logger.info(f"[Queue Worker] Task {task_id} re-enqueued for retry (retry_count: {retry_count + 1})")
            else:
                update_task_status(task_id, status="failed", error_message=str(exc))
                if source == "telegram" and chat_id and message_id:
                    await notify_task_failed(int(chat_id), int(message_id), str(exc))
                elif source == "line" and chat_id:
                    await notify_line_failed(str(chat_id), str(exc))

task_worker = TaskWorker(concurrency=2, poll_interval=0.5)
