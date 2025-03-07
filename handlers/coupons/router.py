from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database import (
    check_coupon_usage,
    create_coupon_usage,
    get_coupon_by_code,
    update_balance,
    update_coupon_usage_count,
)
from handlers.utils import edit_or_send_message
from keyboards.coupons import get_coupon_keyboard


class CouponActivationState(StatesGroup):
    waiting_for_coupon_code = State()


router = Router()


@router.callback_query(F.data == "activate_coupon")
@router.message(F.text == "/activate_coupon")
async def handle_activate_coupon(state: FSMContext, target_message: Message):
    """
    Обрабатывает запрос на активацию купона.

    Args:
        state: Контекст состояния FSM.
        chat_id: ID чата (добавлено middleware).
        target_message: Целевое сообщение для ответа (добавлено middleware).
    """
    builder = get_coupon_keyboard()

    await edit_or_send_message(
        target_message=target_message,
        text="<b>🎫 Введите код купона:</b>\n\n"
        "📝 Пожалуйста, введите действующий код купона, который вы хотите активировать. 🔑",
        reply_markup=builder.as_markup(),
        media_path=None,
    )
    await state.set_state(CouponActivationState.waiting_for_coupon_code)


@router.message(CouponActivationState.waiting_for_coupon_code)
async def process_coupon_code(message: Message, state: FSMContext, session: Any, chat_id: int):
    """
    Обрабатывает введенный код купона.

    Args:
        message: Сообщение с кодом купона.
        state: Контекст состояния FSM.
        session: Сессия базы данных.
        chat_id: ID чата (добавлено middleware).
    """
    coupon_code = message.text.strip()
    activation_result = await activate_coupon(chat_id, coupon_code, session)

    builder = get_coupon_keyboard()

    await message.answer(activation_result, reply_markup=builder.as_markup())
    await state.clear()


async def activate_coupon(user_id: int, coupon_code: str, session: Any) -> str:
    """
    Активирует купон для пользователя.

    Args:
        user_id: ID пользователя.
        coupon_code: Код купона.
        session: Сессия базы данных.

    Returns:
        str: Сообщение о результате активации.
    """
    coupon_record = await get_coupon_by_code(coupon_code, session)

    if not coupon_record:
        return "<b>❌ Купон не найден</b> 🚫 или его использование ограничено. 🔒 Пожалуйста, проверьте код и попробуйте снова. 🔍"

    usage_exists = await check_coupon_usage(coupon_record["id"], user_id, session)

    if usage_exists:
        return "<b>❌ Вы уже активировали этот купон.</b> 🚫 Купоны могут быть активированы только один раз. 🔒"

    coupon_amount = coupon_record["amount"]

    await update_coupon_usage_count(coupon_record["id"], session)
    await create_coupon_usage(coupon_record["id"], user_id, session)

    await update_balance(user_id, coupon_amount, session)
    return f"<b>✅ Купон успешно активирован! 🎉</b>\n\nНа ваш баланс добавлено <b>{coupon_amount} рублей</b> 💰."
