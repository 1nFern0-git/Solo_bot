from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Setting


_KEY = "SITE_INITIALIZED"


async def is_site_initialized(session: AsyncSession) -> bool:
    result = await session.execute(select(Setting).where(Setting.key == _KEY))
    setting = result.scalar_one_or_none()
    return bool(setting and setting.value is True)


async def mark_site_initialized(session: AsyncSession) -> None:
    """Идемпотентно выставляет флаг инициализации сайта."""
    result = await session.execute(select(Setting).where(Setting.key == _KEY))
    setting = result.scalar_one_or_none()
    if setting is None:
        session.add(Setting(key=_KEY, value=True, description="Сайт прошёл первую настройку админом"))
    elif setting.value is not True:
        setting.value = True


async def reset_site_initialized(session: AsyncSession) -> None:
    """Сброс флага — вызывается при полном ресете сайта через TG-бот."""
    result = await session.execute(select(Setting).where(Setting.key == _KEY))
    setting = result.scalar_one_or_none()
    if setting is not None:
        setting.value = False
