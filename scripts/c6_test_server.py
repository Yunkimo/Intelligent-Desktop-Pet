"""仅用于 C6 自动化的回环测试服务；业务接口不替换，外部服务未启用。

默认只监听本机回环；真机预览联调时用 C6_TEST_HOST=0.0.0.0 监听局域网。
"""

import os

import uvicorn
from app import main

if __name__ == "__main__":
    host = os.environ.get("C6_TEST_HOST", "127.0.0.1")
    uvicorn.run(main.app, host=host, port=int(os.environ["C6_TEST_PORT"]), access_log=False)
