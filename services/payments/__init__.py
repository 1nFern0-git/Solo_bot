from __future__ import annotations

from typing import TYPE_CHECKING

from config import (
    CASHBACK as DEFAULT_CASHBACK,
    REFERRAL_BONUS_PERCENTAGES,
)
from core.bootstrap import MONEY_CONFIG
from database import add_payment
from database.access.resolution import resolve_user_optional
from database.referrals import get_referral_by_referred_id
from database.users import update_balance
from logger import logger


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


async def process_referrals(session: AsyncSession, user_id: int, amount: float) -> dict[int, float]:
    """Начисляет реферальные бонусы по цепочке.

    Returns: dict {referrer_id: bonus_amount} — для логирования/уведомлений.
    """
    u = await resolve_user_optional(session, user_id)
    if u is None:
        return {}

    max_levels = len(REFERRAL_BONUS_PERCENTAGES)
    current_id = u.id
    bonus_by_chain: dict[int, tuple[float, int]] = {}

    for level in range(1, max_levels + 1):
        referral = await get_referral_by_referred_id(session, current_id)
        if not referral:
            break
        referrer_id = int(referral["referrer_user_id"])
        percent = REFERRAL_BONUS_PERCENTAGES.get(level)
        if not percent:
            continue
        bonus = amount * percent if isinstance(percent, float) else percent
        bonus_by_chain[referrer_id] = (bonus, level)
        current_id = referrer_id

    result_map: dict[int, float] = {}
    for referrer_id, (bonus, lvl) in bonus_by_chain.items():
        await update_balance(session, referrer_id, float(bonus))
        await add_payment(session, tg_id=referrer_id, amount=bonus, payment_system="referral")
        logger.info(f"Начислен бонус {bonus}₽ пользователю {referrer_id} за уровень {lvl}")
        result_map[referrer_id] = bonus

    return result_map


async def process_cashback(session: AsyncSession, user_id: int, amount: float) -> float:
    """Начисляет кэшбэк на баланс пользователя.

    Returns: сумма кэшбэка (0 если отключён).
    """
    cashback_config = MONEY_CONFIG.get("CASHBACK", DEFAULT_CASHBACK)
    try:
        cashback_percent = float(cashback_config) if cashback_config not in (None, False) else 0.0
    except (TypeError, ValueError):
        cashback_percent = 0.0

    if cashback_percent <= 0:
        return 0.0

    cashback_amount = round(amount * (cashback_percent / 100))
    if cashback_amount > 0:
        await update_balance(session, user_id, cashback_amount)
        await add_payment(session, tg_id=user_id, amount=cashback_amount, payment_system="cashback")
        logger.info(f"Начислен кешбэк {cashback_amount}₽ пользователю {user_id}")

    return float(cashback_amount)
