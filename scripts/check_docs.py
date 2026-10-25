"""检查项目文档的本地相对链接和代码围栏；不联网、不执行文档命令。"""

import argparse
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"!?\[[^\]]*\]\((<[^>]+>|[^\s)]+)(?:\s+['\"][^)]*['\"])?\)")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})(.*)$")


def documents(root: Path) -> list[Path]:
    """只取维护的文档目录；不读取代理指令、虚拟环境或个人配置。"""
    paths = set(root.glob("*.md"))
    paths.update((root / "docs").rglob("*.md"))
    paths.update(root / name for name in ("assets/README.md", "miniprogram/README.md"))
    return sorted(
        path
        for path in paths
        if path.is_file() and path.name.lower() not in {"agent.md", "agents.md"}
    )


def check_file(path: Path, root: Path) -> tuple[list[str], int]:
    """忽略围栏内示例链接、外链和锚点；返回错误位置与本地链接计数。"""
    errors, count = [], 0
    opening = None
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = FENCE.match(line)
        if match:
            marker, rest = match.groups()
            if opening is None:
                opening = (marker[0], len(marker), number)
            elif marker[0] == opening[0] and len(marker) >= opening[1] and not rest.strip():
                opening = None
            continue
        if opening:
            continue
        for target in LINK.findall(re.sub(r"`[^`]*`", "", line)):
            target = target.strip("<>")
            parsed = urlsplit(target)
            if parsed.scheme or parsed.netloc or not parsed.path or parsed.path.startswith("/"):
                continue
            count += 1
            linked = path.parent / unquote(parsed.path)
            if not linked.exists():
                errors.append(f"{path.relative_to(root)}:{number}: 文件链接不存在 {target}")
    if opening:
        errors.append(f"{path.relative_to(root)}:{opening[2]}: 代码围栏未配对")
    return errors, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    root = args.root.resolve()
    paths = documents(root)
    errors, count = [], 0
    for path in paths:
        found, number = check_file(path, root)
        errors.extend(found)
        count += number
    for error in errors:
        print("FAIL " + error)
    if errors:
        return 1
    print(
        f"PASS {len(paths)} documents, {count} local links, paired fences; external URLs/anchors not checked"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
