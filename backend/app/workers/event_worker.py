# app/workers/event_worker.py
"""Worker manager: N worker threads + a sweeper thread, started/stopped by the FastAPI lifespan.

Threads (not asyncio tasks) are used because the data layer is synchronous SQLAlchemy. Handlers may be plain
functions or coroutine functions; each runs in its own daemon thread so a hung handler can be abandoned on
timeout/shutdown without blocking process exit.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import queue
import threading
import time

from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.crud import processing as ps
from app.models import AttemptOutcome
from app.workers.event_broker import EventBroker
from app.workers.event_queue import EventQueue

logger = logging.getLogger(__name__)


class HandlerTimeout(Exception):
    pass


class EventWorkerManager:
    def __init__(self, settings: Settings, session_factory: sessionmaker, registry: ps.HandlerRegistry,
                 broker: EventBroker) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.registry = registry
        self.broker = broker
        self.queue = EventQueue(settings.EVENT_QUEUE_MAXSIZE)
        self._stopping = threading.Event()
        self._workers: list[threading.Thread] = []
        self._sweeper: threading.Thread | None = None
        self._inflight: dict[int, ps.EventContext] = {}
        self._lock = threading.Lock()
        self.running = False

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        with self.session_factory() as db:
            recovered = ps.recover_interrupted(db)
        if recovered:
            logger.warning("Recovered %d interrupted events", recovered)
        self.sweep_once()  # re-dispatch everything pending in PostgreSQL
        self._workers = [threading.Thread(target=self._worker_loop, args=(i,), name=f"event-worker-{i}", daemon=True)
                         for i in range(self.settings.EVENT_WORKER_CONCURRENCY)]
        self._sweeper = threading.Thread(target=self._sweeper_loop, name="event-sweeper", daemon=True)
        for t in (*self._workers, self._sweeper):
            t.start()
        self.running = True
        logger.info("Event workers started", extra={"workers": len(self._workers)})

    def stop(self) -> None:
        """Graceful shutdown: stop taking work, give in-flight events the grace period, record stragglers."""
        if not self.running:
            return
        self._stopping.set()
        deadline = time.monotonic() + self.settings.EVENT_SHUTDOWN_GRACE_SECONDS
        threads = [*self._workers, *([self._sweeper] if self._sweeper else [])]
        for t in threads:
            t.join(max(0.0, deadline - time.monotonic()))
        with self._lock:
            stragglers = list(self._inflight.values())
        for ctx in stragglers:  # still running after the grace period: record + abandon (daemon threads)
            self._fail(ctx, "Processing interrupted (shutdown)", True, None, AttemptOutcome.INTERRUPTED)
        self._workers, self._sweeper, self.running = [], None, False
        logger.info("Event workers stopped", extra={"abandoned": len(stragglers)})

    # ---- dispatch --------------------------------------------------------
    def dispatch(self, ids: list[int]) -> set[int]:
        """Enqueue events; returns the subset actually queued. The rest stay in PostgreSQL for the sweeper."""
        queued = {i for i in ids if self.queue.try_put(i)}
        if queued:
            with self.session_factory() as db:
                ps.mark_queued(db, list(queued))
        return queued

    def sweep_once(self) -> int:
        if self.queue.free <= 0:
            return 0
        with self.session_factory() as db:
            ids = ps.collect_dispatchable(db, limit=self.queue.capacity)
        return len(self.dispatch(ids))

    # ---- loops -----------------------------------------------------------
    def _sweeper_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                self.sweep_once()
            except Exception:  # noqa: BLE001
                logger.exception("Sweeper iteration failed")
            self._stopping.wait(self.settings.EVENT_SWEEP_INTERVAL_SECONDS)

    def _worker_loop(self, index: int) -> None:
        while not self._stopping.is_set():
            try:
                event_pk = self.queue.get(timeout=0.25)
            except queue.Empty:
                continue
            try:
                self._process(index, event_pk)
            except Exception:  # noqa: BLE001 - never let one event kill the worker
                logger.exception("Unexpected worker error", extra={"event_pk": event_pk})
            finally:
                self.queue.task_done()

    # ---- processing ------------------------------------------------------
    @staticmethod
    def _call_handler(handler, ctx: ps.EventContext) -> None:
        if inspect.iscoroutinefunction(handler):
            asyncio.run(handler(ctx))
        else:
            handler(ctx)

    def _run_with_timeout(self, handler, ctx: ps.EventContext) -> None:
        box: dict = {}
        done = threading.Event()

        def target() -> None:
            try:
                self._call_handler(handler, ctx)
            except BaseException as exc:  # noqa: BLE001
                box["error"] = exc
            finally:
                done.set()

        threading.Thread(target=target, name=f"handler-{ctx.id}", daemon=True).start()
        if not done.wait(self.settings.EVENT_PROCESSING_TIMEOUT_SECONDS):
            raise HandlerTimeout("Handler timed out")
        if "error" in box:
            raise box["error"]

    def _process(self, index: int, event_pk: int) -> None:
        with self.session_factory() as db:
            ctx = ps.claim_event(db, event_pk)
        if ctx is None:
            return  # already claimed / not claimable
        with self._lock:
            self._inflight[index] = ctx
        self._notify("event.processing", ctx, "PROCESSING")
        start = time.perf_counter()
        try:
            self._run_with_timeout(self.registry.get(ctx.event_type), ctx)
        except HandlerTimeout:
            self._fail(ctx, "Handler timed out", True, (time.perf_counter() - start) * 1000)
        except ps.NonRetryableProcessingError as exc:
            self._fail(ctx, ps.sanitize_error(exc), False, (time.perf_counter() - start) * 1000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Event handler failed", extra={"event_id": ctx.event_id, "attempt": ctx.attempt_number,
                                                          "error": ps.sanitize_error(exc)})
            self._fail(ctx, ps.sanitize_error(exc), True, (time.perf_counter() - start) * 1000)
        else:
            duration = (time.perf_counter() - start) * 1000
            with self.session_factory() as db:
                if ps.mark_success(db, ctx.id, ctx.attempt_number, duration):
                    self._notify("event.processed", ctx, "PROCESSED")
        finally:
            with self._lock:
                self._inflight.pop(index, None)

    def _fail(self, ctx: ps.EventContext, error: str, retryable: bool, duration_ms: float | None,
              outcome: AttemptOutcome = AttemptOutcome.FAILED) -> None:
        with self.session_factory() as db:
            new_status = ps.register_failure(db, ctx.id, error, retryable=retryable, duration_ms=duration_ms,
                                             outcome=outcome, attempt_number=ctx.attempt_number)
        if new_status is not None:
            kind = "event.retrying" if new_status.value == "RETRYING" else "event.dead_lettered"
            logger.warning("Event processing failed", extra={"event_id": ctx.event_id, "status": new_status.value,
                                                             "attempt": ctx.attempt_number, "error": error})
            self._notify(kind, ctx, new_status.value)

    def _notify(self, kind: str, ctx: ps.EventContext, status: str) -> None:
        self.broker.publish(kind, {"id": ctx.id, "event_id": ctx.event_id, "event_type": ctx.event_type,
                                   "source": ctx.source, "status": status})

    # ---- introspection -----------------------------------------------------
    def status(self) -> dict:
        cap = self.queue.capacity
        return {
            "running": self.running,
            "workers_configured": self.settings.EVENT_WORKER_CONCURRENCY,
            "workers_alive": sum(1 for t in self._workers if t.is_alive()),
            "sweeper_alive": bool(self._sweeper and self._sweeper.is_alive()),
            "queue_size": self.queue.size,
            "queue_capacity": cap,
            "utilization": round(self.queue.size / cap, 4) if cap else 0.0,
            "saturated": self.queue.full(),
            "sse_clients": self.broker.client_count,
        }
