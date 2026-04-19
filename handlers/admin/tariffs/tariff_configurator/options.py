import re

from datetime import datetime

from aiogram import F
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models import Tariff
from filters.admin import IsAdminFilter

from .. import router
from .common import (
    TariffConfigState,
    build_cancel_config_kb,
    build_config_menu_kb,
    build_config_summary_text,
)


@router.callback_query(F.data.startswith("cfg_edit_devices|"), TariffConfigState.choosing_section, IsAdminFilter())
async def ask_devices_config(callback: CallbackQuery, state: FSMContext):
    tariff_id = int(callback.data.split("|")[1])
    await state.set_state(TariffConfigState.entering_devices)
    await state.update_data(tariff_id=tariff_id)

    text = (
        "📱 Настройка вариантов устройств.\n\n"
        "Введите список вариантов количества устройств через пробел или запятую.\n"
        "Например: <code>1 3 5</code>\n\n"
        "Число <code>0</code> можно использовать как вариант безлимита.\n"
        "Чтобы совсем отключить выбор устройств и использовать только базовый лимит тарифа, отправьте единичный <code>0</code>."
    )
    await callback.message.edit_text(text=text, reply_markup=build_cancel_config_kb(tariff_id))


@router.message(TariffConfigState.entering_devices, IsAdminFilter())
async def save_devices_config(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    tariff_id = data["tariff_id"]
    raw_text = message.text.strip()

    result = await session.execute(select(Tariff).where(Tariff.id == tariff_id))
    tariff = result.scalar_one_or_none()
    if not tariff:
        await message.answer("❌ Тариф не найден.")
        await state.clear()
        return

    if raw_text == "0":
        tariff.device_options = None
    else:
        try:
            parts = [p for p in re.split(r"[,\s]+", raw_text) if p.strip()]
            if not parts:
                raise ValueError
            values: list[int] = []
            for part in parts:
                v = int(part)
                if v < 0:
                    raise ValueError
                values.append(v)
            values = sorted(set(values))
            tariff.device_options = values
        except Exception:
            await message.answer(
                "❌ Некорректные значения. Введите положительные числа или 0 через пробел или запятую,\n"
                "например: <code>1 3 5</code>, <code>0 1 3 5</code> (0 как безлимит)\n"
                "или <code>0</code> для отключения выбора устройств.",
                reply_markup=build_cancel_config_kb(tariff_id),
            )
            return

    tariff.updated_at = datetime.utcnow()

    await state.set_state(TariffConfigState.choosing_section)

    text = build_config_summary_text(tariff)
    await message.answer(text=text, reply_markup=build_config_menu_kb(tariff_id))


@router.callback_query(F.data.startswith("cfg_edit_traffic|"), TariffConfigState.choosing_section, IsAdminFilter())
async def ask_traffic_config(callback: CallbackQuery, state: FSMContext):
    tariff_id = int(callback.data.split("|")[1])
    await state.set_state(TariffConfigState.entering_traffic)
    await state.update_data(tariff_id=tariff_id)

    text = (
        "📦 Настройка вариантов трафика.\n\n"
        "Введите список лимитов трафика в ГБ через пробел или запятую.\n"
        "Например: <code>100 200 500</code>\n\n"
        "Число <code>0</code> можно использовать как вариант безлимита.\n"
        "Чтобы совсем отключить выбор трафика и использовать только базовый лимит тарифа, отправьте единичный <code>0</code>."
    )
    await callback.message.edit_text(text=text, reply_markup=build_cancel_config_kb(tariff_id))


@router.message(TariffConfigState.entering_traffic, IsAdminFilter())
async def save_traffic_config(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    tariff_id = data["tariff_id"]
    raw_text = message.text.strip()

    result = await session.execute(select(Tariff).where(Tariff.id == tariff_id))
    tariff = result.scalar_one_or_none()
    if not tariff:
        await message.answer("❌ Тариф не найден.")
        await state.clear()
        return

    if raw_text == "0":
        tariff.traffic_options_gb = None
    else:
        try:
            parts = [p for p in re.split(r"[,\s]+", raw_text) if p.strip()]
            if not parts:
                raise ValueError
            values: list[int] = []
            for part in parts:
                v = int(part)
                if v < 0:
                    raise ValueError
                values.append(v)
            values = sorted(set(values))
            tariff.traffic_options_gb = values
        except Exception:
            await message.answer(
                "❌ Некорректные значения. Введите числа 0 и больше через пробел или запятую,\n"
                "например: <code>100 200 500</code>.\n"
                "0 можно использовать как вариант безлимита или отправить единственный 0 для отключения выбора.",
                reply_markup=build_cancel_config_kb(tariff_id),
            )
            return

    tariff.updated_at = datetime.utcnow()

    await state.set_state(TariffConfigState.choosing_section)

    text = build_config_summary_text(tariff)
    await message.answer(text=text, reply_markup=build_config_menu_kb(tariff_id))
