"""检查 C4 文档相对文件链接、代码围栏与 Shell 文件换行；不验证外链/锚点。"""

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DOCUMENTS = (
    "docs/deploy.md",
    "docs/c4-verification.md",
    "docs/C4-人工复验.md",
    "docs/C4-服务器操作.md",
    "docs/C4-IP调试复验.md",
    "docs/evidence/c4/acceptance-template.md",
)


def main() -> int:
    """逐项报错；成功只代表文件链接和基础 Markdown 结构通过。"""
    errors = []
    links = 0
    for name in DOCUMENTS:
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        if sum(line.startswith("```") for line in text.splitlines()) % 2:
            errors.append(f"{name}: 代码围栏未配对")
        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            target = target.strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or not parsed.path:
                continue
            links += 1
            if not (path.parent / unquote(parsed.path)).exists():
                errors.append(f"{name}: 文件链接不存在 {target}")
    for name in ("scripts/run-backend.sh", "scripts/deploy-server.sh"):
        if b"\r" in (ROOT / name).read_bytes():
            errors.append(f"{name}: Shell 脚本应使用 LF")
    for error in errors:
        print("FAIL " + error)
    if errors:
        return 1
    print(f"PASS {len(DOCUMENTS)} 份文档、{links} 个相对文件链接、Shell LF；外链与锚点未纳入")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
