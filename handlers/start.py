import os
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from config import CHANNEL_URL, CONNECT_ANDROID, CONNECT_IOS, DOWNLOAD_ANDROID, DOWNLOAD_IOS, SUPPORT_CHAT_URL
from database import add_connection, add_referral, check_connection_exists, get_trial, use_trial
from handlers.keys.trial_key import create_trial_key
from handlers.texts import INSTRUCTIONS_TRIAL, WELCOME_TEXT, get_about_vpn
from logger import logger

router = Router()


@router.callback_query(F.data == "start")
async def handle_start_callback_query(callback_query: CallbackQuery, state: FSMContext, session: Any, admin: bool):
    await start_command(callback_query.message, state, session, admin)


@router.message(Command("start"))
async def start_command(message: Message, state: FSMContext, session: Any, admin: bool):
    if message.text:
        try:
            referrer_tg_id = int(message.text.split("referral_")[1])
            await add_referral(message.from_user.id, referrer_tg_id, session)
        except (ValueError, IndexError):
            pass
        connection_exists = await check_connection_exists(message.from_user.id)
        if not connection_exists:
            await add_connection(message.from_user.id, session)
    trial_status = await get_trial(message.from_user.id, session)
    logger.info(f'trial_status {trial_status}')
    image_path = os.path.join("img", "pic.jpg")

    builder = InlineKeyboardBuilder()
    if trial_status == 0:
        builder.row(InlineKeyboardButton(text="🔗 Подключить VPN", callback_data="connect_vpn"))
    builder.row(InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile"))
    builder.row(
        InlineKeyboardButton(text="📞 Техническая поддержка", url=SUPPORT_CHAT_URL),
    )
    builder.row(
        InlineKeyboardButton(text="📢 Официальный канал", url=CHANNEL_URL),
    )
    if admin:
        builder.row(InlineKeyboardButton(text="🔧 Администратор", callback_data="admin"))
    builder.row(InlineKeyboardButton(text="🌐 О нашем VPN", callback_data="about_vpn"))

    if os.path.isfile(image_path):
        with open(image_path, "rb") as image_from_buffer:
            await message.answer_photo(
                photo=BufferedInputFile(image_from_buffer.read(), filename="pic.jpg"),
                caption=WELCOME_TEXT,
                reply_markup=builder.as_markup(),
            )
    else:
        await message.answer(
            text=WELCOME_TEXT,
            reply_markup=builder.as_markup(),
        )


@router.callback_query(F.data == "connect_vpn")
async def handle_connect_vpn(callback_query: CallbackQuery, session: Any):
    user_id = callback_query.from_user.id

    trial_key_info = await create_trial_key(user_id, session)

    if "error" in trial_key_info:
        await callback_query.message.answer(trial_key_info["error"])
    else:
        await use_trial(user_id, session)

        key_message = (
            f"🔑 <b>Ваш персональный ключ доступа:</b>\n"
            f"<pre>{trial_key_info['key']}</pre>\n\n"
            f"📋 <b>Быстрая инструкция по подключению:</b>\n{INSTRUCTIONS_TRIAL}"
        )

        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="👤 Личный кабинет", callback_data="profile"))
        builder.row(
            InlineKeyboardButton(text="🍏 Скачать для iOS", url=DOWNLOAD_IOS),
            InlineKeyboardButton(text="🤖 Скачать для Android", url=DOWNLOAD_ANDROID),
        )
        builder.row(
            InlineKeyboardButton(
                text="🍏 Подключить на iOS",
                url=f'{CONNECT_IOS}{trial_key_info["key"]}',
            ),
            InlineKeyboardButton(
                text="🤖 Подключить на Android",
                url=f'{CONNECT_ANDROID}{trial_key_info["key"]}',
            ),
        )

        await callback_query.message.answer(key_message, reply_markup=builder.as_markup())


@router.callback_query(F.data == "about_vpn")
async def handle_about_vpn(callback_query: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="💰 Поддержать проект", callback_data="donate"))
    builder.row(
        InlineKeyboardButton(text="📞 Техническая поддержка", url=SUPPORT_CHAT_URL),
    )
    builder.row(
        InlineKeyboardButton(text="📢 Официальный канал", url=CHANNEL_URL),
    )
    builder.row(InlineKeyboardButton(text="⬅️ Назад", callback_data="start"))

    await callback_query.message.answer(get_about_vpn("3.1.1_Stable"), reply_markup=builder.as_markup())
