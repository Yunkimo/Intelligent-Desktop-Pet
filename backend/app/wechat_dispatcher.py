"""微信一次性订阅发送调度，独立于 WebSocket 的成功/失败结果。"""

import asyncio
import time
from collections.abc import Awaitable, Callable

from . import config, wechat_store
from .wechat_client import WeChatError


class WeChatDispatcher:
    """注入渠道函数；只对尚未发送时的可恢复错误进行有限重试。"""

    def __init__(
        self, send: Callable[[str, dict], Awaitable[None]], clock: Callable = time.time
    ) -> None:
        self.send = send
        self.clock = clock

    async def run_once(self) -> int:
        """处理有限条微信发送，不依赖桌面是否在线。"""
        if not config.WX_ENABLED:
            return 0
        processed = 0
        for _ in range(config.SCHEDULER_BATCH_SIZE):
            claim = await asyncio.to_thread(wechat_store.claim_due, self.clock())
            if claim is None:
                break
            if not await asyncio.to_thread(wechat_store.is_current, claim):
                await asyncio.to_thread(
                    wechat_store.finish, claim, self.clock(), "cancelled", "reminder_changed"
                )
                continue
            outcome, error = "sent", None
            try:
                if claim["template_id"] != config.WX_TEMPLATE_ID:
                    raise WeChatError("wechat_template_changed")
                await asyncio.wait_for(
                    self.send(claim["openid"], claim), config.WX_DELIVERY_TIMEOUT_SECONDS
                )
            except WeChatError as exc:
                error = exc.reason
                outcome = "uncertain" if exc.uncertain else "failed"
                if exc.retryable and claim["attempts"] < config.SCHEDULER_MAX_ATTEMPTS:
                    outcome = "retry"
            except asyncio.CancelledError:
                await asyncio.shield(
                    asyncio.to_thread(
                        wechat_store.finish, claim, self.clock(), "uncertain", "interrupted_send"
                    )
                )
                raise
            except Exception:
                outcome, error = "uncertain", "wechat_send_outcome_unknown"
            await asyncio.to_thread(wechat_store.finish, claim, self.clock(), outcome, error)
            processed += 1
        return processed
