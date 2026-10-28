"""本地启动入口：python run.py（开发热重载，监听 0.0.0.0:8001）。"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8001,
        reload=True,
        ws="websockets-sansio",
        ws_max_size=4096,
    )
