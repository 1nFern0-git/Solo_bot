import json

from config import REDIS_URL
from logger import logger


def payment_events_channel(legacy_user_ref: int) -> str:
    return f"payment_events:user:{int(legacy_user_ref)}"


async def publish_payment_event(
    *,
    legacy_user_ref: int,
    status: str,
    flow: str | None = None,
    amount: float | int | None = None,
) -> None:
    try:
        from redis.asyncio import from_url

        payload: dict[str, str | float | int] = {"status": str(status)}
        if flow:
            payload["flow"] = str(flow)
        if amount is not None:
            payload["amount"] = float(amount)
        client = from_url(REDIS_URL, encoding="utf-8", decode_responses=True, max_connections=8)
        try:
            subscribers = await client.publish(
                payment_events_channel(int(legacy_user_ref)),
                json.dumps(payload, ensure_ascii=False),
            )
            logger.info(
                f"[Payments] Event published: user_ref={legacy_user_ref}, status={status}, "
                f"flow={flow}, subscribers={subscribers}"
            )
        finally:
            await client.aclose()
    except Exception as e:
        logger.warning(f"[Payments] publish_payment_event failed: {e}")
