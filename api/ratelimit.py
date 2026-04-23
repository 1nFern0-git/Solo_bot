from __future__ import annotations

from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from api.depends import _identity_from_cookie


async def enforce_rate_limit(
    request: Request,
    session: AsyncSession,
    *,
    bucket: str,
    max_per_window: int,
    window_sec: int,
    identity_aware: bool = True,
) -> None:
    try:
        from api.v2.routes.auth._fallback_limiter import check_and_increment
        from core.redis_cache import cache_incr_checked
    except Exception:
        return

    owner = "anon"
    if identity_aware:
        try:
            identity = await _identity_from_cookie(session, request)
            if identity is not None and getattr(identity, "id", None):
                owner = f"id:{identity.id}"
        except Exception:
            pass

    if owner == "anon":
        ip = (request.client.host if request.client else "") or "unknown"
        owner = f"ip:{ip}"

    key = f"rl:{bucket}:{owner}"
    try:
        count, redis_ok = await cache_incr_checked(key, window_sec)
        if not redis_ok:
            count = check_and_increment(key, max_per_window, window_sec)
    except Exception:
        return

    if count > max_per_window:
        raise HTTPException(status_code=429, detail="Слишком много запросов, подождите и попробуйте снова")


def rate_limit_dependency(*, bucket: str, max_per_window: int, window_sec: int):
    from api.depends import get_session
    from fastapi import Depends

    async def _dep(request: Request, session: AsyncSession = Depends(get_session)) -> None:
        await enforce_rate_limit(
            request,
            session,
            bucket=bucket,
            max_per_window=max_per_window,
            window_sec=window_sec,
        )

    return _dep
