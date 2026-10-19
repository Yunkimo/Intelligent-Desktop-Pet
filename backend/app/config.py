"""后端配置：从 backend/.env 读取密钥与数据库路径。"""

import json
import math
import os
import re
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# 简单 API Key：桌宠与手机 PWA 通过 X-API-Key 请求头携带，服务端比对
API_TOKEN = os.getenv("API_TOKEN", "").strip()

# 视觉模型（课表图片识别导入）：OpenAI 兼容 vision API（如硅基流动 Qwen2.5-VL）
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "").strip()
LLM_VISION_MODEL = os.getenv("LLM_VISION_MODEL", "").strip()

# SQLite 数据库路径（默认 backend/data/pet.db，已被 git 忽略）
DB_PATH = Path(os.getenv("DB_PATH", str(BACKEND_DIR / "data" / "pet.db")))


def positive_seconds(name: str, default: str) -> float:
    """读取正有限秒数，配置错误时明确拒绝启动。"""
    try:
        value = float(os.getenv(name, default))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正有限秒数") from exc
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} 必须是正有限秒数")
    return value


WS_SEND_TIMEOUT_SECONDS = positive_seconds("WS_SEND_TIMEOUT_SECONDS", "2")
WS_CLOSE_TIMEOUT_SECONDS = positive_seconds("WS_CLOSE_TIMEOUT_SECONDS", "1")


def integer_setting(name: str, default: str, minimum: int, maximum: int) -> int:
    """读取有明确上下界的整数配置。"""
    value = int(os.getenv(name, default))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须介于 {minimum} 与 {maximum}")
    return value


SCHEDULER_ENABLED = os.getenv("SCHEDULER_ENABLED", "true").lower()
if SCHEDULER_ENABLED not in {"true", "false"}:
    raise ValueError("SCHEDULER_ENABLED 必须为 true 或 false")
SCHEDULER_ENABLED = SCHEDULER_ENABLED == "true"
SCHEDULER_INTERVAL_SECONDS = positive_seconds("SCHEDULER_INTERVAL_SECONDS", "30")
SCHEDULER_SEND_TIMEOUT_SECONDS = positive_seconds("SCHEDULER_SEND_TIMEOUT_SECONDS", "5")
SCHEDULER_LEASE_SECONDS = positive_seconds("SCHEDULER_LEASE_SECONDS", "30")
SCHEDULER_RETRY_SECONDS = positive_seconds("SCHEDULER_RETRY_SECONDS", "30")
SCHEDULER_MAX_RETRY_SECONDS = positive_seconds("SCHEDULER_MAX_RETRY_SECONDS", "300")
SCHEDULER_MAX_ATTEMPTS = integer_setting("SCHEDULER_MAX_ATTEMPTS", "3", 1, 10)
SCHEDULER_BATCH_SIZE = integer_setting("SCHEDULER_BATCH_SIZE", "100", 1, 1000)
DB_TIMEOUT_SECONDS = positive_seconds("DB_TIMEOUT_SECONDS", "2")
DB_BACKUP_TIMEOUT_SECONDS = positive_seconds("DB_BACKUP_TIMEOUT_SECONDS", "30")
REMINDER_NAIVE_OFFSET_MINUTES = integer_setting("REMINDER_NAIVE_OFFSET_MINUTES", "480", -1439, 1439)
if SCHEDULER_LEASE_SECONDS <= SCHEDULER_SEND_TIMEOUT_SECONDS + 2 * DB_TIMEOUT_SECONDS:
    raise ValueError("SCHEDULER_LEASE_SECONDS 必须大于发送超时加两倍数据库锁等待上限")

# 微信渠道默认关闭；真实联调显式启用，不影响现有桌宠/REST。
WX_ENABLED = os.getenv("WX_ENABLED", "false").lower()
if WX_ENABLED not in {"true", "false"}:
    raise ValueError("WX_ENABLED 必须为 true 或 false")
WX_ENABLED = WX_ENABLED == "true"
WX_APPID = os.getenv("WX_APPID", "").strip()
WX_SECRET = os.getenv("WX_SECRET", "").strip()
WX_TEMPLATE_ID = os.getenv("WX_TEMPLATE_ID", "").strip()
WX_TIMEOUT_SECONDS = positive_seconds("WX_TIMEOUT_SECONDS", "10")
WX_SESSION_TTL_SECONDS = integer_setting("WX_SESSION_TTL_SECONDS", "7200", 60, 86400)
WX_MINIPROGRAM_STATE = os.getenv("WX_MINIPROGRAM_STATE", "developer")
if WX_MINIPROGRAM_STATE not in {"developer", "trial", "formal"}:
    raise ValueError("WX_MINIPROGRAM_STATE 必须为 developer、trial 或 formal")
WX_TEMPLATE_FIELDS = json.loads(os.getenv("WX_TEMPLATE_FIELDS", "{}"))
if not isinstance(WX_TEMPLATE_FIELDS, dict) or not all(
    isinstance(key, str)
    and isinstance(value, str)
    and (
        (re.fullmatch(r"thing[0-9]+", key) and value in {"title", "body"})
        or (re.fullmatch(r"(?:time|date)[0-9]+", key) and value == "remind_at")
    )
    for key, value in WX_TEMPLATE_FIELDS.items()
):
    raise ValueError("WX_TEMPLATE_FIELDS 仅支持 thingN 对应 title/body、timeN/dateN 对应 remind_at")
WX_DELIVERY_TIMEOUT_SECONDS = WX_TIMEOUT_SECONDS * 4
WX_DELIVERY_LEASE_SECONDS = WX_DELIVERY_TIMEOUT_SECONDS + 2 * DB_TIMEOUT_SECONDS + 5
# B4：固定上游主机，调用者只能提供城市或关键词，不能传入目标 URL。
WEB_WEATHER_URL = "https://wttr.in"
WEB_SEARCH_URL = "https://html.duckduckgo.com/html/"
WEB_QUERY_TIMEOUT_SECONDS = positive_seconds("WEB_QUERY_TIMEOUT_SECONDS", "8")
WEB_QUERY_MAX_BYTES = integer_setting("WEB_QUERY_MAX_BYTES", "262144", 1024, 1048576)
WEB_QUERY_MAX_CONCURRENT = integer_setting("WEB_QUERY_MAX_CONCURRENT", "4", 1, 16)
