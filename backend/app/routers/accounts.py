"""设备登录与会话管理；响应禁止缓存。"""

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from .. import accounts
from ..auth import current_user, require_token

router = APIRouter(prefix="/api/auth", tags=["accounts"])


class DeviceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pairing_code: str | None = Field(default=None, min_length=1, max_length=128)


@router.post("/device")
def login(payload: DeviceIn, response: Response, x_api_key: str = Header(default="")):
    if payload.pairing_code is None:
        require_token(x_api_key)
    try:
        result = accounts.device_session(payload.pairing_code)
    except ValueError:
        raise HTTPException(401, "pairing_invalid") from None
    response.headers["Cache-Control"] = "no-store"
    return result


@router.post("/pairing")
def pairing(response: Response, user_id: int = Depends(current_user)):
    response.headers["Cache-Control"] = "no-store"
    return accounts.pair(user_id)


@router.get("/me")
def me(user_id: int = Depends(current_user)):
    return {"user_id": user_id}


@router.post("/logout", status_code=204)
def logout(authorization: str = Header(default=""), user_id: int = Depends(current_user)):
    accounts.revoke(authorization.partition(" ")[2])
