from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import exists, or_, select

from database import add_notification, check_notifications_bulk, delete_key, delete_notification, get_last_notification_times_bulk
from database.models import Key
from database.models.users import BlockedUser, ManualBan
from handlers.notifications.context import NotificationContext
from handlers.notifications.keyboards import build_notification_expired_kb, build_notification_kb
from handlers.notifications.renewal import RenewalStatus, try_auto_renew
from handlers.notifications.sender import send_notification
from handlers.texts import KEY_DELETED_MSG, KEY_EXPIRED_DELAY_MSG, KEY_EXPIRED_NO_DELAY_MSG
from handlers.utils import format_hours, format_minutes
from logger import logger
from services.operations import delete_key_from_cluster

from .expiring import _send_renewed


async def process_expired_keys(
    ctx: NotificationContext,
    keys: list,
    notify_renew_expired: bool,
    notify_delete_key: bool,
    delete_delay_minutes: int,
):
    expired_keys = [k for k in keys if k.expiry_time and k.expiry_time < ctx.current_time]

    try:
        blocked_expired = await _get_blocked_expired_keys(ctx.session, ctx.current_time)
        if blocked_expired:
            existing_ids = {k.client_id for k in expired_keys}
            for bk in blocked_expired:
                if bk.client_id not in existing_ids:
                    expired_keys.append(bk)
            logger.info(f"[Expired] +{len(blocked_expired)} ключей заблокированных")
    except Exception as e:
        logger.error(f"Ошибка получения ключей заблокированных: {e}")

    if not expired_keys:
        return

    logger.info(f"[Expired] Найдено {len(expired_keys)} истекших ключей")

    tg_ids = [k.tg_id for k in expired_keys]
    emails = [k.email or "" for k in expired_keys]
    users = await check_notifications_bulk(ctx.session, "key_expired", 0, tg_ids=tg_ids, emails=emails)
    users_set = {(u["tg_id"], u["email"]) for u in users}

    notification_pairs = [(k.tg_id, f"{k.email or ''}_key_expired") for k in expired_keys]
    last_times = await get_last_notification_times_bulk(ctx.session, notification_pairs)

    for key in expired_keys:
        tg_id = key.tg_id
        email = key.email or ""
        client_id = key.client_id
        server_id = key.server_id
        notification_id = f"{email}_key_expired"
        last_notification_time = last_times.get((tg_id, notification_id))

        expired_ms = ctx.current_time - key.expiry_time
        delay_ms = delete_delay_minutes * 60 * 1000
        is_grace = notify_delete_key and delete_delay_minutes > 0 and expired_ms < delay_ms
        is_delete = not is_grace

        if notify_renew_expired:
            try:
                result = await try_auto_renew(ctx, key)

                if result.status == RenewalStatus.SUCCESS:
                    await _send_renewed(ctx, key, result.tariff, result.new_expiry_time)
                    if ctx.bulk_updates:
                        ctx.bulk_updates["notifications_to_delete"].append((tg_id, notification_id))
                    else:
                        await delete_notification(ctx.session, tg_id, notification_id)
                    continue

            except Exception as e:
                logger.error(f"Ошибка продления для {tg_id}: {e}")
                continue

        if is_grace:
            if last_notification_time is None and (tg_id, email) in users_set:
                remaining_ms = delay_ms - expired_ms
                remaining_minutes = max(1, int(remaining_ms / (60 * 1000)))
                await _send_expired_grace(ctx, key, remaining_minutes)
                await add_notification(ctx.session, tg_id, notification_id)
            continue

        if is_delete and notify_delete_key:
            should_delete = False
            if delete_delay_minutes == 0:
                should_delete = True
            elif last_notification_time is not None:
                minutes_passed = expired_ms / (60 * 1000)
                should_delete = minutes_passed >= delete_delay_minutes

            if should_delete:
                try:
                    await delete_key_from_cluster(server_id, email, client_id, ctx.session)
                    await delete_key(ctx.session, client_id)
                    logger.info(f"Ключ {client_id} для {tg_id} удалён")
                    await _send_deleted(ctx, key)
                except Exception as e:
                    logger.error(f"Ошибка удаления ключа {client_id}: {e}")
                continue

        if last_notification_time is None and (tg_id, email) in users_set:
            await _send_expired(ctx, key, delete_delay_minutes)
            await add_notification(ctx.session, tg_id, notification_id)

    logger.info("[Expired] Обработка завершена")


async def _get_blocked_expired_keys(session, current_time: int) -> list:
    stmt = (
        select(Key)
        .where(
            Key.is_frozen.is_(False),
            Key.expiry_time.isnot(None),
            Key.expiry_time < current_time,
            or_(
                exists().where(BlockedUser.tg_id == Key.tg_id),
                exists().where(
                    ManualBan.tg_id == Key.tg_id,
                    or_(ManualBan.until.is_(None), ManualBan.until > datetime.now(timezone.utc)),
                ),
            ),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _send_expired_grace(ctx: NotificationContext, key, remaining_minutes: int) -> bool:
    email = key.email or ""
    hours = remaining_minutes // 60
    minutes = remaining_minutes % 60
    if hours > 0 and minutes > 0:
        time_formatted = f"{format_hours(hours)} и {format_minutes(minutes)}"
    elif hours > 0:
        time_formatted = format_hours(hours)
    else:
        time_formatted = format_minutes(minutes)

    text = KEY_EXPIRED_DELAY_MSG.format(email=email, time_formatted=time_formatted)
    keyboard = build_notification_kb(email, getattr(key, "client_id", None))
    return await send_notification(ctx.bot, key.tg_id, "notify_expired.jpg", text, keyboard)


async def _send_expired(ctx: NotificationContext, key, delay_minutes: int) -> bool:
    email = key.email or ""
    if delay_minutes > 0:
        hours = delay_minutes // 60
        minutes = delay_minutes % 60
        if hours > 0 and minutes > 0:
            time_formatted = f"{format_hours(hours)} и {format_minutes(minutes)}"
        elif hours > 0:
            time_formatted = format_hours(hours)
        else:
            time_formatted = format_minutes(minutes)
        text = KEY_EXPIRED_DELAY_MSG.format(email=email, time_formatted=time_formatted)
    else:
        text = KEY_EXPIRED_NO_DELAY_MSG.format(email=email)

    keyboard = build_notification_kb(email, getattr(key, "client_id", None))
    return await send_notification(ctx.bot, key.tg_id, "notify_expired.jpg", text, keyboard)


async def _send_deleted(ctx: NotificationContext, key) -> bool:
    email = key.email or ""
    text = KEY_DELETED_MSG.format(email=email)
    keyboard = build_notification_expired_kb()
    return await send_notification(ctx.bot, key.tg_id, "notify_expired.jpg", text, keyboard)
