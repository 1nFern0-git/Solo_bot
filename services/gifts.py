from __future__ import annotations

import uuid

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from database import (
    add_referral,
    get_balance,
    get_referral_by_referred_id,
    store_gift_link,
    update_balance,
    update_trial,
)
from database.access.resolution import resolve_user_optional
from database.gifts import (
    count_gift_usages,
    get_gift_locked,
    get_gift_usage,
    mark_gift_fully_redeemed,
    record_gift_usage,
)
from database.tariffs import get_tariff_by_id
from logger import logger
from services.formatting import format_days, format_months, get_gift_link, get_site_gift_link

from .errors import InsufficientFundsError, NotFoundError, ValidationError


if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession


@dataclass
class GiftRedeemResult:
    message: str
    gift_id: str
    tariff_id: int
    duration_days: int


@dataclass
class GiftCreateResult:
    gift_id: str
    gift_link: str
    site_gift_link: str
    tariff_name: str
    duration_days: int
    duration_text: str
    expiry_time: datetime
    price_charged: int


def normalize_gift_code(raw: str) -> str:
    s = raw.strip()
    if not s:
        return ""
    if "/gift/" in s:
        from_url = s.split("/gift/")[-1]
        s = from_url.split("?")[0].split("#")[0].strip()
    if s.startswith("gift_"):
        s = s[5:].strip()
    for prefix in ("start=gift_", "start="):
        idx = s.find(prefix)
        if idx >= 0:
            token = s[idx + len(prefix) :]
            return token.split("&")[0].split("?")[0].split("#")[0].strip()
    return s.split("?")[0].split("#")[0].strip()


def _format_duration(days: int) -> str:
    return format_months(days // 30) if days % 30 == 0 else format_days(days)


async def redeem_gift(
    session: AsyncSession,
    gift_code: str,
    billing_user_ref: int,
) -> GiftRedeemResult:
    """Активирует подарок для пользователя.

    Создаёт ключ, записывает usage, привязывает реферала.
    Raises: ValidationError, NotFoundError
    """
    code = normalize_gift_code(gift_code)
    if not code:
        raise ValidationError("Укажите ссылку или код подарка")

    gift_info = await get_gift_locked(session, code)
    if not gift_info:
        raise NotFoundError("Подарок не найден или срок ссылки истёк")

    wu = await resolve_user_optional(session, billing_user_ref)
    if wu is None:
        raise NotFoundError("Пользователь не найден")

    if gift_info.expiry_time and gift_info.expiry_time < datetime.utcnow():
        raise ValidationError("Срок действия подарка истёк")

    if gift_info.sender_user_id == wu.id:
        raise ValidationError("Нельзя активировать подарок, который вы создали сами")

    if await get_gift_usage(session, gift_info.gift_id, wu.id) is not None:
        raise ValidationError("Вы уже активировали этот подарок")

    if gift_info.recipient_user_id and not gift_info.is_unlimited:
        raise ValidationError("Этот подарок уже был активирован другим пользователем")

    if not gift_info.is_unlimited:
        usage_count = await count_gift_usages(session, gift_info.gift_id)
        if (
            gift_info.is_used
            or (gift_info.max_usages is not None and usage_count >= gift_info.max_usages)
            or (gift_info.max_usages is None and gift_info.recipient_user_id is not None)
        ):
            raise ValidationError("Этот подарок уже был использован")

    existing_referral = await get_referral_by_referred_id(session, wu.id)
    if not existing_referral and gift_info.sender_user_id:
        await add_referral(session, wu.id, gift_info.sender_user_id)

    await update_trial(session, wu.id, 1)

    tariff = await get_tariff_by_id(session, int(gift_info.tariff_id)) if gift_info.tariff_id else None
    if not tariff:
        raise NotFoundError("Тариф, связанный с подарком, не найден")

    from services.keys import create_vpn_key_headless

    duration_days = int(tariff["duration_days"] or 0)
    expiry_time = datetime.now(timezone.utc) + timedelta(days=duration_days)

    selected_device_limit = getattr(gift_info, "selected_device_limit", None)
    selected_traffic_gb = getattr(gift_info, "selected_traffic_gb", None)
    selected_price_rub = getattr(gift_info, "selected_price_rub", None)

    await create_vpn_key_headless(
        session=session,
        tg_id=wu.id,
        expiry_time=expiry_time,
        plan=int(tariff["id"]),
        selected_device_limit=int(selected_device_limit) if selected_device_limit is not None else None,
        selected_traffic_gb=int(selected_traffic_gb) if selected_traffic_gb is not None else None,
        selected_price_rub=int(selected_price_rub) if selected_price_rub is not None else None,
        skip_balance_charge=True,
    )

    await record_gift_usage(session, gift_info.gift_id, wu.id, wu.tg_id)

    if not gift_info.is_unlimited:
        usage_count = await count_gift_usages(session, gift_info.gift_id)
        if gift_info.max_usages and usage_count >= gift_info.max_usages:
            await mark_gift_fully_redeemed(session, code, wu.id, wu.tg_id)

    duration_text = _format_duration(duration_days)

    try:
        from database.web_notifications import notify_web

        await notify_web(
            session,
            tg_id=wu.tg_id,
            type="gift_received",
            template_vars={"name": tariff["name"], "duration": duration_text},
            data={"gift_id": gift_info.gift_id, "tariff_id": int(tariff["id"])},
        )
    except Exception as e:
        logger.warning("[Gifts] Ошибка отправки уведомления о подарке: {}", e)

    return GiftRedeemResult(
        message=f"Подарок активирован — подписка на {duration_text}",
        gift_id=gift_info.gift_id,
        tariff_id=int(tariff["id"]),
        duration_days=duration_days,
    )


async def create_gift(
    session: AsyncSession,
    sender_user_ref: int,
    tariff_id: int,
    selected_device_limit: int | None = None,
    selected_traffic_gb: int | None = None,
    selected_price_rub: int | None = None,
) -> GiftCreateResult:
    """Создаёт подарок: списывает баланс, сохраняет в БД.

    Raises: NotFoundError, InsufficientFundsError
    """
    tariff = await get_tariff_by_id(session, int(tariff_id))
    if not tariff or tariff.get("group_code") != "gifts":
        raise NotFoundError("Тариф не найден")

    price_to_charge = int(selected_price_rub) if selected_price_rub is not None else int(tariff["price_rub"])

    balance = await get_balance(session, sender_user_ref)
    if balance < price_to_charge:
        raise InsufficientFundsError(
            "Недостаточно средств для создания подарка",
            required=price_to_charge,
            balance=balance,
        )

    await update_balance(session, sender_user_ref, -price_to_charge)

    duration_days = int(tariff["duration_days"] or 0)
    expiry_time = datetime.utcnow() + timedelta(days=duration_days)
    gift_id = uuid.uuid4().hex
    gift_link = get_gift_link(sender_user_ref, gift_id)
    site_gift_link = get_site_gift_link(gift_id)

    await store_gift_link(
        session=session,
        gift_id=gift_id,
        sender_legacy_ref=sender_user_ref,
        selected_months=duration_days // 30,
        expiry_time=expiry_time,
        gift_link=gift_link,
        tariff_id=int(tariff["id"]),
        max_usages=1,
        selected_device_limit=selected_device_limit,
        selected_traffic_gb=selected_traffic_gb,
        selected_price_rub=price_to_charge,
    )

    return GiftCreateResult(
        gift_id=gift_id,
        gift_link=gift_link,
        site_gift_link=site_gift_link,
        tariff_name=tariff["name"],
        duration_days=duration_days,
        duration_text=_format_duration(duration_days),
        expiry_time=expiry_time,
        price_charged=price_to_charge,
    )
