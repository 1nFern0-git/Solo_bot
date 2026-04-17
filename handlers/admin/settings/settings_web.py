from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.settings.web_config import WEB_CONFIG, update_web_config
from database import async_session_maker
from handlers.buttons import BACK

from ..panel.keyboard import AdminPanelCallback, build_admin_back_btn


router = Router(name="admin_settings_web")


class WebSettingsState(StatesGroup):
    waiting_for_url = State()


def build_settings_web_kb() -> InlineKeyboardBuilder:
    builder = InlineKeyboardBuilder()

    enabled = bool(WEB_CONFIG.get("WEB_ENABLED", False))
    url = str(WEB_CONFIG.get("SITE_URL") or "не указан")

    builder.row(
        InlineKeyboardButton(
            text=f"{'✅' if enabled else '❌'} Сайт {'включён' if enabled else 'выключен'}",
            callback_data=AdminPanelCallback(action="settings_web_toggle").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text=f"🌐 URL: {url}",
            callback_data=AdminPanelCallback(action="settings_web_url").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="🔄 Сбросить сайт к исходнику",
            callback_data=AdminPanelCallback(action="settings_web_reset_ask").pack(),
        )
    )
    builder.row(build_admin_back_btn("settings"))

    return builder


@router.callback_query(AdminPanelCallback.filter(F.action == "settings_web"))
async def open_web_settings(callback: CallbackQuery) -> None:
    enabled = bool(WEB_CONFIG.get("WEB_ENABLED", False))
    url = str(WEB_CONFIG.get("SITE_URL") or "не указан")

    text = (
        "<b>🌐 Настройки веб-сайта</b>\n\n"
        f"Статус: {'✅ Включён' if enabled else '❌ Выключен'}\n"
        f"URL: <code>{url}</code>\n\n"
        "Сайт может работать на отдельном домене и сервере.\n"
        "При выключении кнопка «Личный кабинет» скрывается из бота."
    )
    await callback.message.edit_text(
        text=text,
        reply_markup=build_settings_web_kb().as_markup(),
    )
    await callback.answer()


@router.callback_query(AdminPanelCallback.filter(F.action == "settings_web_toggle"))
async def toggle_web_enabled(callback: CallbackQuery) -> None:
    current = bool(WEB_CONFIG.get("WEB_ENABLED", False))
    new_config = dict(WEB_CONFIG)
    new_config["WEB_ENABLED"] = not current

    async with async_session_maker() as session:
        await update_web_config(session, new_config)

    status = "✅ Сайт включён" if new_config["WEB_ENABLED"] else "❌ Сайт выключен"
    await callback.answer(status, show_alert=True)

    enabled = new_config["WEB_ENABLED"]
    url = str(new_config.get("SITE_URL") or "не указан")
    text = (
        "<b>🌐 Настройки веб-сайта</b>\n\n"
        f"Статус: {'✅ Включён' if enabled else '❌ Выключен'}\n"
        f"URL: <code>{url}</code>\n\n"
        "Сайт может работать на отдельном домене и сервере.\n"
        "При выключении кнопка «Личный кабинет» скрывается из бота."
    )
    await callback.message.edit_text(
        text=text,
        reply_markup=build_settings_web_kb().as_markup(),
    )


@router.callback_query(AdminPanelCallback.filter(F.action == "settings_web_url"))
async def prompt_web_url(callback: CallbackQuery, state: FSMContext) -> None:
    current = str(WEB_CONFIG.get("SITE_URL") or "")
    text = (
        "<b>🌐 Введите URL сайта</b>\n\n"
        f"Текущий: <code>{current or 'не указан'}</code>\n\n"
        "Отправьте полный URL (с https://).\n"
        "Пример: <code>https://my-vpn.com</code>\n\n"
        "Отправьте <code>-</code> чтобы очистить."
    )
    await callback.message.edit_text(text=text)
    await state.set_state(WebSettingsState.waiting_for_url)
    await callback.answer()


@router.callback_query(AdminPanelCallback.filter(F.action == "settings_web_reset_ask"))
async def ask_reset_site(callback: CallbackQuery) -> None:
    text = (
        "<b>⚠️ Сброс сайта к исходнику</b>\n\n"
        "Действие удалит:\n"
        "• все страницы, блоки, темы и варианты\n"
        "• всех веб-пользователей (включая админа сайта)\n"
        "• флаг «сайт проинициализирован»\n\n"
        "Биллинг-данные (пользователи бота, ключи, платежи) не трогаются.\n\n"
        "После сброса админ сайта пересоздаётся из переменных окружения "
        "<code>WEB_ADMIN_LOGIN</code> / <code>WEB_ADMIN_PASSWORD</code>.\n\n"
        "<b>Действие необратимо.</b>"
    )
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text="❌ Отмена",
            callback_data=AdminPanelCallback(action="settings_web").pack(),
        )
    )
    builder.row(
        InlineKeyboardButton(
            text="⚠️ Да, сбросить сайт",
            callback_data=AdminPanelCallback(action="settings_web_reset_do").pack(),
        )
    )
    await callback.message.edit_text(text=text, reply_markup=builder.as_markup())
    await callback.answer()


@router.callback_query(AdminPanelCallback.filter(F.action == "settings_web_reset_do"))
async def do_reset_site(callback: CallbackQuery, session=None) -> None:
    await callback.answer()
    await callback.message.edit_text(text="<b>⏳ Сбрасываю сайт...</b>")

    from middlewares.session import release_session_early
    from services.site_reset import reset_site

    if session is not None:
        await release_session_early(session)

    try:
        async with async_session_maker() as s:
            await reset_site(s)
            await s.commit()
    except Exception as exc:
        from html import escape as html_escape

        safe = html_escape(str(exc))[:2000]
        await callback.message.edit_text(
            text=f"<b>❌ Не удалось сбросить сайт</b>\n\n<code>{safe}</code>",
            reply_markup=build_settings_web_kb().as_markup(),
        )
        return

    text = (
        "<b>✅ Сайт сброшен к исходнику</b>\n\n"
        "Все веб-страницы, блоки и темы удалены. Админ пересоздан из env.\n"
        "Откройте сайт и пройдите путь первой установки заново."
    )
    await callback.message.edit_text(
        text=text,
        reply_markup=build_settings_web_kb().as_markup(),
    )


@router.message(WebSettingsState.waiting_for_url)
async def set_web_url(message: Message, state: FSMContext) -> None:
    url = message.text.strip() if message.text else ""

    if url == "-":
        url = ""
    elif url and not url.startswith("http"):
        await message.answer("❌ URL должен начинаться с http:// или https://")
        return

    url = url.rstrip("/")

    new_config = dict(WEB_CONFIG)
    new_config["SITE_URL"] = url

    async with async_session_maker() as session:
        await update_web_config(session, new_config)

    await state.clear()

    enabled = new_config.get("WEB_ENABLED", False)
    display_url = url or "не указан"
    text = (
        "<b>🌐 Настройки веб-сайта</b>\n\n"
        f"Статус: {'✅ Включён' if enabled else '❌ Выключен'}\n"
        f"URL: <code>{display_url}</code>\n\n"
        "Сайт может работать на отдельном домене и сервере.\n"
        "При выключении кнопка «Личный кабинет» скрывается из бота."
    )
    await message.answer(
        text=text,
        reply_markup=build_settings_web_kb().as_markup(),
    )
