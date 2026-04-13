from fastapi import APIRouter

from config import (
    BALANCE_BUTTON,
    CAPTCHA_ENABLE,
    CHANNEL_EXISTS,
    CHANNEL_REQUIRED,
    DONATIONS_ENABLE,
    GIFT_BUTTON,
    HAPP_CRYPTOLINK,
    HWID_RESET_BUTTON,
    INSTRUCTIONS_BUTTON,
    PROJECT_NAME,
    REFERRAL_BUTTON,
    REFERRAL_QR,
    REMNAWAVE_WEBAPP,
    REMNAWAVE_WEBAPP_OPEN_IN_BROWSER,
    TOP_REFERRAL_BUTTON,
    TRIAL_TIME_DISABLE,
    USE_COUNTRY_SELECTION,
    USERNAME_BOT,
    TELEGRAM_WEBAPP_DIRECT_LINK,
    TELEGRAM_WEBAPP_SHORT_NAME,
)
from core.bootstrap import BUTTONS_CONFIG, MODES_CONFIG, MONEY_CONFIG, PAYMENTS_CONFIG
from core.settings.web_config import WEB_CONFIG
from core.settings.money_config import get_currency_mode
from services.payments.providers import PROVIDERS_BASE, TELEGRAM_ONLY_PROVIDER_IDS, WEB_LINK_PROVIDER_IDS

router = APIRouter(tags=["Root"])


def _telegram_web_app_return_base() -> str | None:
    direct = str(TELEGRAM_WEBAPP_DIRECT_LINK or "").strip().rstrip("/")
    if direct:
        if direct.lower().startswith("http://"):
            direct = "https://" + direct[7:]
        if direct.lower().startswith("https://t.me/"):
            return direct
    bot = USERNAME_BOT.replace("@", "").strip()
    sn = str(TELEGRAM_WEBAPP_SHORT_NAME or "").strip()
    if bot and sn:
        return f"https://t.me/{bot}/{sn}"
    if bot:
        return f"https://t.me/{bot}"
    return None


def _partner_feature_enabled() -> bool:
    try:
        from modules.partner_program import settings as partner_settings
    except Exception:
        return False
    for key in ("PARTNER_PROGRAM_ENABLED", "PARTNER_BUTTON_ENABLED", "PARTNER_ENABLED"):
        value = getattr(partner_settings, key, None)
        if isinstance(value, bool):
            return value
    return True


@router.get("/api", include_in_schema=False)
async def root():
    return {"message": "SoloBot API v2", "docs": "/api/docs"}


@router.get("/api/version", include_in_schema=True)
async def version():
    return {"version": 2, "api": "v2"}


@router.get("/api/telegram-widget-bot", include_in_schema=True)
async def telegram_widget_bot():
    """Имя бота и имя проекта для веб-клиента."""
    return {
        "bot_username": USERNAME_BOT.replace("@", ""),
        "project_name": (PROJECT_NAME or "Solo").strip() if isinstance(PROJECT_NAME, str) else "Solo",
    }


@router.get("/api/site-config", include_in_schema=True)
async def site_config():
    """Настройки витрины и кабинета для веб-клиента (флаги из runtime-конфигов бота)."""
    bot_username = USERNAME_BOT.replace("@", "").strip()
    pay_flags = {name: bool(PAYMENTS_CONFIG.get(name)) for name in PROVIDERS_BASE}
    any_pay = any(pay_flags.values())
    web_link_provider_ids = [provider_id for provider_id in WEB_LINK_PROVIDER_IDS if pay_flags.get(provider_id, False)]
    telegram_only_provider_ids = [
        provider_id for provider_id in TELEGRAM_ONLY_PROVIDER_IDS if pay_flags.get(provider_id, False)
    ]
    currency_mode, currency_one_screen = get_currency_mode()
    try:
        cb_raw = MONEY_CONFIG.get("CASHBACK", 0)
        cashback_percent = float(cb_raw) if cb_raw not in (None, False) else 0.0
    except (TypeError, ValueError):
        cashback_percent = 0.0

    webapp_short = str(TELEGRAM_WEBAPP_SHORT_NAME or "").strip() or None
    webapp_return_base = _telegram_web_app_return_base()
    return {
        "bot_username": bot_username or None,
        "telegram_web_app_short_name": webapp_short,
        "telegram_web_app_return_base": webapp_return_base,
        "project_name": (PROJECT_NAME or "Solo").strip() if isinstance(PROJECT_NAME, str) else "Solo",
        "site_mode": str(WEB_CONFIG.get("SITE_MODE", "full")).strip() or "full",
        "auth": {
            "telegram_login_enabled": bool(bot_username),
            "email_code_login_enabled": bool(MODES_CONFIG.get("WEB_EMAIL_CODE_LOGIN_ENABLED", True)),
        },
        "mobile": {
            "prefer_mini_app_on_telegram_mobile": bool(
                MODES_CONFIG.get("PREFER_MINI_APP_ON_TELEGRAM_MOBILE", False)
            ),
        },
        "features": {
            "channel_enabled": bool(BUTTONS_CONFIG.get("CHANNEL_BUTTON_ENABLE", CHANNEL_EXISTS)),
            "donations_enabled": bool(BUTTONS_CONFIG.get("DONATIONS_BUTTON_ENABLE", DONATIONS_ENABLE)),
            "balance_enabled": bool(BUTTONS_CONFIG.get("BALANCE_BUTTON_ENABLE", BALANCE_BUTTON)),
            "referral_qr_enabled": bool(BUTTONS_CONFIG.get("REFERRAL_QR_BUTTON_ENABLE", REFERRAL_QR)),
            "instructions_enabled": bool(BUTTONS_CONFIG.get("INSTRUCTIONS_BUTTON_ENABLE", INSTRUCTIONS_BUTTON)),
            "gift_enabled": bool(BUTTONS_CONFIG.get("GIFT_BUTTON_ENABLE", GIFT_BUTTON)),
            "referral_enabled": bool(BUTTONS_CONFIG.get("REFERRAL_BUTTON_ENABLED", REFERRAL_BUTTON)),
            "top_referral_enabled": bool(BUTTONS_CONFIG.get("TOP_REFERRAL_BUTTON_ENABLE", TOP_REFERRAL_BUTTON)),
            "coupon_enabled": bool(BUTTONS_CONFIG.get("COUPON_BUTTON_ENABLE", True)),
            "qr_subscription_enabled": bool(MODES_CONFIG.get("HAPP_CRYPTOLINK_ENABLED", HAPP_CRYPTOLINK)),
            "hwid_reset_enabled": bool(BUTTONS_CONFIG.get("HWID_RESET_BUTTON_ENABLE", HWID_RESET_BUTTON)),
            "country_selection_enabled": bool(
                MODES_CONFIG.get("COUNTRY_SELECTION_ENABLED", USE_COUNTRY_SELECTION)
            ),
            "captcha_enabled": bool(MODES_CONFIG.get("CAPTCHA_ENABLED", CAPTCHA_ENABLE)),
            "channel_check_enabled": bool(MODES_CONFIG.get("CHANNEL_CHECK_ENABLED", CHANNEL_REQUIRED)),
            "trial_enabled": not bool(MODES_CONFIG.get("TRIAL_TIME_DISABLED", TRIAL_TIME_DISABLE)),
            "mini_app_enabled": bool(MODES_CONFIG.get("REMNAWAVE_WEBAPP_ENABLED", REMNAWAVE_WEBAPP)),
            "mini_app_open_in_browser": bool(
                MODES_CONFIG.get("REMNAWAVE_WEBAPP_OPEN_IN_BROWSER", REMNAWAVE_WEBAPP_OPEN_IN_BROWSER)
            ),
            "partner_enabled": bool(_partner_feature_enabled()),
        },
        "payments": {
            "any_enabled": any_pay,
            "any_web_link_enabled": bool(web_link_provider_ids),
            "any_telegram_only_enabled": bool(telegram_only_provider_ids),
            "web_link_provider_ids": web_link_provider_ids,
            "telegram_only_provider_ids": telegram_only_provider_ids,
            "yookassa_enabled": pay_flags.get("YOOKASSA", False),
            "yoomoney_enabled": pay_flags.get("YOOMONEY", False),
            "robokassa_enabled": pay_flags.get("ROBOKASSA", False),
            "kassai_cards_enabled": pay_flags.get("KASSAI_CARDS", False),
            "kassai_sbp_enabled": pay_flags.get("KASSAI_SBP", False),
            "tribute_enabled": pay_flags.get("TRIBUTE", False),
            "heleket_enabled": pay_flags.get("HELEKET", False),
            "cryptobot_enabled": pay_flags.get("CRYPTOBOT", False),
            "freekassa_enabled": pay_flags.get("FREEKASSA", False),
            "stars_enabled": pay_flags.get("STARS", False),
        },
        "money": {
            "currency_mode": currency_mode,
            "currency_one_screen": currency_one_screen,
            "cashback_enabled": cashback_percent > 0,
            "cashback_percent": cashback_percent,
        },
    }
