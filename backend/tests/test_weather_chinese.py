"""上游中文字段实际为英文时，预报和旧缓存仍提供中文文案。"""

import asyncio
import json
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
import pytest
from app import db
from app.weather_tips import WeatherTips
from app.web_query import WebQueryClient, WebQueryError

NOW = datetime(2030, 1, 1, 21, tzinfo=ZoneInfo("Asia/Shanghai"))
TARGET = "2030-01-02"


def streamed_response(status, *, json):
    import json as encoder

    return httpx.Response(status, stream=httpx.ByteStream(encoder.dumps(json).encode()))


@pytest.mark.parametrize(
    "codes,expected,rain",
    [
        ([176], "局部小雨", True),
        ([113, 149], "晴、烟霾", False),
        ([296, 296, 389], "小雨、雷阵雨", True),
        ([338], "大雪", True),
    ],
)
def test_forecast_ignores_upstream_language(client, codes, expected, rain):
    def upstream(request):
        return streamed_response(
            200,
            json={
                "weather": [
                    {
                        "date": TARGET,
                        "hourly": [
                            {
                                "weatherCode": str(code),
                                "lang_zh": [{"value": "Patchy rain nearby"}],
                                "weatherDesc": [{"value": "English text"}],
                            }
                            for code in codes
                        ],
                    }
                ]
            },
        )

    async def run():
        api = WebQueryClient(httpx.MockTransport(upstream))
        try:
            result = await api.forecast("长沙", TARGET)
            assert result["desc"] == expected
            assert result["rain"] is rain
            assert result["tip"] == (f"明天有{expected}，记得带伞" if rain else "")
        finally:
            await api.close()

    asyncio.run(run())


@pytest.mark.parametrize("rain", [True, False])
def test_old_english_cache_is_replaced_and_reused(client, rain):
    old = {
        "status": "ok",
        "date": TARGET,
        "rain": True,
        "desc": "Patchy rain nearby",
        "tip": "明天有Patchy rain nearby，记得带伞",
    }
    with db._conn() as conn:
        conn.execute(
            "INSERT INTO weather_tip_cache VALUES (?,?,?)", ("长沙", TARGET, json.dumps(old))
        )
        conn.execute("INSERT INTO weather_tips VALUES (?,?,?)", ("长沙", TARGET, old["tip"]))
    api = AsyncMock()
    api.forecast.return_value = {
        "rain": rain,
        "desc": "小雨" if rain else "晴",
        "tip": "明天有小雨，记得带伞" if rain else "",
    }

    async def run():
        service = WeatherTips(api)
        first = await service.tomorrow("长沙", NOW)
        assert first["tip"] == api.forecast.return_value["tip"]
        assert await service.tomorrow("长沙", NOW) == first
        api.forecast.assert_awaited_once()

    asyncio.run(run())
    with db._conn() as conn:
        payload = json.loads(conn.execute("SELECT payload FROM weather_tip_cache").fetchone()[0])
        assert payload["desc"] == ("小雨" if rain else "晴")
        rows = conn.execute("SELECT tip FROM weather_tips").fetchall()
        assert [r[0] for r in rows] == (["明天有小雨，记得带伞"] if rain else [])


def test_unknown_weather_code_not_translated_as_rain(client):
    async def run():
        api = WebQueryClient(
            httpx.MockTransport(
                lambda request: streamed_response(
                    200,
                    json={
                        "weather": [
                            {
                                "date": TARGET,
                                "hourly": [{"weatherCode": "9999", "lang_zh": [{"value": "晴"}]}],
                            }
                        ]
                    },
                )
            )
        )
        try:
            with pytest.raises(WebQueryError, match="weather_forecast_invalid"):
                await api.forecast("长沙", TARGET)
        finally:
            await api.close()

    asyncio.run(run())
