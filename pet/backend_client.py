"""后端客户端：REST（httpx）与 WebSocket（websocket-client）的统一入口。

REST 部分封装课表/日程/提醒 CRUD，自动携带 X-API-Key 鉴权头；
WebSocket 部分用后台线程接收后端事件广播，解析后经 Qt 信号上抛。
"""

import json
import threading
from urllib.parse import urlencode

import httpx
import websocket
from PyQt6.QtCore import QThread, pyqtSignal


class BackendError(Exception):
    """后端调用失败（网络异常或非 2xx 响应）。"""


class SessionExpired(BackendError):
    """会话失效，禁止自动退回共享身份。"""


class BackendClient:
    """访问后端 REST 的客户端，封装课表 / 日程 / 提醒的 CRUD。

    base_url 与 api_token 来自配置（见 Settings.backend_url / Settings.api_token）。
    """

    def __init__(self, base_url: str, api_token: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._token = api_token
        self._timeout = timeout
        self.session_token = ""
        self.on_auth_error = None
        self.session_required = False

    # ---------- 底层 ----------
    def _headers(self) -> dict[str, str]:
        if self.session_token:
            return {"Authorization": "Bearer " + self.session_token}
        if self.session_required:
            raise SessionExpired("账号未绑定，请打开「后端账号」重新绑定")
        return {"X-API-Key": self._token}

    def _request(self, method: str, path: str, json: dict | None = None, headers=None):
        url = f"{self.base_url}{path}"
        try:
            resp = httpx.request(
                method,
                url,
                headers=self._headers() if headers is None else headers,
                json=json,
                timeout=self._timeout,
                trust_env=False,  # 本地后端不走系统代理，否则会被 Clash 拦成 502
            )
        except httpx.HTTPError:
            raise BackendError("后端不可达，请检查网络和后端地址") from None
        if resp.status_code == 401:
            if self.on_auth_error is not None:
                self.on_auth_error()
            raise SessionExpired("后端返回 401：账号已失效，请打开「后端账号」重新绑定")
        if resp.status_code >= 400:
            raise BackendError(f"后端返回 {resp.status_code}，请检查请求或服务状态")
        if resp.status_code == 204:
            return None
        try:
            return resp.json()
        except ValueError as exc:  # 非 JSON 的 2xx 响应，避免向上抛裸异常
            raise BackendError("后端响应不是合法 JSON") from exc

    def device_login(self, pairing_code=""):
        """登录不沿用旧 Bearer；配对失败不降级为演示账号。"""
        payload = {"pairing_code": pairing_code} if pairing_code else {}
        result = self._request(
            "POST",
            "/api/auth/device",
            payload,
            headers={} if pairing_code else {"X-API-Key": self._token},
        )
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("device_token"), str)
            or not result["device_token"]
            or type(result.get("user_id")) is not int
        ):
            raise BackendError("登录响应无效")
        return result

    def logout(self):
        return self._request("POST", "/api/auth/logout")

    def get_tomorrow_weather(self, city: str) -> dict:
        """查次日天气提示（带伞判断）。后端按城市/日期缓存，独立于桌宠在线状态。"""
        from urllib.parse import quote

        return self._request("GET", f"/api/weather/tomorrow?city={quote(city)}")

    # ---------- 健康检查（无鉴权） ----------
    def health(self) -> dict:
        """GET /api/health，返回后端健康状态。"""
        return self._request("GET", "/api/health")

    # ---------- 课表 ----------
    def list_courses(self) -> list[dict]:
        return self._request("GET", "/api/courses")

    def create_course(
        self,
        name: str,
        day_of_week: int,
        start_time: str,
        end_time: str,
        location: str = "",
        weeks: list[int] | None = None,
    ) -> dict:
        return self._request(
            "POST",
            "/api/courses",
            json={
                "name": name,
                "day_of_week": day_of_week,
                "start_time": start_time,
                "end_time": end_time,
                "location": location,
                "weeks": weeks,
            },
        )

    def update_course(self, course_id: int, **fields) -> dict:
        return self._request("PUT", f"/api/courses/{course_id}", json=fields)

    def delete_course(self, course_id: int) -> None:
        self._request("DELETE", f"/api/courses/{course_id}")

    # ---------- 日程 / 待办 ----------
    def list_tasks(self) -> list[dict]:
        return self._request("GET", "/api/tasks")

    def create_task(
        self, title: str, note: str = "", due_at: str | None = None, remind_at: str | None = None
    ) -> dict:
        return self._request(
            "POST",
            "/api/tasks",
            json={"title": title, "note": note, "due_at": due_at, "remind_at": remind_at},
        )

    def update_task(self, task_id: int, **fields) -> dict:
        return self._request("PUT", f"/api/tasks/{task_id}", json=fields)

    def delete_task(self, task_id: int) -> None:
        self._request("DELETE", f"/api/tasks/{task_id}")

    # ---------- 提醒 ----------
    def list_reminders(self) -> list[dict]:
        return self._request("GET", "/api/reminders")

    def create_reminder(
        self,
        title: str,
        remind_at: str,
        body: str = "",
        channel: str = "both",
        task_id: int | None = None,
        repeat_rule: str | None = None,
    ) -> dict:
        payload = {
            "title": title,
            "body": body,
            "remind_at": remind_at,
            "channel": channel,
            "task_id": task_id,
        }
        # 重复提醒按 B5 契约必须独立于日程，不能带 task_id
        if repeat_rule is not None:
            payload["repeat_rule"] = repeat_rule
        return self._request("POST", "/api/reminders", json=payload)

    def update_reminder(self, reminder_id: int, **fields) -> dict:
        return self._request("PUT", f"/api/reminders/{reminder_id}", json=fields)

    def delete_reminder(self, reminder_id: int) -> None:
        self._request("DELETE", f"/api/reminders/{reminder_id}")


# ---------- WebSocket 实时监听 ----------


def build_ws_url(backend_url: str, api_token: str) -> str:
    """由后端 REST 地址推导 WebSocket 地址：http→ws、https→wss，token 走 query。"""
    base = backend_url.rstrip("/")
    if base.startswith("https://"):
        ws_base = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        ws_base = "ws://" + base[len("http://") :]
    else:
        ws_base = "ws://" + base
    return f"{ws_base}/ws?{urlencode({'token': api_token})}"


def parse_event(raw: str) -> dict | None:
    """解析一条事件帧；非 JSON 或非对象返回 None（客户端按契约忽略）。"""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class WsListener(QThread):
    """后台线程接收后端 WebSocket 事件广播，解析为 dict 经 event 信号发出。

    断线自动重连（退避 3s）；连接建立失败经 error 信号上报，中途断开静默重连。
    """

    event = pyqtSignal(dict)
    error = pyqtSignal(str)
    auth_error = pyqtSignal()

    _RECONNECT_SECS = 3.0
    _RECV_TIMEOUT_SECS = 1.0

    def __init__(self, url: str, parent=None) -> None:
        super().__init__(parent)
        self.url = url
        self._stop = threading.Event()

    def request_stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                ws = websocket.create_connection(self.url, timeout=5)
            except Exception as exc:  # noqa: BLE001 - 后端未起/鉴权失败，上报并退避重试
                if not self._stop.is_set():
                    if getattr(exc, "status_code", None) in (401, 403):
                        self.auth_error.emit()
                        return
                    self.error.emit("后端实时连接失败，请检查网络")
                if self._stop.wait(self._RECONNECT_SECS):
                    break
                continue
            try:
                ws.settimeout(self._RECV_TIMEOUT_SECS)
                while not self._stop.is_set():
                    try:
                        opcode, raw = ws.recv_data(control_frame=True)
                        if opcode == websocket.ABNF.OPCODE_CLOSE:
                            if len(raw) >= 2 and int.from_bytes(raw[:2], "big") == 1008:
                                self.auth_error.emit()
                                return
                            break
                        if opcode not in (websocket.ABNF.OPCODE_TEXT, websocket.ABNF.OPCODE_BINARY):
                            continue
                        if isinstance(raw, bytes):
                            raw = raw.decode("utf-8")
                    except websocket.WebSocketTimeoutException:
                        continue  # 接收超时仅用于周期性检查停止标记
                    if not raw:
                        break  # 对端关闭
                    event = parse_event(raw)
                    if event is not None:
                        self.event.emit(event)
            except Exception:  # noqa: BLE001 - 连接中途断开，静默重连
                pass
            finally:
                try:
                    ws.close()
                except Exception:  # noqa: BLE001
                    pass
            if self._stop.wait(self._RECONNECT_SECS):
                break
