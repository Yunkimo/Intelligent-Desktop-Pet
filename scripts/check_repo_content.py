"""Audit tracked Git content, including the staged version of each file by default."""

import argparse
import subprocess
from collections import Counter
from pathlib import PurePosixPath

IMAGE_TYPES = {
    ".png": lambda b: b.startswith(b"\x89PNG\r\n\x1a\n"),
    ".gif": lambda b: b.startswith((b"GIF87a", b"GIF89a")),
    ".jpg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".jpeg": lambda b: b.startswith(b"\xff\xd8\xff"),
    ".webp": lambda b: b.startswith(b"RIFF") and b[8:12] == b"WEBP",
    ".ico": lambda b: b.startswith(b"\x00\x00\x01\x00"),
}
LOCAL_DIRECTORIES = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "ci-results",
}
LOCAL_SUFFIXES = {
    ".log",
    ".db",
    ".db-wal",
    ".db-shm",
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".sqlite3",
    ".sqlite3-wal",
    ".sqlite3-shm",
    ".pyc",
    ".pyo",
    ".wav",
    ".mp3",
    ".ogg",
    ".flac",
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mkv",
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".zip",
    ".7z",
    ".tar",
    ".gz",
    ".whl",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".msi",
    ".bin",
    ".pt",
    ".onnx",
    ".safetensors",
}


def entries(tree: str | None) -> list[tuple[bytes, str]]:
    command = ["ls-tree", "--full-tree", "-rz", tree] if tree else ["ls-files", "--stage", "-z"]
    records = subprocess.check_output(["git", *command]).split(b"\0")
    result = []
    for record in filter(None, records):
        metadata, raw_path = record.split(b"\t", 1)
        _, kind_or_oid, oid_or_stage = metadata.split()
        if not tree and oid_or_stage != b"0":
            raise ValueError("Resolve Git index conflicts before auditing.")
        result.append((oid_or_stage if tree else kind_or_oid, raw_path.decode("utf-8")))
    return result


def classify(path: str, data: bytes) -> str:
    p = PurePosixPath(path)
    name, suffix = p.name.lower(), p.suffix.lower()
    if (
        any(part.lower() in LOCAL_DIRECTORIES for part in p.parts[:-1])
        or suffix in LOCAL_SUFFIXES
        or name == ".env"
        or (name.startswith(".env.") and not name.endswith(".example"))
        or name.startswith("npm-debug.log.")
        or (
            name in {"config.js", "project.private.config.json"}
            and p.parent == PurePosixPath("miniprogram")
        )
    ):
        return "local file"
    if suffix in IMAGE_TYPES:
        return "image" if IMAGE_TYPES[suffix](data) else "invalid image signature"
    try:
        decoded = data.decode("utf-8")
    except UnicodeDecodeError:
        return "non-image binary"
    if any(ord(ch) < 32 and ch not in "\t\r\n\f" for ch in decoded) or "\x7f" in decoded:
        return "non-image binary"
    return "text"


def audit(tree: str | None) -> int:
    # Run from the repo root so the index and tree use the same path conventions.
    if subprocess.check_output(["git", "rev-parse", "--show-prefix"]).strip():
        raise ValueError("Run this script from the repository root.")

    counts: Counter[str] = Counter()
    with subprocess.Popen(
        ["git", "cat-file", "--batch"], stdin=subprocess.PIPE, stdout=subprocess.PIPE
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        for oid, path in entries(tree):
            process.stdin.write(oid + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            if len(header) != 3:
                counts["missing object"] += 1
                print(f"ERROR [missing object] {path}")
                continue
            _, kind, size = header
            data = process.stdout.read(int(size))
            if len(data) != int(size) or process.stdout.read(1) != b"\n":
                raise RuntimeError(f"Truncated Git object: {path}")
            category = classify(path, data) if kind == b"blob" else "non-blob Git entry"
            counts[category] += 1
            if category not in {"image", "text"}:
                print(f"ERROR [{category}] {path} ({len(data)} bytes)")
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("git cat-file failed")

    allowed = counts["text"] + counts["image"]
    total = counts.total()
    print(
        f"Checked {total} paths: {counts['text']} text, {counts['image']} images, "
        f"{total - allowed} rejected."
    )
    return int(total != allowed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", help="audit a Git revision instead of the staged index")
    args = parser.parse_args()
    return audit(args.tree)


if __name__ == "__main__":
    raise SystemExit(main())
