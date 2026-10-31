"""FastAPI 应用：组装路由，启动时初始化数据库。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import config, db
from .logging_config import install_log_filters
from .push_service import PushService
from .routers import course_import, courses, reminders, semester, tasks, web_query, wechat, ws
from .scheduler import Scheduler
from .web_query import WebQueryClient
from .wechat_client import WeChatClient
from .wechat_dispatcher import WeChatDispatcher

install_log_filters()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """初始化数据库与广播服务，退出时释放连接。"""
    db.init_db()
    _app.state.wechat_client = WeChatClient()
    _app.state.web_query_client = WebQueryClient()
    _app.state.push_service = PushService(
        config.WS_SEND_TIMEOUT_SECONDS, config.WS_CLOSE_TIMEOUT_SECONDS, _app.state.wechat_client
    )
    _app.state.wechat_dispatcher = WeChatDispatcher(_app.state.push_service.send_wechat_msg)
    _app.state.scheduler = Scheduler(
        _app.state.push_service.broadcast, phone_dispatch=_app.state.wechat_dispatcher.run_once
    )
    if config.SCHEDULER_ENABLED:
        _app.state.scheduler.start()
    try:
        yield
    finally:
        await _app.state.scheduler.stop()
        await _app.state.push_service.close_all()
        await _app.state.wechat_client.close()
        await _app.state.web_query_client.close()


app = FastAPI(title="智能桌宠后端", version="0.1.0", lifespan=lifespan)

app.include_router(tasks.router)
app.include_router(semester.router)
app.include_router(course_import.router)
app.include_router(courses.router)
app.include_router(reminders.router)
app.include_router(ws.router)
app.include_router(wechat.router)
app.include_router(web_query.router)


@app.get("/api/health")
def health():
    return {"status": "ok"}
