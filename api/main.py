import asyncio
import os
from time import perf_counter

from fastapi import Depends, FastAPI, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.middleware.cors import CORSMiddleware
from starlette.staticfiles import StaticFiles

from audit import ensure_api_context, log_api_access, record_api_access_event_background
from config import API_LOGGING, API_VERSION, API_CORS_ORIGINS
from database import async_session_maker
from logger import logger

if API_VERSION == 1:
    from api.v1 import router as api_router, VERSION as API_DOC_VERSION
else:
    from api.v2 import VERSION as API_DOC_VERSION
    from api.v2.router import router as api_router

app = FastAPI(
    title=f"SoloBot API (Alpha) — API v{API_DOC_VERSION}",
    version=API_DOC_VERSION,
    description=f"Версия API: **v{API_DOC_VERSION}**.",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

_cors_origins = API_CORS_ORIGINS if API_CORS_ORIGINS != ["*"] else API_CORS_ORIGINS
_cors_credentials = API_CORS_ORIGINS != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_credentials,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["X-Identity-Id", "X-Token", "Content-Type", "Authorization"],
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-XSS-Protection", "1; mode=block")
    return response


@app.middleware("http")
async def api_access_log_middleware(request: Request, call_next):
    context = ensure_api_context(request)
    if not API_LOGGING:
        response = await call_next(request)
        response.headers["X-Request-Id"] = context.request_id
        return response

    started = perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        duration_ms = int((perf_counter() - started) * 1000)
        log_api_access(
            request,
            status_code=500,
            duration_ms=duration_ms,
            result="fail",
            reason=type(exc).__name__,
        )
        asyncio.create_task(
            record_api_access_event_background(
                async_session_maker,
                request,
                result="fail",
                reason=type(exc).__name__,
                status_code=500,
            )
        )
        raise

    duration_ms = int((perf_counter() - started) * 1000)
    response.headers["X-Request-Id"] = context.request_id
    result = "success" if response.status_code < 400 else "fail"
    log_api_access(
        request,
        status_code=response.status_code,
        duration_ms=duration_ms,
        result=result,
    )
    asyncio.create_task(
        record_api_access_event_background(
            async_session_maker,
            request,
            result=result,
            reason=None if response.status_code < 400 else str(response.status_code),
            status_code=response.status_code,
        )
    )
    return response


@app.get("/api/health", include_in_schema=False)
async def health():
    return {"status": "ok"}


from api.depends import get_session as _get_session, verify_identity_admin as _verify_admin


@app.get("/api/health/detailed", include_in_schema=False)
async def health_detailed(
    session: AsyncSession = Depends(_get_session),
    _identity=Depends(_verify_admin),
):
    import time
    from sqlalchemy import text
    from core.redis_cache import _get_redis

    checks: dict[str, object] = {"status": "ok", "timestamp": int(time.time())}

    try:
        await session.execute(text("SELECT 1"))
        checks["db"] = {"ok": True}
    except Exception as e:
        checks["db"] = {"ok": False, "error": str(e)[:200]}
        checks["status"] = "degraded"

    try:
        client = await _get_redis()
        if client is not None:
            await client.ping()
            checks["redis"] = {"ok": True}
        else:
            checks["redis"] = {"ok": False, "error": "unavailable"}
            checks["status"] = "degraded"
    except Exception as e:
        checks["redis"] = {"ok": False, "error": str(e)[:200]}
        checks["status"] = "degraded"

    return checks


app.include_router(api_router)

_web_uploads_dir = "static/web_uploads"
os.makedirs(_web_uploads_dir, exist_ok=True)
app.mount("/api/web/uploads", StaticFiles(directory=_web_uploads_dir), name="web_uploads")
