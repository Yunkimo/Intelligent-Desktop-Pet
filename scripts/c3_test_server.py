"""仅用于 C3 自动化的回环测试服务；业务接口不替换，外部微信由 MockTransport 隔离。"""

import json
import os

import httpx
import uvicorn
from app import main
from app.auth import require_token
from app.wechat_client import WeChatClient
from fastapi import Depends

sent = []


def upstream(request: httpx.Request) -> httpx.Response:
    """模拟平台身份和接收结果，不联系真实微信。"""
    if request.url.path == "/sns/jscode2session":
        return httpx.Response(200, json={"openid": "test-" + request.url.params["js_code"]})
    if request.url.path == "/cgi-bin/token":
        return httpx.Response(200, json={"access_token": "mock-upstream", "expires_in": 7200})
    if request.url.path == "/cgi-bin/message/subscribe/send":
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"errcode": 0})
    raise AssertionError("Unexpected upstream URL")


main.WeChatClient = lambda: WeChatClient(transport=httpx.MockTransport(upstream))


@main.app.post("/__test__/tick", dependencies=[Depends(require_token)])
async def tick() -> dict:
    """执行真实调度器并返回模拟平台调用数。"""
    await main.app.state.scheduler.run_once()
    return {"sent": sent}


if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ["C3_TEST_PORT"]), access_log=False)
