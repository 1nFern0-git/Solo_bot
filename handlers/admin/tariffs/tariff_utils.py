from aiogram.types import InlineKeyboardMarkup

from database.models import Tariff

from .keyboard import build_single_tariff_kb


MAX_TARIFF_NAME_LENGTH = 40
MAX_SUBGROUP_TITLE_LENGTH = 40


def validate_tariff_name(name: str) -> tuple[bool, str]:
    if len(name) > MAX_TARIFF_NAME_LENGTH:
        return False, f"Название тарифа слишком длинное. Максимум {MAX_TARIFF_NAME_LENGTH} символов."
    return True, ""


def validate_subgroup_title(title: str) -> tuple[bool, str]:
    if len(title) > MAX_SUBGROUP_TITLE_LENGTH:
        return False, f"Название подгруппы слишком длинное. Максимум {MAX_SUBGROUP_TITLE_LENGTH} символов."
    return True, ""


def tariff_to_dict(tariff) -> dict:
    if isinstance(tariff, dict):
        return tariff
    return {
        "id": tariff.id,
        "name": tariff.name,
        "price_rub": tariff.price_rub,
        "group_code": tariff.group_code,
        "subgroup_title": tariff.subgroup_title,
        "sort_order": tariff.sort_order,
    }


def render_tariff_card(tariff: Tariff) -> tuple[str, InlineKeyboardMarkup]:
    traffic_text = f"{tariff.traffic_limit} ГБ" if tariff.traffic_limit else "Безлимит"
    device_text = f"{tariff.device_limit}" if tariff.device_limit is not None else "Безлимит"
    sort_order = getattr(tariff, "sort_order", 1)
    vless_text = "Да" if getattr(tariff, "vless", False) else "Нет"
    configurable = bool(getattr(tariff, "configurable", False))
    configurable_text = "Включен" if configurable else "Выключен"
    external_squad_text = getattr(tariff, "external_squad", None) or "Не задан"

    text = (
        f"<b>📄 Тариф: {tariff.name}</b>\n"
        f"🆔 ID: <code>{tariff.id}</code>\n\n"
        f"📁 Группа: <code>{tariff.group_code}</code>\n"
        f"📅 Длительность: <b>{tariff.duration_days} дней</b>\n"
        f"💰 Стоимость: <b>{tariff.price_rub}₽</b>\n"
        f"📦 Трафик: <b>{traffic_text}</b>\n"
        f"📱 Устройств: <b>{device_text}</b>\n"
        f"🔗 VLESS: <b>{vless_text}</b>\n"
        f"⚙️ Конфигуратор: <b>{configurable_text}</b>\n"
        f"Внешний сквад: <b>{external_squad_text}</b>\n"
        f"🔢 Позиция: <b>{sort_order}</b>\n"
        f"{'✅ Активен' if tariff.is_active else '⛔ Отключен'}"
    )

    return text, build_single_tariff_kb(tariff.id, tariff.group_code, configurable=configurable)
