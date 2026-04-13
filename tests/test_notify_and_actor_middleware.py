import unittest
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database.access.resolution import notify_telegram_chat_id

_ACTOR_SPEC = spec_from_file_location(
    "actor_module_for_tests",
    str(Path(__file__).resolve().parents[1] / "middlewares" / "actor.py"),
)
_ACTOR_MODULE = module_from_spec(_ACTOR_SPEC)
assert _ACTOR_SPEC is not None and _ACTOR_SPEC.loader is not None
sys.modules["actor_module_for_tests"] = _ACTOR_MODULE
_ACTOR_SPEC.loader.exec_module(_ACTOR_MODULE)
ActorMiddleware = _ACTOR_MODULE.ActorMiddleware


class NotifyTelegramChatIdTests(unittest.IsolatedAsyncioTestCase):
    async def test_returns_user_tg_when_user_has_telegram(self):
        session = object()
        user = SimpleNamespace(tg_id=555)
        with patch("database.access.resolution.resolve_user_optional", new=AsyncMock(return_value=user)):
            value = await notify_telegram_chat_id(session, 100)
        self.assertEqual(value, 555)

    async def test_returns_legacy_ref_when_user_missing(self):
        session = object()
        with patch("database.access.resolution.resolve_user_optional", new=AsyncMock(return_value=None)):
            value = await notify_telegram_chat_id(session, 777)
        self.assertEqual(value, 777)

    async def test_returns_none_when_user_exists_without_tg(self):
        session = object()
        user = SimpleNamespace(tg_id=None)
        with patch("database.access.resolution.resolve_user_optional", new=AsyncMock(return_value=user)):
            value = await notify_telegram_chat_id(session, 11)
        self.assertIsNone(value)


class ActorMiddlewareTests(unittest.IsolatedAsyncioTestCase):
    async def test_sets_actor_for_non_bot_user(self):
        middleware = ActorMiddleware()
        from_user = SimpleNamespace(id=123, is_bot=False)
        data = {"event_from_user": from_user, "session": SimpleNamespace(execute=object())}

        async def handler(event, payload):
            return payload.get("actor")

        resolved_actor = SimpleNamespace(surface="telegram", billing_user_id=10, telegram_chat_id=123, identity_id=None)
        with patch("actor_module_for_tests.resolve_actor_from_legacy_ref", new=AsyncMock(return_value=resolved_actor)):
            result = await middleware(handler, object(), data)

        self.assertEqual(result, resolved_actor)
        self.assertEqual(data.get("actor"), resolved_actor)

    async def test_skips_actor_when_event_user_missing(self):
        middleware = ActorMiddleware()
        data = {"session": object()}

        async def handler(event, payload):
            return payload.get("actor")

        with patch("actor_module_for_tests.resolve_actor_from_legacy_ref", new=AsyncMock()) as resolver_mock:
            result = await middleware(handler, object(), data)

        self.assertIsNone(result)
        resolver_mock.assert_not_called()
