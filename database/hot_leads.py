from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.constants import PAYMENT_SYSTEMS_EXCLUDED
from database.models import Key, Payment, User


async def get_hot_leads(session: AsyncSession):
    now_ms = func.extract("epoch", func.now()) * 1000

    sub_active = select(Key.user_id).where(Key.expiry_time > now_ms).distinct()

    stmt = (
        select(Payment.user_id)
        .join(User, User.id == Payment.user_id)
        .distinct()
        .where(User.trial == 1)
        .where(Payment.amount > 0)
        .where(Payment.status == "success")
        .where(Payment.payment_system.notin_(PAYMENT_SYSTEMS_EXCLUDED))
        .where(~Payment.user_id.in_(sub_active))
    )

    result = await session.execute(stmt)
    return result.scalars().all()
