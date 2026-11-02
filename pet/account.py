"""设备凭据仅保存在忽略目录，原子写入并按后端地址隔离。"""

import json
import os
import tempfile
from pathlib import Path


class AccountStore:
    def __init__(self, path: Path, base_url: str):
        self.path = path
        self.base_url = base_url.rstrip("/")

    def load(self):
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("base_url") != self.base_url:
                return None
            if value.get("signed_out") is True:
                return value
            if not isinstance(value.get("device_token"), str) or not value["device_token"]:
                raise ValueError()
            return value
        except (ValueError, TypeError, AttributeError):
            raise ValueError("账号文件损坏，请在后端账号窗口重新绑定") from None

    def save(self, value):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".account-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({**value, "base_url": self.base_url}, stream, ensure_ascii=False)
            os.chmod(name, 0o600)
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def clear(self):
        self.save({"signed_out": True, "device_token": ""})
