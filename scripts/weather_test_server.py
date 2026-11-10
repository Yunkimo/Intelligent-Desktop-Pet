"""仅用于带伞提醒自动化的回环测试服务：微信上游与天气上游均用本地模拟，
业务接口不替换；不联系真实微信或 wttr.in。"""

import os

import httpx
import uvicorn
from app import main
from app.wechat_client import WeChatClient


def upstream(request: httpx.Request) -> httpx.Response:
    """模拟平台身份和接收结果，不联系真实微信。"""
    if request.url.path == "/sns/jscode2session":
        return httpx.Response(200, json={"openid": "test-" + request.url.params["js_code"]})
    if request.url.path == "/cgi-bin/token":
        return httpx.Response(200, json={"access_token": "mock-upstream", "expires_in": 7200})
    if request.url.path == "/cgi-bin/message/subscribe/send":
        return httpx.Response(200, json={"errcode": 0})
    raise AssertionError("Unexpected upstream URL")


main.WeChatClient = lambda: WeChatClient(transport=httpx.MockTransport(upstream))


class MockWeather:
    """确定性天气上游：rain 固定为 False（无降水），便于联调断言。"""

    async def forecast(self, city, target_date):
        return {
            "rain": False,
            "desc": "多云",
            "tip": "",
            "observed_at": "mock",
        }

    async def close(self):
        return None


main.WebQueryClient = lambda: MockWeather()

if __name__ == "__main__":
    host = os.environ.get("WEATHER_TEST_HOST", "127.0.0.1")
    uvicorn.run(main.app, host=host, port=int(os.environ["WEATHER_TEST_PORT"]), access_log=False)
