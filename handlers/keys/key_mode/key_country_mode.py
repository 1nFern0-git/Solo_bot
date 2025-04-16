import asyncio
import uuid

from datetime import datetime
from typing import Any

import pytz

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from py3xui import AsyncApi

from config import (
    ADMIN_PASSWORD,
    ADMIN_USERNAME,
    CONNECT_PHONE_BUTTON,
    PUBLIC_LINK,
    RENEWAL_PRICES,
    SUPPORT_CHAT_URL,
    REMNAWAVE_LOGIN,
    REMNAWAVE_PASSWORD
)
from database import (
    add_connection,
    check_connection_exists,
    get_key_details,
    get_trial,
    update_balance,
    update_trial,
    check_server_name_by_cluster,
)
from handlers.buttons import (
    BACK,
    CONNECT_DEVICE,
    CONNECT_PHONE,
    MAIN_MENU,
    PC_BUTTON,
    SUPPORT,
    TV_BUTTON,
    SUPPORT
)
from handlers.keys.key_utils import create_client_on_server
from handlers.texts import (
    SELECT_COUNTRY_MSG,
    key_message_success,
)
from handlers.utils import edit_or_send_message, generate_random_email, get_least_loaded_cluster
from logger import logger
from panels.three_xui import delete_client
from panels.remnawave import RemnawaveAPI


router = Router()

moscow_tz = pytz.timezone("Europe/Moscow")


async def key_country_mode(
    tg_id: int,
    expiry_time: datetime,
    state: FSMContext,
    session: Any,
    message_or_query: Message | CallbackQuery | None = None,
    old_key_name: str = None,
):
    target_message = message_or_query.message if isinstance(message_or_query, CallbackQuery) else message_or_query

    least_loaded_cluster = await get_least_loaded_cluster()
    servers = await session.fetch(
        "SELECT server_name, api_url, panel_type FROM servers WHERE cluster_name = $1",
        least_loaded_cluster,
    )


    if not servers:
        logger.error(f"Нет серверов в кластере {least_loaded_cluster}")
        error_message = "❌ Нет доступных серверов для создания ключа."
        await edit_or_send_message(
            target_message=target_message,
            text=error_message,
            reply_markup=None,
        )
        return

    available_servers = []
    tasks = [asyncio.create_task(check_server_availability(server)) for server in servers]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for server, result in zip(servers, results):
        if result is True:
            available_servers.append(server["server_name"])

    if not available_servers:
        logger.error(f"Нет доступных серверов в кластере {least_loaded_cluster}")
        error_message = "❌ Нет доступных серверов для создания ключа."
        await edit_or_send_message(
            target_message=target_message,
            text=error_message,
            reply_markup=None,
        )
        return

    logger.info(f"[Country Selection] Доступные серверы для выбора: {available_servers}")

    builder = InlineKeyboardBuilder()
    ts = int(expiry_time.timestamp())

    for country in available_servers:
        if old_key_name:
            callback_data = f"select_country|{country}|{ts}|{old_key_name}"
        else:
            callback_data = f"select_country|{country}|{ts}"
        builder.row(InlineKeyboardButton(text=country, callback_data=callback_data))

    builder.row(InlineKeyboardButton(text=MAIN_MENU, callback_data="profile"))

    await edit_or_send_message(
        target_message=target_message,
        text=SELECT_COUNTRY_MSG,
        reply_markup=builder.as_markup(),
        media_path=None,
    )


@router.callback_query(F.data.startswith("change_location|"))
async def change_location_callback(callback_query: CallbackQuery, session: Any):
    try:
        data = callback_query.data.split("|")
        if len(data) < 2:
            await callback_query.answer("❌ Некорректные данные", show_alert=True)
            return

        old_key_name = data[1]
        record = await get_key_details(old_key_name, session)
        if not record:
            await callback_query.answer("❌ Ключ не найден", show_alert=True)
            return

        expiry_timestamp = record["expiry_time"]
        ts = int(expiry_timestamp / 1000)

        current_server = record["server_id"]

        cluster_info = await check_server_name_by_cluster(current_server, session)
        if not cluster_info:
            await callback_query.answer("❌ Кластер для текущего сервера не найден", show_alert=True)
            return

        cluster_name = cluster_info["cluster_name"]

        servers = await session.fetch(
            "SELECT server_name, api_url, panel_type FROM servers WHERE cluster_name = $1 AND server_name != $2",
            cluster_name,
            current_server,
        )
        if not servers:
            await callback_query.answer("❌ Доступных серверов в кластере не найдено", show_alert=True)
            return

        available_servers = []
        tasks = []

        for server in servers:
            server_info = {
                "server_name": server["server_name"],
                "api_url": server["api_url"],
                "panel_type": server["panel_type"],
            }
            task = asyncio.create_task(check_server_availability(server_info))
            tasks.append(task)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for server, result in zip(servers, results):
            if result is True:
                available_servers.append(server["server_name"])

        if not available_servers:
            await callback_query.answer("❌ Нет доступных серверов для смены локации", show_alert=True)
            return

        logger.info(f"Доступные страны для смены локации: {available_servers}")

        builder = InlineKeyboardBuilder()
        for country in available_servers:
            callback_data = f"select_country|{country}|{ts}|{old_key_name}"
            builder.row(InlineKeyboardButton(text=country, callback_data=callback_data))
        builder.row(InlineKeyboardButton(text=BACK, callback_data=f"view_key|{old_key_name}"))

        await edit_or_send_message(
            target_message=callback_query.message,
            text="🌍 Пожалуйста, выберите новую локацию для вашей подписки:",
            reply_markup=builder.as_markup(),
            media_path=None,
        )
    except Exception as e:
        logger.error(f"Ошибка при смене локации для пользователя {callback_query.from_user.id}: {e}")
        await callback_query.answer("❌ Ошибка смены локации. Попробуйте снова.", show_alert=True)


@router.callback_query(F.data.startswith("select_country|"))
async def handle_country_selection(callback_query: CallbackQuery, session: Any, state: FSMContext):
    """
    Обрабатывает выбор страны.
    Формат callback data:
      select_country|{selected_country}|{ts} [|{old_key_name} (опционально)]
    Если передан old_key_name – значит, происходит смена локации.
    """
    data = callback_query.data.split("|")
    if len(data) < 3:
        await callback_query.message.answer("❌ Некорректные данные. Попробуйте снова.")
        return

    selected_country = data[1]
    try:
        ts = int(data[2])
    except ValueError:
        await callback_query.message.answer("❌ Некорректное время истечения. Попробуйте снова.")
        return

    expiry_time = datetime.fromtimestamp(ts, tz=moscow_tz)

    old_key_name = data[3] if len(data) > 3 else None

    tg_id = callback_query.from_user.id
    logger.info(f"Пользователь {tg_id} выбрал страну: {selected_country}")
    logger.info(f"Получено время истечения (timestamp): {ts}")

    await finalize_key_creation(tg_id, expiry_time, selected_country, state, session, callback_query, old_key_name)


async def finalize_key_creation(
    tg_id: int,
    expiry_time: datetime,
    selected_country: str,
    state: FSMContext | None,
    session: Any,
    callback_query: CallbackQuery,
    old_key_name: str = None,
):
    if not await check_connection_exists(tg_id):
        await add_connection(tg_id, balance=0.0, trial=0, session=session)
        logger.info(f"[Connection] Подключение создано для пользователя {tg_id}")

    expiry_time = expiry_time.astimezone(moscow_tz)

    if old_key_name:
        old_key_details = await get_key_details(old_key_name, session)
        if not old_key_details:
            await callback_query.message.answer("❌ Ключ не найден. Попробуйте снова.")
            return

        key_name = old_key_name
        client_id = old_key_details["client_id"]
        email = old_key_details["email"]
        expiry_timestamp = old_key_details["expiry_time"]
    else:
        while True:
            key_name = generate_random_email()
            existing_key = await get_key_details(key_name, session)
            if not existing_key:
                break
        client_id = str(uuid.uuid4())
        email = key_name.lower()
        expiry_timestamp = int(expiry_time.timestamp() * 1000)

    try:
        server_info = await session.fetchrow(
            "SELECT api_url, inbound_id, server_name, panel_type FROM servers WHERE server_name = $1",
            selected_country,
        )
        if not server_info:
            raise ValueError(f"Сервер {selected_country} не найден.")

        panel_type = server_info["panel_type"].lower()

        public_link = None
        remnawave_link = None
        created_at = int(datetime.now(moscow_tz).timestamp() * 1000)

        if old_key_name and panel_type == "3x-ui":
            old_server_id = old_key_details.get("server_id")
            if old_server_id:
                old_server_info = await session.fetchrow(
                    "SELECT api_url, inbound_id, server_name FROM servers WHERE server_name = $1",
                    old_server_id,
                )
                if old_server_info:
                    xui = AsyncApi(
                        old_server_info["api_url"],
                        username=ADMIN_USERNAME,
                        password=ADMIN_PASSWORD,
                        logger=logger,
                    )
                    await delete_client(
                        xui,
                        old_server_info["inbound_id"],
                        email,
                        client_id,
                    )

        if panel_type == "remnawave":
            remna = RemnawaveAPI(server_info["api_url"])
            logged_in = await remna.login(REMNAWAVE_LOGIN, REMNAWAVE_PASSWORD)
            if not logged_in:
                raise ValueError(f"❌ Не удалось авторизоваться в Remnawave ({selected_country})")

            expire_at = datetime.utcfromtimestamp(expiry_timestamp / 1000).isoformat() + "Z"
            user_data = {
                "username": email,
                "trafficLimitStrategy": "NO_RESET",
                "expireAt": expire_at,
                "telegramId": tg_id,
                "activeUserInbounds": [server_info["inbound_id"]],
            }
            result = await remna.create_user(user_data)
            if not result:
                raise ValueError("❌ Ошибка при создании пользователя в Remnawave")

            client_id = result.get("uuid")
            remnawave_link = result.get("subscriptionUrl")
            logger.info(f"[Key Creation] Remnawave пользователь создан: {result}")

        if panel_type == "3x-ui":
            semaphore = asyncio.Semaphore(2)
            await create_client_on_server(
                server_info=server_info,
                tg_id=tg_id,
                client_id=client_id,
                email=email,
                expiry_timestamp=expiry_timestamp,
                semaphore=semaphore,
            )
            public_link = f"{PUBLIC_LINK}{email}/{tg_id}"

        logger.info(f"[Key Creation] Подписка создана для пользователя {tg_id} на сервере {selected_country}")

        if old_key_name:
            await session.execute(
                "UPDATE keys SET server_id = $1 WHERE tg_id = $2 AND email = $3",
                selected_country,
                tg_id,
                old_key_name,
            )
        else:
            await session.execute(
                """
                INSERT INTO keys (tg_id, client_id, email, created_at, expiry_time, key, remnawave_link, server_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                tg_id,
                client_id,
                email,
                created_at,
                expiry_timestamp,
                public_link,
                remnawave_link,
                selected_country,
            )
            data = await state.get_data()
            if data.get("is_trial"):
                trial_status = await get_trial(tg_id, session)
                if trial_status in [0, -1]:
                    await update_trial(tg_id, 1, session)
            if data.get("plan_id"):
                plan_price = RENEWAL_PRICES.get(data["plan_id"])
                await update_balance(tg_id, -plan_price, session)

    except Exception as e:
        logger.error(f"[Key Finalize] Ошибка при создании ключа для пользователя {tg_id}: {e}")
        await callback_query.message.answer("❌ Произошла ошибка при создании подписки. Попробуйте снова.")
        return

    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=SUPPORT, url=SUPPORT_CHAT_URL))
    if CONNECT_PHONE_BUTTON:
        builder.row(InlineKeyboardButton(text=CONNECT_PHONE, callback_data=f"connect_phone|{key_name}"))
        builder.row(
            InlineKeyboardButton(text=PC_BUTTON, callback_data=f"connect_pc|{email}"),
            InlineKeyboardButton(text=TV_BUTTON, callback_data=f"connect_tv|{email}"),
        )
    else:
        builder.row(InlineKeyboardButton(text=CONNECT_DEVICE, callback_data=f"connect_device|{key_name}"))

    builder.row(InlineKeyboardButton(text=MAIN_MENU, callback_data="profile"))

    remaining_time = expiry_time - datetime.now(moscow_tz)
    days = remaining_time.days

    link_to_show = public_link or remnawave_link or "Ссылка не найдена"
    key_message_text = key_message_success(link_to_show, f"⏳ Осталось дней: {days} 📅")

    await edit_or_send_message(
        target_message=callback_query.message,
        text=key_message_text,
        reply_markup=builder.as_markup(),
        media_path="img/pic.jpg",
    )

    if state:
        await state.clear()


async def check_server_availability(server_info: dict) -> bool:
    """
    Проверяет доступность сервера (3x-ui или Remnawave).
    """
    panel_type = server_info.get("panel_type", "3x-ui").lower()
    server_name = server_info.get("server_name", "unknown")

    try:
        if panel_type == "remnawave":
            remna = RemnawaveAPI(server_info["api_url"])
            await asyncio.wait_for(remna.login(REMNAWAVE_LOGIN, REMNAWAVE_PASSWORD), timeout=5.0)
            logger.info(f"[Ping] Remnawave сервер {server_name} доступен.")
            return True

        else:
            xui = AsyncApi(
                server_info["api_url"],
                username=ADMIN_USERNAME,
                password=ADMIN_PASSWORD,
                logger=logger,
            )
            await asyncio.wait_for(xui.login(), timeout=5.0)
            logger.info(f"[Ping] 3x-ui сервер {server_name} доступен.")
            return True

    except asyncio.TimeoutError:
        logger.warning(f"[Ping] Сервер {server_name} не ответил вовремя.")
        return False
    except Exception as e:
        logger.warning(f"[Ping] Ошибка при проверке сервера {server_name}: {e}")
        return False

