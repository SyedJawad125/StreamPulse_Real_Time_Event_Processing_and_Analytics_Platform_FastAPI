"""Worker manager: N async workers + a sweeper, started/stopped by the FastAPI lifespan."""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.models.event import AttemptOutcome
from app.services import processing_service as ps
from app.services.event_broker import EventBroker
from app.workers.event_queue import EventQueue

logger = logging.getLogger(__name__)


class EventWorkerManager:
    def __init__(
        self,
        settings: Settings,
        session_factory: async_sessionmaker[AsyncSession],
        registry: ps.HandlerRegistry,
        broker: EventBroker,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.registry = registry
        self.broker = broker
        self.queue = EventQueue(settings.event_queue_maxsize)
        self._stopping = asyncio.Event()
        self._workers: list[asyncio.Task[None]] = []
        self._sweeper: asyncio.Task[None] | None = None
        self.running = False

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        if self.running:
            return
        self._stopping.clear()
        async with self.session_factory() as session:
            recovered = await ps.recover_interrupted(session, self.settings)
        if recovered:
            logger.warning("Recovered %d interrupted events", recovered)
        await self.sweep_once()  # redispatch everything pending in PostgreSQL
        self._workers = [
            asyncio.create_task(self._worker_loop(i), name=f"event-worker-{i}")
            for i in range(self.settings.event_worker_concurrency)
        ]
        self._sweeper = asyncio.create_task(self._sweeper_loop(), name="event-sweeper")
        self.running = True
        logger.info("Event workers started", extra={"workers": len(self._workers)})

    async def stop(self) -> None:
        """Graceful shutdown: stop taking new work, let in-flight events finish, then cancel stragglers."""
        if not self.running:
            return
        self._stopping.set()
        tasks = [*self._workers, *([self._sweeper] if self._sweeper else [])]
        _, pending = await asyncio.wait(tasks, timeout=self.settings.event_shutdown_grace_seconds)
        for task in pending:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._workers, self._sweeper, self.running = [], None, False
        logger.info("Event workers stopped", extra={"abandoned": len(pending)})

    # ---- dispatch --------------------------------------------------------
    async def dispatch(self, ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Enqueue events; returns the subset actually queued. Un-queued events stay in the DB for the sweeper."""
        queued = {i for i in ids if self.queue.try_put(i)}
        if queued:
            async with self.session_factory() as session:
                await ps.mark_queued(session, list(queued))
        return queued

    async def sweep_once(self) -> int:
        free = self.queue.free
        if free <= 0:
            return 0
        async with self.session_factory() as session:
            ids = await ps.collect_dispatchable(session, limit=self.queue.capacity)
        return len(await self.dispatch(ids))

    # ---- loops -----------------------------------------------------------
    async def _sweeper_loop(self) -> None:
        while not self._stopping.is_set():
            try:
                await self.sweep_once()
            except Exception:  # noqa: BLE001
                logger.exception("Sweeper iteration failed")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self.settings.event_sweep_interval_seconds)
            except asyncio.TimeoutError:
                pass

    async def _worker_loop(self, index: int) -> None:
        while not self._stopping.is_set():
            try:
                event_pk = await asyncio.wait_for(self.queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            try:
                await self._process(event_pk)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - never let one event kill the worker
                logger.exception("Unexpected worker error", extra={"event_pk": str(event_pk)})
            finally:
                self.queue.task_done()

    async def _process(self, event_pk: uuid.UUID) -> None:
        async with self.session_factory() as session:
            ctx = await ps.claim_event(session, event_pk)
        if ctx is None:
            return  # already claimed / not claimable
        self._notify("event.processing", ctx.id, ctx, "PROCESSING")

        start = time.perf_counter()
        try:
            handler = self.registry.get(ctx.event_type)
            await asyncio.wait_for(handler(ctx), timeout=self.settings.event_processing_timeout_seconds)
        except asyncio.CancelledError:
            # Shutdown while processing: record the interruption (shielded) so the event is retried after restart.
            await asyncio.shield(self._fail(ctx, "Processing interrupted (shutdown)", True, None, AttemptOutcome.INTERRUPTED))
            raise
        except ps.NonRetryableProcessingError as exc:
            await self._fail(ctx, ps.sanitize_error(exc), False, (time.perf_counter() - start) * 1000)
        except asyncio.TimeoutError:
            await self._fail(ctx, "Handler timed out", True, (time.perf_counter() - start) * 1000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Event handler failed", extra={"event_id": ctx.event_id, "attempt": ctx.attempt_number,
                                                          "error": ps.sanitize_error(exc)})
            await self._fail(ctx, ps.sanitize_error(exc), True, (time.perf_counter() - start) * 1000)
        else:
            duration = (time.perf_counter() - start) * 1000
            async with self.session_factory() as session:
                if await ps.mark_success(session, ctx.id, duration):
                    self._notify("event.processed", ctx.id, ctx, "PROCESSED")

    async def _fail(self, ctx: ps.EventContext, error: str, retryable: bool, duration_ms: float | None,
                    outcome: AttemptOutcome = AttemptOutcome.FAILED) -> None:
        async with self.session_factory() as session:
            new_status = await ps.register_failure(session, self.settings, ctx.id, error, retryable=retryable,
                                                   duration_ms=duration_ms, outcome=outcome)
        if new_status is not None:
            kind = "event.retrying" if new_status.value == "RETRYING" else "event.dead_lettered"
            logger.warning("Event processing failed", extra={"event_id": ctx.event_id, "status": new_status.value,
                                                             "attempt": ctx.attempt_number, "error": error})
            self._notify(kind, ctx.id, ctx, new_status.value)

    def _notify(self, kind: str, pk: uuid.UUID, ctx: ps.EventContext, status: str) -> None:
        self.broker.publish(kind, {"id": str(pk), "event_id": ctx.event_id, "event_type": ctx.event_type,
                                   "source": ctx.source, "status": status})

    # ---- introspection -----------------------------------------------------
    def status(self) -> dict:
        alive = sum(1 for t in self._workers if not t.done())
        cap = self.queue.capacity
        return {
            "running": self.running,
            "workers_configured": self.settings.event_worker_concurrency,
            "workers_alive": alive,
            "sweeper_alive": bool(self._sweeper and not self._sweeper.done()),
            "queue_size": self.queue.size,
            "queue_capacity": cap,
            "utilization": round(self.queue.size / cap, 4) if cap else 0.0,
            "saturated": self.queue.full(),
            "sse_clients": self.broker.client_count,
        }
