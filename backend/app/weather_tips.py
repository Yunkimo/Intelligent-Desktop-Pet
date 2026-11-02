"""次日降水提示：城市/日期唯一缓存，后台判断独立于桌宠在线状态。"""

import asyncio
import json
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config, db
from .web_query import WebQueryError


class WeatherTips:
    def __init__(self, client):
        self.client = client
        self.lock = asyncio.Lock()
        self.failures = {}

    async def tomorrow(self, city, now=None):
        now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        target = (now.astimezone(ZoneInfo("Asia/Shanghai")).date() + timedelta(days=1)).isoformat()
        key = (city.casefold(), target)
        async with self.lock:
            with db._conn() as conn:
                row = conn.execute(
                    "SELECT payload FROM weather_tip_cache WHERE city=? AND target_date=?", key
                ).fetchone()
            if row:
                return json.loads(row[0])
            failure = self.failures.get(key)
            if failure and now.timestamp() - failure < 60:
                return {
                    "status": "unknown",
                    "city": city,
                    "date": target,
                    "rain": None,
                    "desc": "天气服务暂不可用",
                    "tip": "",
                }
            try:
                result = await self.client.forecast(city, target)
            except WebQueryError:
                if len(self.failures) > 256:
                    self.failures.clear()
                self.failures[key] = now.timestamp()
                return {
                    "status": "unknown",
                    "city": city,
                    "date": target,
                    "rain": None,
                    "desc": "天气服务暂不可用",
                    "tip": "",
                }
            result = {
                **result,
                "city": city,
                "date": target,
                "status": "ok",
                "fetched_at": now.isoformat(),
            }
            with db._conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO weather_tip_cache VALUES (?,?,?)",
                    (*key, json.dumps(result, ensure_ascii=False)),
                )
                if result["rain"]:
                    conn.execute(
                        "INSERT OR IGNORE INTO weather_tips VALUES (?,?,?)", (*key, result["tip"])
                    )
                # 只保留近期天气，避免城市/日期缓存永久增长。
                conn.execute(
                    "DELETE FROM weather_tip_cache WHERE target_date<?",
                    ((now.date() - timedelta(days=7)).isoformat(),),
                )
                conn.execute(
                    "DELETE FROM weather_tips WHERE target_date<?",
                    ((now.date() - timedelta(days=7)).isoformat(),),
                )
            return result

    async def tick(self, now=None):
        now = now or datetime.now(ZoneInfo("Asia/Shanghai"))
        local = now.astimezone(ZoneInfo("Asia/Shanghai"))
        if local.hour >= 21:
            return await self.tomorrow(config.WEATHER_TIP_CITY, now)
        return None

    async def run(self):
        while True:
            try:
                await self.tick()
            except Exception:
                logging.getLogger(__name__).warning("Weather tip scan failed; retrying later")
            await asyncio.sleep(60)
