from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import API_TOKEN_TTL_DAYS
from logger import logger
from utils.referral_codes import encode_partner_code


TOKEN_TTL_HINT = "бессрочно" if API_TOKEN_TTL_DAYS is None else f"{API_TOKEN_TTL_DAYS} дн."
TELEGRAM_LOGIN_MAX_AGE = 86400

_TRUSTED_PROXY_CIDRS: list[str] = []


def _client_ip(request: Request) -> str:
    client_host = (request.client.host if request.client else "") or ""
    forwarded = request.headers.get("x-forwarded-for") or request.headers.get("X-Forwarded-For")
    if not forwarded:
        return client_host
    if not _TRUSTED_PROXY_CIDRS and client_host not in ("127.0.0.1", "::1"):
        return client_host
    return forwarded.split(",")[0].strip() or client_host


async def _resolve_partner_snapshot(session: AsyncSession, billing_user_id: int) -> dict[str, object]:
    partner_feature_enabled = False
    default_percent = 0.0
    try:
        from modules.partner_program import settings as partner_settings

        partner_feature_enabled = True
        raw_percent = getattr(partner_settings, "PARTNER_BONUS_PERCENTAGES", {}).get(1, 0.0)
        default_percent = float(raw_percent) * 100.0
    except Exception:
        partner_feature_enabled = False
        default_percent = 0.0
    payload: dict[str, object] = {
        "partner_enabled": partner_feature_enabled,
        "partner_code": "",
        "partner_balance": 0.0,
        "partner_percent": default_percent,
        "partner_percent_custom": False,
        "partner_referred_total": 0,
        "partner_payout_method": None,
    }
    try:
        partner_row = (
            await session.execute(
                text(
                    """
                    SELECT
                        tg_id,
                        COALESCE(partner_balance, 0),
                        partner_percent,
                        COALESCE(partner_percent_custom, false),
                        partner_code,
                        payout_method
                    FROM users
                    WHERE id = :user_id
                    LIMIT 1
                    """
                ),
                {"user_id": int(billing_user_id)},
            )
        ).first()
    except Exception:
        partner_row = None
    if partner_row is None:
        return payload
    tg_id = int(partner_row[0]) if partner_row[0] is not None else None
    balance = float(partner_row[1] or 0.0)
    percent_raw = partner_row[2]
    percent_custom = bool(partner_row[3])
    percent_value = float(percent_raw) if (percent_custom and percent_raw is not None) else float(default_percent)
    code = str(partner_row[4] or "").strip()
    if (not code or code.isdigit() or code.startswith("r1_")) and int(billing_user_id) > 0:
        generated_code = encode_partner_code(int(billing_user_id))
        code = generated_code
        try:
            await session.execute(
                text("UPDATE users SET partner_code = :code WHERE id = :id"),
                {"code": generated_code, "id": int(billing_user_id)},
            )
            await session.flush()
        except Exception as e:
            logger.warning("[Auth] Ошибка сохранения partner_code для billing_user_id={}: {}", billing_user_id, e)
    payout_method = str(partner_row[5] or "").strip() or None
    referred_total = 0
    if tg_id is not None:
        try:
            referred_total = int(
                (
                    await session.execute(
                        text("SELECT COUNT(*) FROM partners WHERE partner_tg_id = :tg_id"),
                        {"tg_id": int(tg_id)},
                    )
                ).scalar()
                or 0
            )
        except Exception:
            referred_total = 0
    payload.update({
        "partner_enabled": bool(partner_feature_enabled or code or referred_total > 0 or balance > 0),
        "partner_code": code,
        "partner_balance": balance,
        "partner_percent": percent_value,
        "partner_percent_custom": percent_custom,
        "partner_referred_total": referred_total,
        "partner_payout_method": payout_method,
    })
    return payload
