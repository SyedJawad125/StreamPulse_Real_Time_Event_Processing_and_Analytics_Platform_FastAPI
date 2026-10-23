"""Health endpoints (mounted at the application root, not under /api/v1)."""
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.database import check_database

router = APIRouter(tags=["Health"])
_STARTED = time.monotonic()


async def _state(request: Request) -> tuple[bool, dict]:
    app = request.app
    db_ok = await check_database(app.state.engine, timeout=3.0)
    worker = app.state.worker_manager.status()
    worker_ok = worker["running"] and worker["workers_alive"] == worker["workers_configured"] and worker["sweeper_alive"]
    body = {
        "status": "ok" if (db_ok and worker_ok) else "unavailable",
        "app": app.state.settings.app_name,
        "environment": app.state.settings.app_env,
        "uptime_seconds": round(time.monotonic() - _STARTED, 1),
        "checks": {
            "database": "ok" if db_ok else "down",
            "workers": "ok" if worker_ok else "down",
            "queue": "saturated" if worker["saturated"] else "ok",
        },
        "worker": worker,
    }
    return db_ok and worker_ok, body


@router.get("/health", summary="Overall health with component detail")
async def health(request: Request) -> JSONResponse:
    ok, body = await _state(request)
    return JSONResponse(body, status_code=200 if ok else 503)


@router.get("/health/live", summary="Liveness: the process is up")
async def live() -> dict:
    return {"status": "alive"}


@router.get("/health/ready", summary="Readiness: PostgreSQL reachable and workers running")
async def ready(request: Request) -> JSONResponse:
    ok, body = await _state(request)
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": body["checks"]},
                        status_code=200 if ok else 503)
