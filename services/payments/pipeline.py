from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sqlalchemy import select

from database import (
    add_payment,
    async_session_maker,
    get_payment_by_payment_id,
    invalidate_payment_cache,
    update_balance,
    update_payment_status,
)
from database.models import Payment
from handlers.payments.utils import send_payment_success_notification
from logger import logger


if TYPE_CHECKING:
    pass


@dataclass
class ParsedPayment:
    """Нормализованный результат парсинга webhook-payload'а провайдера."""

    payment_id: str
    tg_id: int | None
    amount: float
    currency: str = "RUB"
    metadata: dict | None = field(default=None)


@dataclass
class PipelineResult:
    """Что pipeline вернул адаптеру — для корректного HTTP-ответа."""

    ok: bool
    already_processed: bool = False
    error: str | None = None


async def process_success_payment(
    provider: str,
    parsed: ParsedPayment,
    *,
    metadata_patch: dict | None = None,
    credit_amount_override: float | None = None,
    update_currency: str | None = None,
    update_original_amount: float | None = None,
) -> PipelineResult:
    """Идемпотентно переводит платёж в success, зачисляет баланс, уведомляет.

    Открывает одну транзакцию на всю операцию — если что-то упадёт, всё
    откатывается атомарно.

    ``provider`` — строка для колонки ``payments.payment_system`` (регистр
    важен, некоторые провайдеры исторически писали как "YOOMONEY"/"HELEKET",
    см. комментарии в конкретных адаптерах).

    ``metadata_patch`` — опциональный dict, который ПАТЧИТ (merge) существующий
    ``payments.metadata_`` для провайдера у которых метадата приходит только
    в webhook'е (cryptobot: FX rate, invoice_id, paid amount).

    ``credit_amount_override`` — зачислить на баланс сумму, отличную от
    ``parsed.amount``. Нужно для cryptobot: провайдер возвращает paid_amount
    в USDT, но баланс пополняется исходной RUB-суммой из pending-записи.

    ``update_currency`` / ``update_original_amount`` — дополняют ``Payment``
    row для crypto-платежей (зафиксировать реально списанную валюту).
    """
    try:
        async with async_session_maker() as session:
            payment = await get_payment_by_payment_id(session, parsed.payment_id)

            if payment and payment.get("status") == "success":
                logger.info(f"[{provider}] Повторный webhook, платёж уже обработан: payment_id={parsed.payment_id}")
                return PipelineResult(ok=True, already_processed=True)

            if payment and payment.get("id") is not None:
                updated = await update_payment_status(
                    session=session,
                    internal_id=int(payment["id"]),
                    new_status="success",
                    metadata_patch=metadata_patch,
                )
                if not updated:
                    logger.error(f"[{provider}] Не удалось перевести платёж id={payment['id']} в success")
                    return PipelineResult(ok=False, error="update_payment_status failed")
                tg_id = parsed.tg_id if parsed.tg_id is not None else int(payment["tg_id"])

                if update_currency is not None or update_original_amount is not None:
                    row = (
                        await session.execute(select(Payment).where(Payment.id == int(payment["id"])).limit(1))
                    ).scalar_one_or_none()
                    if row is not None:
                        if update_currency is not None:
                            row.currency = update_currency
                        if update_original_amount is not None:
                            row.original_amount = update_original_amount
            else:
                await add_payment(
                    session=session,
                    tg_id=parsed.tg_id,
                    amount=parsed.amount,
                    payment_system=provider,
                    status="success",
                    currency=parsed.currency,
                    payment_id=parsed.payment_id,
                    metadata=parsed.metadata or metadata_patch,
                )
                tg_id = parsed.tg_id

            credit_amount = float(credit_amount_override) if credit_amount_override is not None else parsed.amount
            if tg_id is not None and credit_amount > 0:
                await update_balance(session, tg_id, credit_amount)
                await send_payment_success_notification(tg_id, credit_amount, session)

            await session.commit()
            await invalidate_payment_cache(parsed.payment_id)

        logger.info(
            f"[{provider}] Платёж обработан: payment_id={parsed.payment_id}, "
            f"tg_id={tg_id}, amount={credit_amount} (parsed={parsed.amount} {parsed.currency})"
        )
        return PipelineResult(ok=True)
    except Exception as e:
        logger.error(f"[{provider}] Ошибка обработки успешного платежа: {e}")
        return PipelineResult(ok=False, error=str(e))


async def process_cancelled_payment(
    provider: str,
    parsed: ParsedPayment,
    *,
    new_status: str = "cancelled",
) -> PipelineResult:
    """Переводит платёж в cancelled/failed либо записывает его сразу в этом статусе.

    ``new_status`` — обычно "cancelled" (пользователь отменил) или "failed"
    (провайдер вернул ошибку/wrong_amount/system_fail).
    """
    try:
        async with async_session_maker() as session:
            payment = await get_payment_by_payment_id(session, parsed.payment_id)

            if payment and payment.get("status") in ("cancelled", "failed", "success"):
                return PipelineResult(ok=True, already_processed=True)

            if payment and payment.get("id") is not None:
                updated = await update_payment_status(
                    session=session,
                    internal_id=int(payment["id"]),
                    new_status=new_status,
                )
                if not updated:
                    return PipelineResult(ok=False, error="update_payment_status failed")
            else:
                await add_payment(
                    session=session,
                    tg_id=parsed.tg_id,
                    amount=parsed.amount,
                    payment_system=provider,
                    status=new_status,
                    currency=parsed.currency,
                    payment_id=parsed.payment_id,
                    metadata=parsed.metadata,
                )

            await session.commit()
            await invalidate_payment_cache(parsed.payment_id)

        logger.info(f"[{provider}] Платёж {parsed.payment_id} помечен как {new_status}")
        return PipelineResult(ok=True)
    except Exception as e:
        logger.error(f"[{provider}] Ошибка при обработке отмены платежа: {e}")
        return PipelineResult(ok=False, error=str(e))
