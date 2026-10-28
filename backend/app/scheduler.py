"""单实例提醒调度：持久领取、有限重试、可取消生命周期。"""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from contextlib import suppress

from . import config, reminder_store

logger = logging.getLogger(__name__)


class Scheduler:
    """注入发送渠道与时钟，测试不依赖真实时间或外部网络。"""

    def __init__(
        self,
        broadcast: Callable[[dict], Awaitable[int]],
        clock: Callable[[], float] = time.time,
        phone_dispatch: Callable[[], Awaitable[int]] | None = None,
    ) -> None:
        self.broadcast = broadcast
        self.clock = clock
        self._task: asyncio.Task | None = None
        self._phone_task: asyncio.Task | None = None
        self._scan_lock = asyncio.Lock()
        self.phone_dispatch = phone_dispatch

    def start(self) -> None:
        """幂等启动独立渠道循环，微信网络等待不阻塞桌面下一轮扫描。"""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="reminder-scheduler")
        if self.phone_dispatch is not None and (
            self._phone_task is None or self._phone_task.done()
        ):
            self._phone_task = asyncio.create_task(self._run_phone(), name="wechat-scheduler")

    async def stop(self) -> None:
        """取消后台循环；中断的领取由持久租约到期后恢复。"""
        tasks = [task for task in (self._task, self._phone_task) if task is not None]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self._task = self._phone_task = None

    async def _run(self) -> None:
        while True:
            try:
                await self.run_once(include_phone=False)
            except Exception:
                # 不打印异常正文，避免发送渠道异常包含凭证或个人数据。
                logger.error("Reminder scan failed; retrying on next interval")
            await asyncio.sleep(config.SCHEDULER_INTERVAL_SECONDS)

    async def _run_phone(self) -> None:
        while True:
            try:
                await self.phone_dispatch()
            except Exception:
                logger.error("WeChat scan failed; retrying on next interval")
            await asyncio.sleep(config.SCHEDULER_INTERVAL_SECONDS)

    async def run_once(self, *, include_phone: bool = True) -> int:
        """手动调用可验证两个渠道；后台运行时各自扫描，DB 工作放到线程。"""
        processed = 0
        async with self._scan_lock:
            for _ in range(config.SCHEDULER_BATCH_SIZE):
                claim = await asyncio.to_thread(reminder_store.claim_due, self.clock())
                if claim is None:
                    break
                if not await asyncio.to_thread(reminder_store.is_current, claim):
                    continue
                event = {
                    "version": 1,
                    "event_id": claim["event_id"],
                    "type": "reminder.due",
                    "occurred_at": claim["occurred_at"],
                    "data": {"id": claim["reminder_id"]},
                }
                error = None
                try:
                    sent = await asyncio.wait_for(
                        self.broadcast(event), config.SCHEDULER_SEND_TIMEOUT_SECONDS
                    )
                    if sent <= 0:
                        error = "no_clients"
                except asyncio.TimeoutError:
                    error = "send_timeout"
                except Exception:
                    error = "send_failed"
                if error:
                    logger.warning(
                        "Reminder delivery failed id=%s event_id=%s attempt=%s reason=%s",
                        claim["reminder_id"],
                        claim["event_id"],
                        claim["attempts"],
                        error,
                    )
                await asyncio.to_thread(reminder_store.finish, claim, self.clock(), error)
                processed += 1
        if include_phone and self.phone_dispatch is not None:
            processed += await self.phone_dispatch()
        return processed
