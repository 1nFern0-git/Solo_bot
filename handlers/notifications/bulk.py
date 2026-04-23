from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database import bulk_add_notifications, bulk_delete_notifications
from database.models import Key
from logger import logger


def create_bulk_updates() -> dict[str, Any]:
    return {
        "balance_changes": {},
        "key_expiry_updates": [],
        "key_tariff_updates": [],
        "notifications_to_add": [],
        "notifications_to_delete": [],
    }


async def execute_bulk_updates(session: AsyncSession, bulk_updates: dict[str, Any]) -> None:
    try:
        balance_changes = bulk_updates.get("balance_changes") or {}
        if balance_changes:
            tg_ids = list(balance_changes.keys())
            changes = [balance_changes[tg_id] for tg_id in tg_ids]
            await session.execute(
                text(
                    "UPDATE users SET balance = balance + v.change FROM "
                    "(SELECT unnest(CAST(:tg_ids AS bigint[])) AS tg_id, unnest(CAST(:changes AS double precision[])) AS change) AS v "
                    "WHERE users.tg_id = v.tg_id"
                ),
                {"tg_ids": tg_ids, "changes": changes},
            )
            logger.info(f"Bulk: обновлено {len(balance_changes)} балансов")

        key_expiry = bulk_updates.get("key_expiry_updates") or []
        if key_expiry:
            await session.run_sync(
                lambda sync_sess: sync_sess.bulk_update_mappings(
                    Key,
                    [{"client_id": cid, "expiry_time": exp} for cid, exp in key_expiry],
                )
            )
            logger.info(f"Bulk: обновлено {len(key_expiry)} сроков действия ключей")

        key_tariff = bulk_updates.get("key_tariff_updates") or []
        if key_tariff:
            await session.run_sync(
                lambda sync_sess: sync_sess.bulk_update_mappings(
                    Key,
                    [{"client_id": cid, "tariff_id": tid} for cid, tid in key_tariff],
                )
            )
            logger.info(f"Bulk: обновлено {len(key_tariff)} тарифов ключей")

        to_add = bulk_updates.get("notifications_to_add") or []
        if to_add:
            await bulk_add_notifications(session, to_add, commit=False)

        to_delete = bulk_updates.get("notifications_to_delete") or []
        if to_delete:
            await bulk_delete_notifications(session, to_delete, commit=False)

        if to_add or to_delete:
            logger.info(f"Bulk: {len(to_add)} добавлений, {len(to_delete)} удалений уведомлений")

        await session.commit()

    except Exception as error:
        logger.error(f"Ошибка в bulk-обновлениях: {error}")
        try:
            await session.rollback()
        except Exception:
            pass
        raise
