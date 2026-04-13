from ._common import router, user_router
from . import admin, user  # noqa: F401 — import triggers endpoint registration

__all__ = ["router", "user_router"]
