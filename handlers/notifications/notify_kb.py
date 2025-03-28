from aiogram.types import InlineKeyboardMarkup

from handlers.buttons import MAIN_MENU, RENEW_KEY


def build_notification_kb(email: str) -> InlineKeyboardMarkup:
    """
    Формирует inline-клавиатуру для уведомлений.
    Кнопки: "🔄 Продлить VPN" (callback_data содержит email) и "👤 Личный кабинет".
    """
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text=RENEW_KEY, callback_data=f"renew_key|{email}")
    builder.button(text=MAIN_MENU, callback_data="profile")
    builder.adjust(1)
    return builder.as_markup()


def build_notification_expired_kb() -> InlineKeyboardMarkup:
    """
    Формирует inline-клавиатуру для уведомлений после удаления или продления.
    Кнопка: "👤 Личный кабинет"
    """
    from aiogram.utils.keyboard import InlineKeyboardBuilder

    builder = InlineKeyboardBuilder()
    builder.button(text=MAIN_MENU, callback_data="profile")
    return builder.as_markup()
