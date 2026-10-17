"""应用引导。"""

import sys

from PyQt6.QtWidgets import QApplication

from .config import Settings
from .window import PetWindow


def run() -> int:
    settings = Settings()

    app = QApplication(sys.argv)
    app.setApplicationName("Intelligent Desk Pet")

    window = PetWindow(settings)
    window.show()

    if not settings.llm_api_key:
        window.show_hint("还没配置 LLM_API_KEY 哦～在 .env 里填好再重启我就能聊天啦")
        print("警告：未配置 LLM_API_KEY，请在 .env 中填写（参考 .env.example）。")

    return app.exec()
