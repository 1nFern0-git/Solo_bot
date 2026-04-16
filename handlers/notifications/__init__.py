__all__ = ("router",)

from aiogram import Router

from core.tasks import lifecycle as _task_lifecycle


router = Router(name="notifications_main_router")
