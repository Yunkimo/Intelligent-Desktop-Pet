"""服务凭据和用户会话分层；Bearer 错误不能降级为共享凭据。"""

from hmac import compare_digest

from fastapi import Header, HTTPException

from . import accounts, config, wechat_store


def require_token(x_api_key: str = Header(default="")) -> None:
    if not config.API_TOKEN:
        raise HTTPException(503, "后端未配置 API_TOKEN，请在 backend/.env 设置")
    if not compare_digest(x_api_key.encode(), config.API_TOKEN.encode()):
        raise HTTPException(401, "API Key 无效")


def current_user(
    authorization: str = Header(default=""), x_api_key: str = Header(default="")
) -> int:
    if authorization:
        scheme, _, token = authorization.partition(" ")
        uid = accounts.session_user(token) if scheme.lower() == "bearer" else None
        if uid is None:
            raise HTTPException(401, "session_invalid")
        return uid
    if config.ALLOW_LEGACY_API_KEY:
        require_token(x_api_key)
        return accounts.DEFAULT_USER
    raise HTTPException(401, "session_required")


def current_wechat_user(authorization: str = Header(default="")) -> int:
    scheme, _, token = authorization.partition(" ")
    uid = wechat_store.session_user(token) if scheme.lower() == "bearer" else None
    if uid is None:
        raise HTTPException(401, "wechat_session_invalid")
    return uid
