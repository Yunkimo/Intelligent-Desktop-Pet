"""仅用于 C6 自动化的回环测试服务；业务接口不替换，外部服务未启用。"""

import os

import uvicorn
from app import main

if __name__ == "__main__":
    uvicorn.run(main.app, host="127.0.0.1", port=int(os.environ["C6_TEST_PORT"]), access_log=False)
