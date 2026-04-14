from . import admin, user  # noqa: F401 — import triggers endpoint registration
from ._common import router, user_router


__all__ = ["router", "user_router"]
