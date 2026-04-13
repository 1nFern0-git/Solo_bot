from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from services.coupons import resolve_percent_coupon
from services.errors import ServiceError


async def resolve_percent_coupon_pricing(
    session: AsyncSession,
    billing_user_id: int,
    base_price_rub: int,
    coupon_code: str | None,
) -> tuple[int, int, int | None, str | None]:
    """Применяет процентный купон. Бросает HTTPException при ошибке."""
    try:
        return await resolve_percent_coupon(
            session=session,
            billing_user_id=billing_user_id,
            base_price_rub=base_price_rub,
            coupon_code=coupon_code,
        )
    except ServiceError as e:
        status_map = {
            "not_found": 404,
            "limit_exceeded": 409,
            "validation_error": 400,
        }
        raise HTTPException(
            status_code=status_map.get(e.code, 400),
            detail=e.message,
        )
