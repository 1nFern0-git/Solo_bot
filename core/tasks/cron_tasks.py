import asyncio

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from database import async_session_maker, cancel_expired_pending_payments
from logger import logger


async def scheduled_audit_drain() -> None:
    from audit import drain_audit_redis_to_db

    try:
        drained = await drain_audit_redis_to_db(async_session_maker)
        logger.info("[AuditDrain] Ночной drain завершён, записано событий: {}", drained)
    except Exception as error:
        logger.error("[AuditDrain] Ошибка ночного drain: {}", error)


async def scheduled_stats_report() -> None:
    from handlers.admin.stats.stats_handler import send_daily_stats_report

    async with async_session_maker() as session:
        await send_daily_stats_report(session)


async def sweep_stale_payments_job() -> None:
    async with async_session_maker() as session:
        await cancel_expired_pending_payments(session)
        await session.commit()


def scheduled_audit_drain_process_runner() -> None:
    asyncio.run(scheduled_audit_drain())


def scheduled_stats_report_process_runner() -> None:
    asyncio.run(scheduled_stats_report())


def sweep_stale_payments_process_runner() -> None:
    asyncio.run(sweep_stale_payments_job())


async def cleanup_expired_gifts_job() -> None:
    from datetime import datetime

    from sqlalchemy import update as sa_update

    from database.models import Gift

    async with async_session_maker() as session:
        try:
            result = await session.execute(
                sa_update(Gift).where(Gift.expiry_time < datetime.utcnow(), Gift.is_used is False).values(is_used=True)
            )
            count = result.rowcount
            await session.commit()
            if count:
                logger.info("[GiftCleanup] Просроченных подарков помечено использованными: {}", count)
        except Exception as error:
            logger.error("[GiftCleanup] Ошибка очистки подарков: {}", error)


def cleanup_expired_gifts_process_runner() -> None:
    asyncio.run(cleanup_expired_gifts_job())


async def log_db_pool_status() -> None:
    """Раз в минуту логирует состояние пула соединений: даёт видимость «упираемся ли в лимит»."""
    try:
        from database.db import engine

        pool = engine.pool
        size = pool.size()
        checked_out = pool.checkedout()
        checked_in = getattr(pool, "checkedin", lambda: size - checked_out)()
        overflow = getattr(pool, "overflow", lambda: -1)()
        logger.info(
            "[DBPool] size={} in_use={} idle={} overflow={}",
            size,
            checked_out,
            checked_in,
            overflow,
        )
    except Exception as error:
        logger.debug("[DBPool] не удалось получить статус пула: {}", error)


AUDIT_DRAIN_TRIGGER = CronTrigger(hour=0, minute=0, timezone="Europe/Moscow")
DAILY_STATS_REPORT_TRIGGER = CronTrigger(hour=0, minute=1, timezone="Europe/Moscow")
STALE_PAYMENTS_SWEEP_TRIGGER = CronTrigger(minute=0, timezone="Europe/Moscow")
EXPIRED_GIFTS_CLEANUP_TRIGGER = CronTrigger(hour=3, minute=0, timezone="Europe/Moscow")
DB_POOL_STATUS_TRIGGER = IntervalTrigger(minutes=1)
