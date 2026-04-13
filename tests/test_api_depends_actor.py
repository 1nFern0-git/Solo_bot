import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from starlette.requests import Request

from api.depends import bind_identity_actor, get_request_actor
from database.access.resolution import ActorSurface, ResolvedActor


def _make_request() -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
        "query_string": b"",
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "http_version": "1.1",
    }
    return Request(scope)


class ApiDependsActorBindingTests(unittest.IsolatedAsyncioTestCase):
    async def test_bind_identity_actor_sets_request_state_and_calls_audit_setter(self):
        request = _make_request()
        session = object()
        identity = SimpleNamespace(id="ident-100")
        resolved = ResolvedActor(
            surface=ActorSurface.WEB,
            billing_user_id=100,
            telegram_chat_id=7001,
            identity_id="ident-100",
        )

        with patch("api.depends.resolve_actor_from_identity", new=AsyncMock(return_value=resolved)):
            with patch("api.depends.set_api_actor") as set_api_actor_mock:
                actor = await bind_identity_actor(request, session, identity)

        self.assertEqual(actor, resolved)
        self.assertEqual(get_request_actor(request), resolved)
        set_api_actor_mock.assert_called_once_with(
            request,
            identity_id="ident-100",
            tg_id=7001,
        )

    async def test_get_request_actor_returns_none_when_request_missing(self):
        self.assertIsNone(get_request_actor(None))
