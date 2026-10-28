"""API Key 鉴权依赖。"""

from fastapi import Header, HTTPException

from . import config


def require_token(x_api_key: str = Header(default="")) -> None:
    """校验 X-API-Key 请求头；未配置 token 或 token 不符则拒绝。"""
    if not config.API_TOKEN:
        raise HTTPException(status_code=503, detail="后端未配置 API_TOKEN，请在 backend/.env 设置")
    if x_api_key != config.API_TOKEN:
        raise HTTPException(status_code=401, detail="API Key 无效")
