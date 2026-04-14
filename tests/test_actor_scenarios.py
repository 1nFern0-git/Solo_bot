import unittest

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from database.access.resolution import (
    ActorSurface,
    resolve_actor_from_identity,
    resolve_actor_from_legacy_ref,
)


class ActorScenarioTests(unittest.IsolatedAsyncioTestCase):
    async def test_tg_only_user_detected_as_telegram_surface(self):
        session = object()
        user = SimpleNamespace(id=1, tg_id=1001, identity_id="ident-tg")
        with patch("database.access.resolution.resolve_user_optional", new=AsyncMock(return_value=user)):
            actor = await resolve_actor_from_legacy_ref(session, 1001)
        self.assertEqual(actor.surface, ActorSurface.TELEGRAM)
        self.assertEqual(actor.billing_user_id, 1)
        self.assertEqual(actor.telegram_chat_id, 1001)

    async def test_web_only_user_detected_as_web_surface(self):
        session = object()
        user = SimpleNamespace(id=2, tg_id=None, identity_id="ident-web")
        with patch("database.access.resolution.resolve_user_optional", new=AsyncMock(return_value=user)):
            actor = await resolve_actor_from_legacy_ref(session, 2)
        self.assertEqual(actor.surface, ActorSurface.WEB)
        self.assertEqual(actor.billing_user_id, 2)
        self.assertIsNone(actor.telegram_chat_id)

    async def test_linked_user_is_web_by_identity_and_telegram_by_tg(self):
        session = object()
        identity = SimpleNamespace(id="ident-linked")
        linked_user = SimpleNamespace(id=3, tg_id=1003, identity_id="ident-linked")

        with patch("database.identities.ensure_billing_user_for_identity", new=AsyncMock(return_value=3)):
            with patch("database.access.resolution.resolve_user_optional", new=AsyncMock(return_value=linked_user)):
                web_actor = await resolve_actor_from_identity(session, identity)

        with patch("database.access.resolution.resolve_user_optional", new=AsyncMock(return_value=linked_user)):
            tg_actor = await resolve_actor_from_legacy_ref(session, 1003)

        self.assertEqual(web_actor.surface, ActorSurface.WEB)
        self.assertEqual(web_actor.billing_user_id, 3)
        self.assertEqual(web_actor.telegram_chat_id, 1003)
        self.assertEqual(tg_actor.surface, ActorSurface.TELEGRAM)
        self.assertEqual(tg_actor.billing_user_id, 3)
        self.assertEqual(tg_actor.telegram_chat_id, 1003)
