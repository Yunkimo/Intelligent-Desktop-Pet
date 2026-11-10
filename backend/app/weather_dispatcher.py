"""只处理用户显式登记的本次天气订阅，和普通提醒共用调度生命周期。"""

import asyncio
import time
from datetime import datetime

from . import config
from . import weather_subscriptions as store
from .wechat_client import WeChatError


class WeatherDispatcher:
    def __init__(self, weather, send, clock=time.time):
        self.weather, self.send, self.clock = weather, send, clock

    async def run_once(self) -> int:
        if not config.WX_ENABLED or not config.WEATHER_WX_TEMPLATE_ID:
            return 0
        processed = 0
        # 限制每轮天气网络操作，普通日程微信发送不被大量城市查询长时间占用。
        for _ in range(min(config.SCHEDULER_BATCH_SIZE, 4)):
            claim = await asyncio.to_thread(store.claim_due, self.clock())
            if claim is None:
                break
            try:
                forecast = await self.weather.tomorrow(
                    claim["city"], datetime.fromtimestamp(self.clock(), store.ZONE)
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                forecast = {"status": "unknown"}
            sending = await asyncio.to_thread(store.weather_result, claim, forecast, self.clock())
            processed += 1
            if sending is None:
                continue
            outcome, error = "sent", None
            try:
                await asyncio.wait_for(
                    self.send(sending["openid"], sending), config.WX_DELIVERY_TIMEOUT_SECONDS
                )
            except WeChatError as exc:
                error = exc.reason
                outcome = "uncertain" if exc.uncertain else "failed"
                if (
                    not exc.uncertain
                    and exc.retryable
                    and sending["attempts"] < config.SCHEDULER_MAX_ATTEMPTS
                ):
                    outcome = "retry"
            except asyncio.CancelledError:
                await asyncio.shield(
                    asyncio.to_thread(
                        store.finish, sending, "uncertain", "interrupted_send", self.clock()
                    )
                )
                raise
            except Exception:
                outcome, error = "uncertain", "weather_send_outcome_unknown"
            await asyncio.to_thread(store.finish, sending, outcome, error, self.clock())
        return processed
