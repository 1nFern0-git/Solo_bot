from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import (
    BaseModel,
    Field as PydanticField,
)
from sqlalchemy.ext.asyncio import AsyncSession

from api.depends import (
    bind_identity_actor,
    get_session,
    set_auth_cookie,
    set_is_admin_cookie,
    verify_identity_token,
)
from api.v2.routes.auth._common import TELEGRAM_LOGIN_MAX_AGE, TOKEN_TTL_HINT, _client_ip
from api.v2.schemas.identities import (
    IdentityResponse,
    LinkTelegramRequest,
    LoginResponse,
    LoginTelegramRequest,
)
from config import API_TOKEN
from database import identities as idb
from logger import logger
from utils.telegram_login import verify_telegram_login


router = APIRouter()


class LoginTelegramWebAppRequest(BaseModel):
    init_data: str = PydanticField(..., min_length=1)


@router.post("/login-telegram", response_model=LoginResponse)
async def login_telegram(
    body: LoginTelegramRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    (
        """Вход через Telegram Login Widget (кнопка на сайте). По tg_id находим или создаём Identity, выдаём токен. Срок действия токена: """
        + TOKEN_TTL_HINT
        + "."
    )
    payload = body.model_dump(mode="json")
    if not verify_telegram_login(payload, API_TOKEN, max_age_seconds=TELEGRAM_LOGIN_MAX_AGE):
        raise HTTPException(status_code=401, detail="Неверная подпись или устаревшие данные от Telegram")
    identity = await idb.get_or_create_identity_for_tg(session, body.id)
    await bind_identity_actor(request, session, identity)
    token = await idb.issue_token_for_identity(session, identity)
    logger.info("[Auth] Login success: identity={}, tg_id={}, ip={}, method=telegram_widget", identity.id, body.id, _client_ip(request))
    set_auth_cookie(response, token, request)
    set_is_admin_cookie(response, identity, request)
    return LoginResponse(identity_id=identity.id)


@router.post("/login-telegram-webapp", response_model=LoginResponse)
async def login_telegram_webapp(
    body: LoginTelegramWebAppRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
):
    """Вход через Telegram WebApp initData. Валидирует HMAC, находит/создаёт Identity по tg_id."""
    from utils.telegram_login import verify_webapp_init_data
    result = verify_webapp_init_data(body.init_data, API_TOKEN)
    if not result:
        raise HTTPException(status_code=401, detail="Неверная подпись initData")
    tg_id = result.get("user_id")
    if not tg_id:
        raise HTTPException(status_code=401, detail="Не удалось определить пользователя из initData")
    identity = await idb.get_or_create_identity_for_tg(session, int(tg_id))
    await bind_identity_actor(request, session, identity)
    token = await idb.issue_token_for_identity(session, identity)
    logger.info("[Auth] Login success: identity={}, tg_id={}, ip={}, method=telegram_webapp", identity.id, tg_id, _client_ip(request))
    set_auth_cookie(response, token, request)
    set_is_admin_cookie(response, identity, request)
    return LoginResponse(identity_id=identity.id)


@router.post("/link-telegram", response_model=IdentityResponse)
async def link_telegram(
    body: LinkTelegramRequest,
    request: Request,
    response: Response,
    session: AsyncSession = Depends(get_session),
    identity=Depends(verify_identity_token),
):
    """Привязывает Telegram к текущей идентичности. Требуется подпись от Telegram Login Widget (доказательство владения аккаунтом)."""
    payload = body.model_dump(mode="json")
    if not verify_telegram_login(payload, API_TOKEN, max_age_seconds=TELEGRAM_LOGIN_MAX_AGE):
        raise HTTPException(status_code=401, detail="Неверная подпись или устаревшие данные от Telegram")
    result = await idb.attach_telegram(session, identity.id, body.id)
    if not result:
        raise HTTPException(
            status_code=409,
            detail="Этот Telegram уже привязан к другой идентичности",
        )
    await bind_identity_actor(request, session, result)
    set_is_admin_cookie(response, result, request)
    return IdentityResponse.model_validate(result)
