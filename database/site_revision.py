from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Setting


_KEY = "CONTENT_REVISION"


async def get_site_revision(session: AsyncSession) -> int:
    result = await session.execute(select(Setting).where(Setting.key == _KEY))
    setting = result.scalar_one_or_none()
    if setting is None:
        return 0
    try:
        return int(setting.value or 0)
    except (TypeError, ValueError):
        return 0


async def bump_site_revision(session: AsyncSession) -> int:
    result = await session.execute(select(Setting).where(Setting.key == _KEY))
    setting = result.scalar_one_or_none()
    if setting is None:
        session.add(Setting(key=_KEY, value=1))
        return 1
    try:
        current = int(setting.value or 0)
    except (TypeError, ValueError):
        current = 0
    setting.value = current + 1
    return current + 1
