from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import (
    BlockedUser,
    CouponUsage,
    Gift,
    GiftUsage,
    Key,
    ManualBan,
    Notification,
    Payment,
    Referral,
    TemporaryData,
    User,
)


def mirror_telegram_id(user: User | None) -> int | None:
    if user is None:
        return None
    return user.tg_id


async def refresh_tg_mirrors_for_user(session: AsyncSession, user_id: int) -> None:
    r = await session.execute(select(User.tg_id).where(User.id == user_id))
    tg = r.scalar_one_or_none()

    await session.execute(update(Key).where(Key.user_id == user_id).values(tg_id=tg))
    await session.execute(update(Payment).where(Payment.user_id == user_id).values(tg_id=tg))
    await session.execute(update(Notification).where(Notification.user_id == user_id).values(tg_id=tg))
    await session.execute(update(GiftUsage).where(GiftUsage.user_id == user_id).values(tg_id=tg))
    await session.execute(update(CouponUsage).where(CouponUsage.user_id == user_id).values(tg_id=tg))
    await session.execute(update(TemporaryData).where(TemporaryData.user_id == user_id).values(tg_id=tg))
    await session.execute(update(BlockedUser).where(BlockedUser.user_id == user_id).values(tg_id=tg))
    await session.execute(update(ManualBan).where(ManualBan.user_id == user_id).values(tg_id=tg))

    await session.execute(
        update(Referral).where(Referral.referred_user_id == user_id).values(referred_tg_id=tg)
    )
    await session.execute(
        update(Referral).where(Referral.referrer_user_id == user_id).values(referrer_tg_id=tg)
    )

    await session.execute(update(Gift).where(Gift.sender_user_id == user_id).values(sender_tg_id=tg))
    await session.execute(
        update(Gift).where(Gift.recipient_user_id == user_id).values(recipient_tg_id=tg)
    )
