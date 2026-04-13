import json

from logger import logger

try:
    from pywebpush import webpush, WebPushException
    _WEBPUSH_AVAILABLE = True
except ImportError:
    _WEBPUSH_AVAILABLE = False

try:
    from config import VAPID_PRIVATE_KEY, VAPID_PUBLIC_KEY, VAPID_CLAIMS_EMAIL
except ImportError:
    VAPID_PRIVATE_KEY = ""
    VAPID_PUBLIC_KEY = ""
    VAPID_CLAIMS_EMAIL = ""


def push_enabled() -> bool:
    return _WEBPUSH_AVAILABLE and bool(VAPID_PRIVATE_KEY) and bool(VAPID_PUBLIC_KEY)


async def send_push_notification(
    subscription_info: dict,
    title: str,
    body: str,
    url: str = "/dashboard",
    tag: str = "solo-notification",
) -> bool:
    """Отправить push-уведомление одному подписчику."""
    if not push_enabled():
        logger.debug("[WebPush] push отключён (нет VAPID ключей или pywebpush)")
        return False

    payload = json.dumps({
        "title": title,
        "body": body,
        "url": url,
        "tag": tag,
    })

    try:
        webpush(
            subscription_info=subscription_info,
            data=payload,
            vapid_private_key=VAPID_PRIVATE_KEY,
            vapid_claims={"sub": f"mailto:{VAPID_CLAIMS_EMAIL}"},
        )
        logger.debug("[WebPush] уведомление отправлено: {}", title)
        return True
    except WebPushException as e:
        logger.error("[WebPush] ошибка отправки: {}", e)
        return False
    except Exception as e:
        logger.error("[WebPush] неожиданная ошибка: {}", e)
        return False


async def send_push_to_many(
    subscriptions: list[dict],
    title: str,
    body: str,
    url: str = "/dashboard",
    tag: str = "solo-notification",
) -> int:
    """Отправить push нескольким подписчикам. Возвращает количество успешных."""
    sent = 0
    for sub in subscriptions:
        if await send_push_notification(sub, title, body, url, tag):
            sent += 1
    return sent
