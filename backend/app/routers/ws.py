"""只接收服务器事件的 WebSocket 路由。"""

import asyncio
from hmac import compare_digest

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from .. import accounts, config
from ..push_service import PushService

router = APIRouter(tags=["events"])


@router.websocket("/ws")
async def websocket_events(websocket: WebSocket) -> None:
    """握手前校验唯一 query token；连接退出时始终清理注册。"""
    tokens = websocket.query_params.getlist("token")
    user_id = None
    session = None
    if len(tokens) == 1:
        user_id = await asyncio.to_thread(accounts.session_user, tokens[0])
        if user_id is not None:
            session = tokens[0]
        elif (
            config.ALLOW_LEGACY_API_KEY
            and config.API_TOKEN
            and compare_digest(tokens[0].encode(), config.API_TOKEN.encode())
        ):
            user_id = 1
    if user_id is None:
        await websocket.close(code=1008)
        return
    push_service: PushService = websocket.app.state.push_service
    if not await push_service.connect(websocket, user_id, session):
        return
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            # 本端点不接收客户端业务消息；协议层 ping/pong 由服务器处理。
            await websocket.close(code=1008)
            break
    except WebSocketDisconnect:
        pass
    finally:
        push_service.disconnect(websocket)
