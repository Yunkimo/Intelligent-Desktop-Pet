"""单进程 WebSocket 广播：隔离慢连接，不持久化或补发事件。"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from pydantic import AwareDatetime, BaseModel, Field

from .wechat_client import WeChatClient, WeChatError

logger = logging.getLogger(__name__)
EventType = Literal["task.created", "course.created", "reminder.due"]


class ResourceData(BaseModel):
    """通知仅包含资源 ID，业务状态由 REST 校正。"""

    id: int = Field(gt=0)


class Event(BaseModel):
    """版本一事件信封；提醒事件由后续调度器产生。"""

    version: Literal[1] = 1
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    type: EventType
    occurred_at: AwareDatetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: ResourceData


class PushService:
    """每个应用生命周期拥有一个实例，仅在同一事件循环内调用。"""

    def __init__(
        self, send_timeout: float, close_timeout: float, wechat: WeChatClient | None = None
    ) -> None:
        self.send_timeout = send_timeout
        self.close_timeout = close_timeout
        self._connections: dict[WebSocket, asyncio.Lock] = {}
        self._closing = False
        self._wechat = wechat

    async def send_wechat_msg(self, openid: str, reminder: dict) -> None:
        """向已由服务端验证的收件人发送；授权和幂等性由调度层控制。"""
        if self._wechat is None:
            raise WeChatError("wechat_not_configured")
        await self._wechat.send(openid, reminder)

    @property
    def connection_count(self) -> int:
        """返回当前注册连接数，供测试与运维观察。"""
        return len(self._connections)

    async def connect(self, websocket: WebSocket) -> bool:
        """接受连接；重复注册幂等，关闭期间拒绝新连接。"""
        if websocket in self._connections:
            return True
        if self._closing:
            await self._close(websocket, 1001)
            return False
        await websocket.accept()
        if self._closing:
            await self._close(websocket, 1001)
            return False
        self._connections[websocket] = asyncio.Lock()
        return True

    def disconnect(self, websocket: WebSocket) -> None:
        """移除连接，允许接收端与发送端重复清理。"""
        self._connections.pop(websocket, None)

    async def _close(self, websocket: WebSocket, code: int) -> None:
        try:
            await asyncio.wait_for(websocket.close(code=code), self.close_timeout)
        except (asyncio.TimeoutError, OSError, RuntimeError, WebSocketDisconnect):
            # 不记录异常正文，避免第三方异常包含 URL 或 token。
            logger.warning("WebSocket close failed or timed out")

    async def _send(self, websocket: WebSocket, lock: asyncio.Lock, message: str) -> bool:
        async def send_locked() -> None:
            async with lock:
                if websocket not in self._connections:
                    raise RuntimeError("connection removed")
                await websocket.send_text(message)

        try:
            await asyncio.wait_for(send_locked(), self.send_timeout)
            return True
        except (asyncio.TimeoutError, OSError, RuntimeError, WebSocketDisconnect):
            self.disconnect(websocket)
            logger.warning("WebSocket send failed or timed out; connection removed")
            await self._close(websocket, 1013)
            return False
        except asyncio.CancelledError:
            self.disconnect(websocket)
            await self._close(websocket, 1001)
            raise

    async def broadcast(self, event: dict) -> int:
        """验证并广播同一 JSON 事件，返回成功发送数；不代表客户端已展示。"""
        message = Event.model_validate(event).model_dump_json()
        connections = tuple(self._connections.items())
        results = await asyncio.gather(
            *(self._send(websocket, lock, message) for websocket, lock in connections)
        )
        return sum(results)

    async def notify(self, event_type: EventType, resource_id: int) -> None:
        """在数据库提交后尽力通知，推送异常不得改变已成功的 REST 写入。"""
        try:
            event = Event(type=event_type, data=ResourceData(id=resource_id))
            await self.broadcast(event.model_dump())
        except Exception:
            logger.error("Committed resource notification failed; refresh through REST")

    async def close_all(self) -> None:
        """停止注册，清空集合，并在有限时间内释放所有连接。"""
        self._closing = True
        connections = tuple(self._connections)
        self._connections.clear()
        await asyncio.gather(*(self._close(websocket, 1001) for websocket in connections))
