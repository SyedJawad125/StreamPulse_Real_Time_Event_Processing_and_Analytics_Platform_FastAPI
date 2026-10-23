"""StreamPulse application factory and lifespan (DB engine, RBAC seed, event workers)."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health
from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.rate_limit import SlidingWindowRateLimiter
from app.database import check_database, create_engine, create_session_factory
from app.middleware.body_limit import BodySizeLimitMiddleware
from app.middleware.request_id import RequestContextMiddleware
from app.services import auth_service, idempotency_service
from app.services.event_broker import EventBroker
from app.services.processing_service import HandlerRegistry
from app.services.rbac_seed import seed_rbac
from app.workers.event_worker import EventWorkerManager

logger = logging.getLogger(__name__)
MAINTENANCE_INTERVAL_SECONDS = 600


async def _maintenance_loop(app: FastAPI) -> None:
    """Periodic housekeeping: expired revoked tokens, idempotency records, idle rate-limit keys."""
    while True:
        await asyncio.sleep(MAINTENANCE_INTERVAL_SECONDS)
        try:
            async with app.state.session_factory() as session:
                await auth_service.purge_expired_revocations(session)
            async with app.state.session_factory() as session:
                await idempotency_service.purge_expired(session, app.state.settings.idempotency_ttl_hours)
            app.state.rate_limiter.cleanup()
            app.state.login_limiter.cleanup()
        except Exception:  # noqa: BLE001
            logger.exception("Maintenance iteration failed")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    configure_logging(settings)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.logs_dir.mkdir(parents=True, exist_ok=True)

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    app.state.engine, app.state.session_factory = engine, session_factory

    if not await check_database(engine, timeout=5.0):
        await engine.dispose()
        raise RuntimeError("PostgreSQL is unreachable. Check DATABASE_URL and that the service is running.")

    app.state.broker = EventBroker(settings.sse_client_buffer_size, settings.sse_max_clients)
    app.state.handlers = HandlerRegistry()
    manager = EventWorkerManager(settings, session_factory, app.state.handlers, app.state.broker)
    app.state.worker_manager = manager

    if settings.auto_seed_rbac:
        await seed_rbac(session_factory)
    await manager.start()
    maintenance = asyncio.create_task(_maintenance_loop(app), name="maintenance")
    logger.info("%s started (env=%s)", settings.app_name, settings.app_env)
    try:
        yield
    finally:
        maintenance.cancel()
        await asyncio.gather(maintenance, return_exceptions=True)
        await manager.stop()
        await engine.dispose()
        logger.info("%s stopped", settings.app_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title=f"{settings.app_name} API",
        version="1.0.0",
        description="Real-time event processing & analytics platform.",
        lifespan=lifespan,
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )
    app.state.settings = settings
    app.state.rate_limiter = SlidingWindowRateLimiter(window_seconds=60.0)  # API-key limits (per process)
    app.state.login_limiter = app.state.rate_limiter  # same class; distinct key namespaces
    app.state.stream_tickets = {}

    register_exception_handlers(app)
    # Added innermost -> outermost: body limit, request context, CORS.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=settings.max_request_body_bytes)
    app.add_middleware(RequestContextMiddleware)
    if settings.cors_origin_list:
        app.add_middleware(
            CORSMiddleware, allow_origins=settings.cors_origin_list, allow_methods=["*"], allow_headers=["*"],
            allow_credentials=False,
            expose_headers=["X-Request-ID", "Retry-After", "X-RateLimit-Limit", "X-RateLimit-Remaining",
                            "Idempotent-Replayed"],
        )

    app.include_router(health.router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
