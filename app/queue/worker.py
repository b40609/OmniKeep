import asyncio
import logging
import time
from contextlib import closing
from app.config import settings
from app.error_translate import classify, failure_message, is_ai_failure
from app.file_lock import FileLock
from typing import Dict, Any, Optional, Set
from app.database import (
    claim_next_task,
    get_ingest_task,
    claim_completion_notification,
    finish_completion_notification,
    update_task_status,
    reset_stale_tasks,
    get_user_setting,
    find_item_by_canonical_or_url,
    get_item_by_id,
    get_db_connection
)
from app.pipeline import run_pipeline
from app.parsers.reel import ReelUnavailableError, is_empty_reel_metadata
from app.providers.openai_compatible import ProviderUnavailableError
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

_MAX_RATE_LIMIT_RETRIES = 6
# How long a timed-out attempt gets to unwind after it is cancelled, before its slot is
# given back anyway.
_CANCEL_GRACE_SECONDS = 10.0
# Tries (with a growing pause) at writing a task's state back before giving up on the write.
_STATE_WRITE_PAUSES = (0.2, 1.0, 3.0)


class TaskTimeoutError(Exception):
    """One attempt at a task ran past INGEST_TASK_TIMEOUT_SECONDS and was given up."""

    def __init__(self, seconds: float):
        self.seconds = seconds
        limit = f"{round(seconds / 60)} 分鐘" if seconds >= 60 else f"{seconds:g} 秒"
        super().__init__(f"處理超過 {limit}還沒完成，這次嘗試已中止（影片太長，或來源網站、AI 服務一直沒有回應時會這樣）。")


def _is_rate_limit_error(exc: Exception) -> bool:
    """An AI provider's rate limit: the one failure the whole queue waits out.

    Read from where the exception came from and its status (app/error_translate.py), not
    from words in its text. A fetched site answering 429 (an HTTPStatusError, yt-dlp's
    "HTTP Error 429") matched "429" and cooled the whole queue down, though the AI quota
    had nothing to do with it; so did any message that happened to contain "quota".
    """
    return is_ai_failure(exc) and classify(exc)["kind"] == "rate_limit"


def _retrieve_outcome(attempt: "asyncio.Future") -> None:
    """Done callback of an abandoned attempt: read its outcome, so asyncio does not report
    an exception that was never retrieved."""
    if not attempt.cancelled():
        attempt.exception()


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
    - Bounded: one attempt may take INGEST_TASK_TIMEOUT_SECONDS at most (a hung fetch or
      AI call used to hold its slot until the next restart; two of them stopped the queue),
      and a task handed out more often than any retry policy allows is failed instead of
      being claimed first again after every crash.
    """

    def __init__(self, concurrency: int = 2, poll_interval: float = 0.5, max_retries: int = 2):
        self.concurrency = concurrency
        self.poll_interval = poll_interval
        self.max_retries = max_retries
        self.semaphore = asyncio.BoundedSemaphore(concurrency)
        self.notification_semaphore = asyncio.BoundedSemaphore(concurrency)
        self._ownership = None
        self.running: bool = False
        self._loop_task: Optional[asyncio.Task] = None
        self.active_tasks: Set[asyncio.Task] = set()
        # Timed-out attempts that did not stop when cancelled; kept until they end on their own.
        self.abandoned_attempts: Set["asyncio.Future"] = set()
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
        self.notification_semaphore = asyncio.BoundedSemaphore(self.concurrency)
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
                # Notification delivery runs even while the LLM is cooling down.
                # Failed sends have their own persistent backoff and never requeue ingestion.
                try:
                    await self._schedule_completion_notification()
                except Exception as exc:
                    logger.warning("[Queue Worker] Notification scheduling error: %s", exc)

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

    async def _schedule_completion_notification(self, task_id: Optional[str] = None,
                                                item: Optional[Dict[str, Any]] = None):
        if self.notification_semaphore.locked():
            return
        await self.notification_semaphore.acquire()
        try:
            delivery = claim_completion_notification(task_id=task_id)
        except BaseException:
            self.notification_semaphore.release()
            raise
        if not delivery:
            self.notification_semaphore.release()
            return
        try:
            task = asyncio.create_task(self._deliver_completion(delivery, item))
        except BaseException:
            self.notification_semaphore.release()
            raise
        self.active_tasks.add(task)
        task.add_done_callback(self.active_tasks.discard)

    async def _deliver_completion(self, delivery: Dict[str, Any], item: Optional[Dict[str, Any]]):
        task_id = delivery["id"]
        marker = delivery["error_message"]
        error = None
        finalized = False
        try:
            resolved_item = item or get_item_by_id(delivery["item_id"])
            if not resolved_item:
                raise RuntimeError(f"Completed item unavailable for delivery: {delivery['item_id']}")
            if delivery["source"] == "telegram":
                await notify_task_completed(int(delivery["chat_id"]), int(delivery["message_id"]),
                                            resolved_item, strict=True)
            elif delivery["source"] == "line":
                await notify_line_completed(str(delivery["chat_id"]), resolved_item, strict=True)
            else:
                raise ValueError(f"Unsupported completion source: {delivery['source']}")
            finalized = True
        except asyncio.CancelledError:
            # Leave in-flight marker for exclusive-owner startup recovery.
            raise
        except Exception as exc:
            error = str(exc)
            finalized = True
            logger.warning("[Queue Worker] Completion notification for %s failed: %s", task_id, exc)
        finally:
            try:
                if finalized:
                    finish_completion_notification(task_id, marker, error=error)
            finally:
                self.notification_semaphore.release()

    async def _trigger_completion_notification(self, task_id: str, item: Dict[str, Any]):
        try:
            await self._schedule_completion_notification(task_id=task_id, item=item)
        except Exception as exc:
            # The durable pending marker is already committed; the loop will retry.
            logger.warning("[Queue Worker] Could not schedule notification for %s: %s", task_id, exc)

    async def _run_with_timeout(self, coro, timeout: float):
        """Await `coro` for at most `timeout` seconds, then TaskTimeoutError (0 or less: no limit).

        asyncio.wait_for alone would not give the slot back: it waits for the cancelled
        attempt to finish, and the reel parser shields its native threads (download, speech
        to text) and waits for them when cancelled, so a hung thread would hold the slot for
        good. The attempt gets _CANCEL_GRACE_SECONDS to unwind, then is left to end on its own.
        """
        if timeout <= 0:
            return await coro
        attempt = asyncio.ensure_future(coro)
        try:
            done, _ = await asyncio.wait({attempt}, timeout=timeout)
            if done:
                return attempt.result()
            attempt.cancel()
            done, _ = await asyncio.wait({attempt}, timeout=_CANCEL_GRACE_SECONDS)
        except asyncio.CancelledError:
            # The worker is stopping: take the attempt down too, as a plain await would have.
            attempt.cancel()
            await asyncio.gather(attempt, return_exceptions=True)
            raise
        if not done:
            self.abandoned_attempts.add(attempt)
            attempt.add_done_callback(self.abandoned_attempts.discard)
            attempt.add_done_callback(_retrieve_outcome)
            logger.warning("[Queue Worker] A timed-out attempt did not stop within %gs of being cancelled; "
                           "its slot is released and it is left to end on its own", _CANCEL_GRACE_SECONDS)
        elif not attempt.cancelled() and attempt.exception() is None:
            return attempt.result()  # it finished just as the limit was reached
        raise TaskTimeoutError(timeout)

    async def _write_task_state(self, task_id: str, what: str, write) -> bool:
        """Run one write of a task's state; True when it landed.

        These writes happen while a failure is being handled. One that raised there left the
        task 'processing' until the next start, with nothing in the log to say so. A busy
        database is tried again; a write that never lands is logged with what was lost
        (reset_stale_tasks() puts the task back in the queue at the next start).
        """
        last: Optional[Exception] = None
        for pause in (0.0, *_STATE_WRITE_PAUSES):
            if pause:
                await asyncio.sleep(pause)
            try:
                write()
                return True
            except Exception as exc:
                last = exc
                logger.warning("[Queue Worker] Task %s: could not %s (%s: %s)",
                               task_id, what, type(exc).__name__, exc)
        logger.error("[Queue Worker] Task %s stays 'processing': could not %s after %d tries (%s: %s). "
                     "It is queued again at the next start.",
                     task_id, what, len(_STATE_WRITE_PAUSES) + 1, type(last).__name__, last)
        return False

    async def _requeue_task(self, task_id: str, note: str) -> bool:
        def write():
            with closing(get_db_connection()) as conn, conn:
                conn.execute(
                    "UPDATE ingest_tasks SET status = 'queued', retry_count = retry_count + 1, error_message = ? WHERE id = ?",
                    (note, task_id)
                )
        return await self._write_task_state(task_id, "queue it again", write)

    async def _fail_task(self, task_id: str, message: str) -> bool:
        return await self._write_task_state(
            task_id, "mark it failed",
            lambda: update_task_status(task_id, status="failed", error_message=message))

    async def _process_task(self, task: Dict[str, Any]):
        task_id = task["id"]
        url = task["url"]
        source = task.get("source", "telegram")
        chat_id = task.get("chat_id")
        message_id = task.get("message_id")
        retry_count = int(task.get("retry_count") or 0)

        def _get_current_message_id() -> Optional[int]:
            nonlocal message_id
            if not message_id and source == "telegram":
                fresh = get_ingest_task(task_id)
                if fresh and fresh.get("message_id") is not None:
                    message_id = fresh.get("message_id")
            return message_id

        async def _notify_task_failed(err_msg: str):
            mid = _get_current_message_id()
            if source == "telegram" and chat_id and mid:
                await notify_task_failed(int(chat_id), int(mid), err_msg)
            elif source == "line" and chat_id:
                await notify_line_failed(str(chat_id), err_msg)

        logger.info(f"[Queue Worker] Processing task {task_id} (source: {source}) -> {url[:60]}")

        # 1. Idempotency Cache Check: Instant return if URL or repo is already in second brain
        existing_item = find_item_by_canonical_or_url(url)
        if existing_item and not is_empty_reel_metadata(existing_item):
            logger.info(f"[Queue Worker] Idempotency Hit: URL already indexed as item {existing_item.get('id')}")
            update_task_status(task_id, status="completed", item_id=existing_item.get("id"))
            await self._trigger_completion_notification(task_id, existing_item)
            return
        if existing_item:
            # Keep the existing URL so a successful retry updates the same item.
            url = existing_item.get("url") or url
            logger.info(f"[Queue Worker] Retrying empty reel item {existing_item.get('id')}")

        # 1b. A task handed out more often than any retry policy allows is one that takes the
        # process down with it: reset_stale_tasks() queues it again at every start (adding to
        # retry_count) and, being the oldest, it was claimed first again, without end.
        if retry_count > max(self.max_retries, _MAX_RATE_LIMIT_RETRIES):
            gave_up = (f"這個連結已經處理 {retry_count} 次都沒有完成（包含服務中斷後重新排隊的次數），"
                       "已停止自動重試。可以重新傳送連結再試一次。")
            logger.error(f"[Queue Worker] Task {task_id} was handed out {retry_count} times without finishing; "
                         "failing it instead of running it again")
            await self._fail_task(task_id, gave_up)
            await _notify_task_failed(gave_up)
            return

        # 2. Telegram Heartbeat notification if user is in heartbeat mode
        mid = _get_current_message_id()
        if source == "telegram" and chat_id and mid:
            mode = get_user_setting(chat_id)
            if mode == "heartbeat":
                try:
                    await notify_task_heartbeat(
                        int(chat_id),
                        int(mid),
                        "<b>正在讀取並分析…</b>"
                    )
                except Exception as e:
                    logger.warning(f"[Queue Worker] Telegram heartbeat error: {e}")

        try:
            # 3. Execute intelligence pipeline, for a bounded time
            item = await self._run_with_timeout(run_pipeline(url), float(settings.INGEST_TASK_TIMEOUT_SECONDS))

            # Mark completed in DB
            update_task_status(task_id, status="completed", item_id=item.get("id"))
            self._rate_limit_backoff = 60.0  # quota healthy again — reset backoff
            logger.info(f"[Queue Worker] Task {task_id} completed successfully (item_id: {item.get('id')})")
        except Exception as exc:
            logger.error(f"[Queue Worker] Task {task_id} failed on attempt {retry_count + 1}: "
                         f"{type(exc).__name__}: {exc}")

            if isinstance(exc, (ProviderUnavailableError, ReelUnavailableError)):
                # A network access block is deterministic; avoid repeated paid API requests.
                await self._fail_task(task_id, str(exc))
                await _notify_task_failed(str(exc))
                return

            if _is_rate_limit_error(exc):
                # 429 = account-wide quota; retry patiently with global backoff.
                if retry_count < _MAX_RATE_LIMIT_RETRIES:
                    backoff = self._rate_limit_backoff
                    self._rate_limit_backoff = min(self._rate_limit_backoff * 2, 600.0)
                    self._rate_limit_until = time.monotonic() + backoff
                    await self._requeue_task(
                        task_id,
                        f"AI 額度限流，{int(backoff)} 秒後自動重試（第 {retry_count + 1}/{_MAX_RATE_LIMIT_RETRIES} 次）")
                    logger.warning(
                        f"[Queue Worker] Rate limited. Worker cooling down {int(backoff)}s; "
                        f"task {task_id} re-queued (attempt {retry_count + 1}/{_MAX_RATE_LIMIT_RETRIES})"
                    )
                    mid = _get_current_message_id()
                    if source == "telegram" and chat_id and mid:
                        try:
                            await notify_task_heartbeat(
                                int(chat_id), int(mid),
                                f"<b>AI 服務限流，稍後自動再試</b>\n\n這是第 {retry_count + 1} 次重試，約 {int(backoff)} 秒後自動繼續，不用重新傳送。",
                            )
                        except Exception as e:
                            logger.warning(f"[Queue Worker] Telegram heartbeat error: {e}")
                    return
                # Out of rate-limit retries — fail with actionable guidance.
                friendly = (
                    f"AI 服務持續限流（免費額度用完，或請求太頻繁），自動重試 {_MAX_RATE_LIMIT_RETRIES} 次仍未恢復。"
                    "可以晚一點重新傳送這個連結；常發生的話到「設定 › AI」把請求間隔調長、"
                    "加一條備援連線，或升級服務商方案。"
                )
                await self._fail_task(task_id, friendly)
                await _notify_task_failed(friendly)
                return

            # Non-rate-limit error: reset backoff so a later 429 starts gentle.
            self._rate_limit_backoff = 60.0

            # An AI failure is explained in Chinese; anything else keeps its own message.
            reason = failure_message(exc)

            # Transient error retry policy: up to max_retries (default 2 retries)
            if retry_count < self.max_retries:
                if await self._requeue_task(task_id, f"第 {retry_count + 1} 次嘗試失敗，會自動再試：{reason}"):
                    logger.info(f"[Queue Worker] Task {task_id} re-enqueued for retry (retry_count: {retry_count + 1})")
            else:
                await self._fail_task(task_id, reason)
                await _notify_task_failed(reason)

        else:
            # Delivery is independent of ingestion, retries and LLM quota state.
            await self._trigger_completion_notification(task_id, item)

task_worker = TaskWorker(concurrency=2, poll_interval=0.5)
