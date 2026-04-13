import hashlib
import secrets
from datetime import datetime, timedelta

import bcrypt
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import API_TOKEN_TTL_DAYS
from core.executor import run_cpu, run_io
from database.access.tg_mirror import refresh_tg_mirrors_for_user
from database.models import Admin, Identity, User


_BCRYPT_MAX_PASSWORD_BYTES = 72
_BCRYPT_ROUNDS = 12


def _password_bytes(password: str) -> bytes:
    """Пароль в байтах, не длиннее 72 байт (ограничение bcrypt)."""
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_PASSWORD_BYTES:
        return raw[:_BCRYPT_MAX_PASSWORD_BYTES]
    return raw


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def hash_password(password: str) -> str:
    """Хеш пароля через bcrypt (соль уникальна на каждый пароль)."""
    salt = bcrypt.gensalt(rounds=_BCRYPT_ROUNDS)
    return bcrypt.hashpw(_password_bytes(password), salt).decode("ascii")


def check_password(password: str, password_hash: str | None) -> bool:
    if not password_hash:
        return False
    try:
        return bcrypt.checkpw(_password_bytes(password), password_hash.encode("ascii"))
    except Exception:
        return False


def generate_token() -> str:
    return secrets.token_urlsafe(32)


async def create_identity(
    session: AsyncSession,
    email: str | None = None,
    tg_id: int | None = None,
) -> Identity:
    """Создаёт идентичность; можно задать email и/или tg_id."""
    identity = Identity(email=email.strip().lower() if email else None, tg_id=tg_id)
    session.add(identity)
    await session.flush()
    if tg_id:
        await session.execute(User.__table__.update().where(User.tg_id == tg_id).values(identity_id=identity.id))
    await session.refresh(identity)
    return identity


async def get_identity_by_id(session: AsyncSession, identity_id: str) -> Identity | None:
    """Возвращает идентичность по id."""
    result = await session.execute(select(Identity).where(Identity.id == identity_id))
    return result.scalar_one_or_none()


async def get_identity_by_email(session: AsyncSession, email: str) -> Identity | None:
    """Возвращает идентичность по email."""
    if not email or not email.strip():
        return None
    result = await session.execute(select(Identity).where(Identity.email == email.strip().lower()))
    return result.scalar_one_or_none()


async def get_identity_by_tg_id(session: AsyncSession, tg_id: int) -> Identity | None:
    """Возвращает идентичность по tg_id."""
    result = await session.execute(select(Identity).where(Identity.tg_id == tg_id))
    return result.scalar_one_or_none()


async def get_identity_by_token_hash(session: AsyncSession, token_hash: str) -> Identity | None:
    """Возвращает идентичность по хешу API-токена."""
    result = await session.execute(select(Identity).where(Identity.api_token_hash == token_hash))
    return result.scalar_one_or_none()


async def issue_token_for_identity(session: AsyncSession, identity: Identity) -> str:
    """Генерирует токен, сохраняет хеш и token_issued_at в identity, возвращает токен (показать один раз)."""
    token = generate_token()
    identity.api_token_hash = await run_io(hash_token, token)
    identity.token_issued_at = datetime.utcnow()
    await session.refresh(identity)
    return token


def _is_token_expired(identity: Identity) -> bool:
    """Проверяет, истёк ли срок действия токена (если задан API_TOKEN_TTL_DAYS)."""
    if API_TOKEN_TTL_DAYS is None or identity.token_issued_at is None:
        return False
    expiry = identity.token_issued_at + timedelta(days=API_TOKEN_TTL_DAYS)
    return datetime.utcnow() >= expiry


async def create_identity_with_token(
    session: AsyncSession,
    email: str | None = None,
    password: str | None = None,
    tg_id: int | None = None,
) -> tuple[Identity, str]:
    """Создаёт идентичность и выдаёт API-токен. При регистрации по почте передать email и password."""
    identity = await create_identity(session, email=email, tg_id=tg_id)
    if password:
        identity.password_hash = await run_cpu(hash_password, password)
        await session.refresh(identity)
    token = await issue_token_for_identity(session, identity)
    return identity, token


async def verify_identity_token(session: AsyncSession, identity_id: str, token: str) -> Identity | None:
    """Проверяет пару identity_id + token и срок действия токена; возвращает Identity или None."""
    identity = await get_identity_by_id(session, identity_id)
    if not identity or not identity.api_token_hash:
        return None
    token_hash = await run_io(hash_token, token)
    if token_hash != identity.api_token_hash:
        return None
    if _is_token_expired(identity):
        return None
    return identity


async def login_by_email(session: AsyncSession, email: str, password: str) -> tuple[Identity, str] | None:
    """Вход по email и паролю: проверяет пароль, выдаёт новый токен; возвращает (identity, token) или None."""
    identity = await get_identity_by_email(session, email)
    if not identity:
        return None
    if not await run_cpu(check_password, password, identity.password_hash):
        return None
    token = await issue_token_for_identity(session, identity)
    return identity, token


async def set_initial_password(
    session: AsyncSession,
    identity_id: str,
    password: str,
) -> Identity | None:
    identity = await get_identity_by_id(session, identity_id)
    if not identity or identity.password_hash:
        return None
    identity.password_hash = await run_cpu(hash_password, password)
    await session.refresh(identity)
    return identity


async def set_password_for_identity(
    session: AsyncSession,
    identity_id: str,
    new_password: str,
) -> Identity | None:
    identity = await get_identity_by_id(session, identity_id)
    if not identity:
        return None
    identity.password_hash = await run_cpu(hash_password, new_password)
    await session.refresh(identity)
    return identity


async def change_identity_password(
    session: AsyncSession,
    identity_id: str,
    current_password: str,
    new_password: str,
) -> str | None:
    """Возвращает None при успехе, иначе код: no_password | wrong_password."""
    identity = await get_identity_by_id(session, identity_id)
    if not identity:
        return "wrong_password"
    if not identity.password_hash:
        return "no_password"
    if not await run_cpu(check_password, current_password, identity.password_hash):
        return "wrong_password"
    identity.password_hash = await run_cpu(hash_password, new_password)
    await session.refresh(identity)
    return None


async def ensure_billing_user_for_identity(session: AsyncSession, identity: Identity) -> int:
    from database.users import add_user, check_user_exists

    if identity.tg_id is not None:
        tid = int(identity.tg_id)
        if not await check_user_exists(session, tid):
            await add_user(session, tid)
        ur = await session.execute(select(User).where(User.tg_id == tid).limit(1))
        u = ur.scalar_one()
        await session.execute(update(User).where(User.id == u.id).values(identity_id=identity.id))
        return int(u.id)
    res = await session.execute(select(User).where(User.identity_id == identity.id))
    row = res.scalars().first()
    if row is not None:
        return int(row.id)
    new_u = User(identity_id=identity.id, tg_id=None)
    session.add(new_u)
    await session.flush()
    return int(new_u.id)


async def merge_billing_user_into_telegram(session: AsyncSession, identity_id: str, telegram_tg_id: int) -> None:
    from database.models import (
        CouponUsage,
        Gift,
        GiftUsage,
        Key,
        Notification,
        Payment,
        Referral,
        ScheduledBroadcast,
        TemporaryData,
    )
    from database.access.resolution import resolve_user_optional
    from database.users import invalidate_balance_cache, invalidate_profile_cache, update_balance

    res = await session.execute(select(User).where(User.identity_id == identity_id))
    rows = res.scalars().all()
    if not rows:
        return
    billing = rows[0]
    src_uid = int(billing.id)
    dst_tg = int(telegram_tg_id)
    if billing.tg_id is not None and int(billing.tg_id) > 0:
        return

    dst_u = await resolve_user_optional(session, dst_tg)
    if dst_u is None:
        new_u = User(
            tg_id=dst_tg,
            identity_id=identity_id,
            username=billing.username,
            first_name=billing.first_name,
            last_name=billing.last_name,
            language_code=billing.language_code,
            is_bot=billing.is_bot or False,
            balance=float(billing.balance or 0.0),
            trial=int(billing.trial or 0),
            preferred_currency=billing.preferred_currency or "RUB",
            source_code=billing.source_code,
        )
        session.add(new_u)
        await session.flush()
        dst_uid = int(new_u.id)
    else:
        dst_uid = int(dst_u.id)
        bal = float(billing.balance or 0.0)
        if bal:
            await update_balance(session, dst_uid, bal)
        st = int(billing.trial or 0)
        dt_r = await session.execute(select(User.trial).where(User.id == dst_uid))
        dt_val = dt_r.scalar_one_or_none()
        if dt_val is not None and st > int(dt_val or 0):
            await session.execute(update(User).where(User.id == dst_uid).values(trial=st))

    await session.execute(update(Key).where(Key.user_id == src_uid).values(user_id=dst_uid))
    await session.execute(update(Payment).where(Payment.user_id == src_uid).values(user_id=dst_uid))

    await session.execute(
        text(
            "DELETE FROM notifications AS n1 USING notifications AS n2 "
            "WHERE n1.user_id = :src AND n2.user_id = :dst AND n1.notification_type = n2.notification_type"
        ),
        {"src": src_uid, "dst": dst_uid},
    )
    await session.execute(update(Notification).where(Notification.user_id == src_uid).values(user_id=dst_uid))

    await session.execute(update(Gift).where(Gift.sender_user_id == src_uid).values(sender_user_id=dst_uid))
    await session.execute(
        update(Gift).where(Gift.recipient_user_id == src_uid).values(recipient_user_id=dst_uid)
    )

    await session.execute(
        text(
            "DELETE FROM gift_usages AS g1 USING gift_usages AS g2 "
            "WHERE g1.user_id = :src AND g2.user_id = :dst AND g1.gift_id = g2.gift_id"
        ),
        {"src": src_uid, "dst": dst_uid},
    )
    await session.execute(update(GiftUsage).where(GiftUsage.user_id == src_uid).values(user_id=dst_uid))

    await session.execute(
        text(
            "DELETE FROM coupon_usages AS c1 USING coupon_usages AS c2 "
            "WHERE c1.user_id = :src AND c2.user_id = :dst AND c1.coupon_id = c2.coupon_id"
        ),
        {"src": src_uid, "dst": dst_uid},
    )
    await session.execute(update(CouponUsage).where(CouponUsage.user_id == src_uid).values(user_id=dst_uid))

    await session.execute(update(TemporaryData).where(TemporaryData.user_id == src_uid).values(user_id=dst_uid))

    await session.execute(
        update(ScheduledBroadcast)
        .where(ScheduledBroadcast.created_by_user_id == src_uid)
        .values(created_by_user_id=dst_uid)
    )

    await session.execute(
        text(
            "DELETE FROM referrals AS r1 USING referrals AS r2 "
            "WHERE r1.referred_user_id = :src AND r2.referred_user_id = :dst "
            "AND r1.referrer_user_id = r2.referrer_user_id"
        ),
        {"src": src_uid, "dst": dst_uid},
    )
    await session.execute(
        text(
            "DELETE FROM referrals AS r1 USING referrals AS r2 "
            "WHERE r1.referrer_user_id = :src AND r2.referrer_user_id = :dst "
            "AND r1.referred_user_id = r2.referred_user_id"
        ),
        {"src": src_uid, "dst": dst_uid},
    )
    await session.execute(
        update(Referral).where(Referral.referred_user_id == src_uid).values(referred_user_id=dst_uid)
    )
    await session.execute(
        update(Referral).where(Referral.referrer_user_id == src_uid).values(referrer_user_id=dst_uid)
    )

    await refresh_tg_mirrors_for_user(session, dst_uid)

    await session.execute(delete(User).where(User.id == src_uid))
    await session.execute(update(User).where(User.id == dst_uid).values(identity_id=identity_id))

    await invalidate_balance_cache(src_uid)
    await invalidate_profile_cache(src_uid)
    await invalidate_balance_cache(dst_uid)
    await invalidate_profile_cache(dst_uid)


async def resolve_tg_id(session: AsyncSession, identity_id: str) -> int | None:
    """По identity_id возвращает внутренний user id (users.id) для биллинга и ключей."""
    identity = await get_identity_by_id(session, identity_id)
    if not identity:
        return None
    return await ensure_billing_user_for_identity(session, identity)


async def attach_email(session: AsyncSession, identity_id: str, email: str) -> Identity | None:
    """Привязывает email к идентичности."""
    identity = await get_identity_by_id(session, identity_id)
    if not identity:
        return None
    email_clean = email.strip().lower() if email else None
    if not email_clean:
        return identity
    existing = await get_identity_by_email(session, email_clean)
    if existing and existing.id != identity_id:
        return None
    identity.email = email_clean
    await session.refresh(identity)
    return identity


async def attach_telegram(session: AsyncSession, identity_id: str, tg_id: int) -> Identity | None:
    """Привязывает Telegram (tg_id) к идентичности и связывает User с identity. Если tg_id в admins — выставляет is_admin."""
    identity = await get_identity_by_id(session, identity_id)
    if not identity:
        return None
    existing = await get_identity_by_tg_id(session, tg_id)
    if existing and existing.id != identity_id:
        return None
    await merge_billing_user_into_telegram(session, identity_id, tg_id)
    identity = await get_identity_by_id(session, identity_id)
    if not identity:
        return None
    identity.tg_id = tg_id
    admin_row = await session.execute(select(Admin).where(Admin.tg_id == tg_id))
    if admin_row.scalar_one_or_none():
        identity.is_admin = True
    await session.execute(User.__table__.update().where(User.tg_id == tg_id).values(identity_id=identity_id))
    await session.refresh(identity)
    return identity


async def get_or_create_identity_for_tg(session: AsyncSession, tg_id: int) -> Identity:
    """Для tg_id возвращает существующую идентичность или создаёт новую и привязывает User."""
    identity = await get_identity_by_tg_id(session, tg_id)
    if identity:
        return identity
    identity = Identity(tg_id=tg_id)
    session.add(identity)
    await session.flush()
    await session.execute(User.__table__.update().where(User.tg_id == tg_id).values(identity_id=identity.id))
    await session.refresh(identity)
    return identity
