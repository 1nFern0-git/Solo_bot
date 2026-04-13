import asyncio
import os
import time

from collections import deque
from datetime import datetime

import aiofiles
import pytz

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession

from database import async_session_maker, create_blocked_user
from services.tariffs.tariff_display import get_key_tariff_display
from handlers.utils import format_hours, format_minutes, get_russian_month
from logger import logger


moscow_tz = pytz.timezone("Europe/Moscow")


class NotificationRateLimiter:
    def __init__(self, max_rate: int = 35, window: float = 1.0) -> None:
        self.max_rate = max_rate
        self.window = window
        self.send_times = deque()
        self.lock = asyncio.Lock()

    def _clean_old_timestamps(self, current_time: float):
        cutoff_time = current_time - self.window
        while self.send_times and self.send_times[0] <= cutoff_time:
            self.send_times.popleft()

    async def acquire(self):
        async with self.lock:
            while True:
                now = time.time()
                self._clean_old_timestamps(now)
                if len(self.send_times) < self.max_rate:
                    self.send_times.append(now)
                    return
                oldest_timestamp = self.send_times[0]
                time_to_wait = (oldest_timestamp + self.window) - now
                if time_to_wait > 0:
                    await asyncio.sleep(time_to_wait + 0.001)


class NotificationMessage:
    def __init__(self, tg_id: int, text: str, photo: str | None = None, keyboard=None) -> None:
        self.tg_id = tg_id
        self.text = text
        self.photo = photo
        self.keyboard = keyboard
        self.retry_after = None
        self.attempts = 0


class FastNotificationSender:
    def __init__(self, bot: Bot, session: AsyncSession | None, messages_per_second: int = 35) -> None:
        self.bot = bot
        self.session = session
        self.rate_limiter = NotificationRateLimiter(max_rate=messages_per_second)
        self.blocked_users = set()
        self.queue = asyncio.Queue()
        self.delayed_queue = asyncio.Queue()
        self.results = []
        self.total_sent = 0
        self.is_running = False

    async def _send_single_message(self, msg: NotificationMessage) -> bool:
        try:
            await self.rate_limiter.acquire()

            if msg.photo:
                photo_path = os.path.join("img", msg.photo)
                if os.path.isfile(photo_path):
                    async with aiofiles.open(photo_path, "rb") as f:
                        image_data = await f.read()
                    buffered_photo = BufferedInputFile(image_data, filename=msg.photo)
                    await self.bot.send_photo(
                        chat_id=msg.tg_id, photo=buffered_photo, caption=msg.text, reply_markup=msg.keyboard
                    )
                else:
                    await self.bot.send_message(chat_id=msg.tg_id, text=msg.text, reply_markup=msg.keyboard)
            else:
                await self.bot.send_message(chat_id=msg.tg_id, text=msg.text, reply_markup=msg.keyboard)
            return True

        except TelegramRetryAfter as e:
            msg.retry_after = e.retry_after
            msg.attempts += 1
            await self.delayed_queue.put(msg)
            return False

        except TelegramForbiddenError:
            self.blocked_users.add(msg.tg_id)
            return False

        except TelegramBadRequest as e:
            if "chat not found" in str(e).lower():
                self.blocked_users.add(msg.tg_id)
            return False

        except Exception:
            return False

    async def _process_delayed_messages(self):
        while self.is_running:
            try:
                if not self.delayed_queue.empty():
                    msg = await asyncio.wait_for(self.delayed_queue.get(), timeout=0.1)
                    if msg.retry_after:
                        await asyncio.sleep(msg.retry_after)
                        msg.retry_after = None
                    if msg.attempts < 3:
                        await self.queue.put(msg)
                    else:
                        self.results.append(False)
                else:
                    await asyncio.sleep(0.1)
            except TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(0.1)

    async def _worker(self):
        while self.is_running:
            try:
                msg = await asyncio.wait_for(self.queue.get(), timeout=0.1)
                success = await self._send_single_message(msg)
                if success:
                    self.total_sent += 1
                    self.results.append(True)
                elif msg.attempts == 0:
                    self.results.append(False)
                self.queue.task_done()
            except TimeoutError:
                continue
            except Exception:
                await asyncio.sleep(0.1)

    async def _save_blocked_users(self):
        if not self.blocked_users:
            return
        try:
            from database.bans import save_blocked_user_ids

            async with async_session_maker() as session:
                await save_blocked_user_ids(session, list(self.blocked_users))
                await session.commit()
            logger.info(f"📝 Добавлено до {len(self.blocked_users)} пользователей в blocked_users")
        except Exception as e:
            logger.error(f"❌ Ошибка при сохранении заблокированных пользователей: {e}")

    async def send_all(self, messages: list[dict], workers: int = 15) -> list[bool]:
        if not messages:
            return []

        self.is_running = True
        self.results = []
        self.total_sent = 0
        self.blocked_users = set()
        start_time = time.time()

        for msg_data in messages:
            msg = NotificationMessage(
                tg_id=msg_data["tg_id"],
                text=msg_data["text"],
                photo=msg_data.get("photo"),
                keyboard=msg_data.get("keyboard"),
            )
            await self.queue.put(msg)

        worker_tasks = [asyncio.create_task(self._worker()) for _ in range(workers)]
        delayed_task = asyncio.create_task(self._process_delayed_messages())

        await self.queue.join()

        await asyncio.sleep(0.5)
        while not self.delayed_queue.empty():
            await asyncio.sleep(0.5)

        self.is_running = False

        for task in worker_tasks:
            task.cancel()
        delayed_task.cancel()

        await asyncio.gather(*worker_tasks, delayed_task, return_exceptions=True)
        await self._save_blocked_users()

        duration = time.time() - start_time
        speed = self.total_sent / duration if duration > 0 else 0
        logger.info(f"📨 Уведомления: {self.total_sent}/{len(messages)} за {duration:.1f}s ({speed:.1f} msg/s)")

        return self.results


async def send_messages_with_limit(
    bot: Bot,
    messages: list[dict],
    session: AsyncSession = None,
    source_file: str = None,
    messages_per_second: int = 35,
):
    sender = FastNotificationSender(bot, session, messages_per_second)
    return await sender.send_all(messages)


async def try_add_blocked_user(tg_id: int, session: AsyncSession, source_file: str | None):
    if source_file == "special_notifications" and session:
        try:
            await create_blocked_user(session, tg_id)
            logger.info(f"Пользователь {tg_id} добавлен в blocked_users.")
        except Exception as e:
            logger.warning(f"Не удалось добавить {tg_id} в blocked_users: {e}")


def rate_limited_send(func):
    async def wrapper(*args, **kwargs):
        while True:
            try:
                return await func(*args, **kwargs)
            except TelegramRetryAfter as e:
                retry_in = int(e.retry_after) + 1
                logger.warning(f"⚠️ Flood control: повтор через {retry_in} сек.")
                await asyncio.sleep(retry_in)
            except TelegramForbiddenError:
                tg_id = kwargs.get("tg_id") or args[1]
                logger.warning(f"🚫 Бот заблокирован пользователем {tg_id}.")
                return False
            except TelegramBadRequest:
                tg_id = kwargs.get("tg_id") or args[1]
                logger.warning(f"🚫 Чат не найден для пользователя {tg_id}.")
                return False
            except Exception as e:
                tg_id = kwargs.get("tg_id") or args[1]
                logger.error(f"❌ Ошибка отправки сообщения пользователю {tg_id}: {e}")
                return False

    return wrapper


async def send_notification(
    bot: Bot,
    tg_id: int,
    image_filename: str | None,
    caption: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> bool:
    if image_filename is None:
        return await _send_text_notification(bot, tg_id, caption, keyboard)

    photo_path = os.path.join("img", image_filename)
    if os.path.isfile(photo_path):
        return await _send_photo_notification(bot, tg_id, photo_path, image_filename, caption, keyboard)
    else:
        logger.warning(f"Файл с изображением не найден: {photo_path}")
        return await _send_text_notification(bot, tg_id, caption, keyboard)


@rate_limited_send
async def _send_photo_notification(
    bot: Bot,
    tg_id: int,
    photo_path: str,
    image_filename: str,
    caption: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        async with aiofiles.open(photo_path, "rb") as image_file:
            image_data = await image_file.read()
        buffered_photo = BufferedInputFile(image_data, filename=image_filename)
        await bot.send_photo(tg_id, buffered_photo, caption=caption, reply_markup=keyboard)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False
    except Exception as e:
        logger.error(f"Ошибка отправки фото для пользователя {tg_id}: {e}")
        return await _send_text_notification(bot, tg_id, caption, keyboard)


@rate_limited_send
async def _send_text_notification(
    bot: Bot,
    tg_id: int,
    caption: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> bool:
    try:
        await bot.send_message(tg_id, caption, reply_markup=keyboard)
        return True
    except (TelegramForbiddenError, TelegramBadRequest):
        return False
    except Exception as e:
        logger.error(f"Неизвестная ошибка при отправке сообщения для пользователя {tg_id}: {e}")
        return False


async def prepare_key_expiry_data(key, session: AsyncSession, current_time: int) -> dict:
    """Готовит данные об истечении подписки для уведомлений."""
    if isinstance(key, dict):
        expiry_timestamp = key.get("expiry_time")
        email = key.get("email") or ""
        record = dict(key)
    else:
        expiry_timestamp = getattr(key, "expiry_time", None)
        email = getattr(key, "email", "") or ""
        record = {
            "tariff_id": getattr(key, "tariff_id", None),
            "server_id": getattr(key, "server_id", None),
            "client_id": getattr(key, "client_id", None),
            "selected_device_limit": getattr(key, "selected_device_limit", None),
            "selected_traffic_limit": getattr(key, "selected_traffic_limit", None),
        }

    if not expiry_timestamp:
        return {
            "hours_left_formatted": "",
            "formatted_expiry_date": "",
            "tariff_name": "—",
            "tariff_details": "",
        }

    delta_ms = max(0, expiry_timestamp - current_time)
    total_minutes = delta_ms // (60 * 1000)
    hours_left = total_minutes // 60
    minutes_left = total_minutes % 60

    if hours_left > 0 or minutes_left > 0:
        parts = []
        if hours_left > 0:
            parts.append(format_hours(hours_left))
        if minutes_left > 0:
            parts.append(format_minutes(minutes_left))
        hours_left_formatted = f"⏳ Осталось времени: {' '.join(parts)}"
    else:
        hours_left_formatted = "⏳ Последний день подписки!"

    expiry_datetime = datetime.fromtimestamp(expiry_timestamp / 1000, tz=moscow_tz)
    month_name = get_russian_month(expiry_datetime)
    formatted_expiry_date = expiry_datetime.strftime(f"%d {month_name} %Y, %H:%M (МСК)")

    tariff_name = "—"
    subgroup_title = ""
    traffic_limit_gb = 0
    device_limit = 0

    try:
        name, subgroup_title, traffic_limit_gb, device_limit, _, _ = await get_key_tariff_display(
            session=session,
            key_record=record,
        )
        if name:
            tariff_name = name
    except Exception as error:
        logger.warning(f"[NOTIFY] Ошибка при получении тарифных лимитов для {email}: {error}")

    traffic_text = "безлимит" if traffic_limit_gb == 0 else f"{traffic_limit_gb} ГБ"
    devices_text = "безлимит" if device_limit == 0 else str(device_limit)

    lines = []
    if subgroup_title:
        lines.append(subgroup_title)
    lines.append(f"Трафик: {traffic_text}")
    lines.append(f"Устройств: {devices_text}")
    tariff_details = "\n" + "\n".join(lines) if lines else ""

    return {
        "hours_left_formatted": hours_left_formatted,
        "formatted_expiry_date": formatted_expiry_date,
        "tariff_name": tariff_name,
        "tariff_details": tariff_details,
    }
