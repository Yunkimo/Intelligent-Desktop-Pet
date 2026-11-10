"""仅用于 C8 自动化的回环测试服务；业务接口不替换，外部服务未启用。

默认只监听本机回环；真机预览联调时用 C8_TEST_HOST=0.0.0.0 监听局域网。
"""

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

if __name__ == "__main__":
    host = os.environ.get("C8_TEST_HOST", "127.0.0.1")
    uvicorn.run(main.app, host=host, port=int(os.environ["C8_TEST_PORT"]), access_log=False)
