"""检查项目文档的本地相对链接和代码围栏；不联网、不执行文档命令。"""

import argparse
import hashlib
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


def check_checksums(manifest: Path, root: Path) -> tuple[list[str], int]:
    """核对指定源码快照；仅将 CRLF 转为 LF，兼容 Git 的文本换行转换。"""
    errors, count = [], 0
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            errors.append(f"{manifest.name}:{number}: 校验清单格式无效")
            continue
        expected, name = match.groups()
        target = (root / name).resolve()
        if not target.is_relative_to(root.resolve()) or not target.is_file():
            errors.append(f"{manifest.name}:{number}: 校验目标不存在或越界 {name}")
            continue
        count += 1
        actual = hashlib.sha256(target.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
        if actual != expected:
            errors.append(f"{name}: 源码校验值不匹配")
    if count == 0 and not errors:
        errors.append(f"{manifest.name}: 校验清单为空")
    return errors, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--checksums", type=Path, help="可选：核对与本次源码对应的快照清单")
    args = parser.parse_args()
    root = args.root.resolve()
    paths = documents(root)
    errors, count = [], 0
    for path in paths:
        found, number = check_file(path, root)
        errors.extend(found)
        count += number
    checksum_count = None
    if args.checksums:
        try:
            found, checksum_count = check_checksums(root / args.checksums, root)
            errors.extend(found)
        except (OSError, UnicodeError) as exc:
            errors.append(f"无法读取源码校验清单：{type(exc).__name__}")
    for error in errors:
        print("FAIL " + error)
    if errors:
        return 1
    print(
        f"PASS {len(paths)} documents, {count} local links, paired fences; external URLs/anchors not checked"
    )
    if checksum_count is not None:
        print(f"PASS {checksum_count} source checksums; CRLF normalized to LF")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
