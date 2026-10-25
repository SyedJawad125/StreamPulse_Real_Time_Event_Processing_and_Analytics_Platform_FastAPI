# app/main.py
"""StreamPulse application: FastAPI app + lifespan (RBAC seed, event workers, maintenance)."""
from __future__ import annotations

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware

from app import database
from app.config import settings
from app.crud import auth as auth_crud
from app.crud import idempotency
from app.crud.processing import HandlerRegistry
from app.exceptions import register_exception_handlers
from app.logging_config import configure_logging
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.middleware.request_id import RequestContextMiddleware
from app.rate_limit import SlidingWindowRateLimiter
from app.routers import analytics, api_key, audit, event, health, permission, role, user
from app.seed import seed_permissions, seed_roles
from app.workers.event_broker import EventBroker, TicketStore
from app.workers.event_worker import EventWorkerManager

logger = logging.getLogger(__name__)
MAINTENANCE_INTERVAL_SECONDS = 600


def _maintenance_loop(app: FastAPI, stop: threading.Event) -> None:
    """Housekeeping: expired revoked tokens, idempotency records, idle rate-limit keys."""
    while not stop.wait(MAINTENANCE_INTERVAL_SECONDS):
        try:
            with database.SessionLocal() as db:
                auth_crud.purge_expired_revocations(db)
            with database.SessionLocal() as db:
                idempotency.purge_expired(db, settings.IDEMPOTENCY_TTL_HOURS)
            app.state.rate_limiter.cleanup()
        except Exception:  # noqa: BLE001
            logger.exception("Maintenance iteration failed")


def _seed() -> None:
    with database.SessionLocal() as db:
        seed_permissions(db)
        seed_roles(db)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings)
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    settings.LOGS_DIR.mkdir(parents=True, exist_ok=True)

    if not await run_in_threadpool(database.check_database):
        raise RuntimeError("PostgreSQL is unreachable. Check DATABASE_URL and that the service is running.")

    app.state.broker = EventBroker(settings.SSE_CLIENT_BUFFER_SIZE, settings.SSE_MAX_CLIENTS)
    # Register your business-logic handlers here, e.g.  app.state.handlers.register("order.created", handle_order)
    app.state.handlers = HandlerRegistry()
    manager = EventWorkerManager(settings, database.SessionLocal, app.state.handlers, app.state.broker)
    app.state.worker_manager = manager

    if settings.AUTO_SEED_RBAC:
        await run_in_threadpool(_seed)
    await run_in_threadpool(manager.start)

    stop_maintenance = threading.Event()
    maintenance = threading.Thread(target=_maintenance_loop, args=(app, stop_maintenance), name="maintenance", daemon=True)
    maintenance.start()
    logger.info("%s started (env=%s)", settings.APP_NAME, settings.APP_ENV)
    try:
        yield
    finally:
        stop_maintenance.set()
        await run_in_threadpool(manager.stop)
        database.engine.dispose()
        logger.info("%s stopped", settings.APP_NAME)


def create_app() -> FastAPI:
    app = FastAPI(
        title=f"{settings.APP_NAME} API", version="1.0.0",
        description="Real-time event processing & analytics platform.",
        lifespan=lifespan,
        docs_url=None if settings.IS_PRODUCTION else "/docs",
        redoc_url=None if settings.IS_PRODUCTION else "/redoc",
        openapi_url=None if settings.IS_PRODUCTION else "/openapi.json",
    )
    app.state.rate_limiter = SlidingWindowRateLimiter(window_seconds=60.0)  # API-key + login limits (per process)
    app.state.ticket_store = TicketStore()
    register_exception_handlers(app)

    # innermost -> outermost: body limit, request context (request id + access log), CORS
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.MAX_REQUEST_BODY_BYTES)
    app.add_middleware(RequestContextMiddleware)
    if settings.CORS_ORIGIN_LIST:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.CORS_ORIGIN_LIST, allow_methods=["*"], allow_headers=["*"],
            allow_credentials=False,
            expose_headers=["X-Request-ID", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining",
                            "Idempotent-Replayed"])

    app.include_router(health.router)
    for module in (user, role, permission, api_key, event, analytics, audit):
        app.include_router(module.router)
    return app


app = create_app()
