"""文档检查应发现失效链接，同时避免把示例代码或外链当本地文件。"""

import hashlib

import pytest
from check_docs import check_checksums, check_file, documents


def test_relative_links_and_examples(tmp_path):
    (tmp_path / "with space.md").write_text("# Target\n", encoding="utf-8")
    source = tmp_path / "README.md"
    source.write_text(
        "[target](with%20space.md#title)\n[external](https://example.org/missing)\n"
        "[anchor](#title)\n`[inline](missing.md)`\n```md\n[example](missing.md)\n```\n",
        encoding="utf-8",
    )
    assert check_file(source, tmp_path) == ([], 1)


def test_missing_file_reports_source_line(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Readme\n[missing](absent.md)\n", encoding="utf-8")
    errors, count = check_file(source, tmp_path)
    assert count == 1 and len(errors) == 1
    assert "README.md:2:" in errors[0] and "absent.md" in errors[0]


def test_unclosed_fence_is_rejected(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("# Readme\n~~~~text\nexample\n", encoding="utf-8")
    assert "README.md:2:" in check_file(source, tmp_path)[0][0]


def test_long_fence_can_contain_triple_backticks(tmp_path):
    source = tmp_path / "README.md"
    source.write_text("````md\n```text\n[example](missing.md)\n```\n````\n", encoding="utf-8")
    assert check_file(source, tmp_path) == ([], 0)


def test_discovery_does_not_read_agent_or_vendor_files(tmp_path):
    (tmp_path / "README.md").touch()
    (tmp_path / "agent.md").touch()
    vendor = tmp_path / "node_modules"
    vendor.mkdir()
    (vendor / "README.md").touch()
    assert documents(tmp_path) == [tmp_path / "README.md"]


@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_source_snapshot_is_portable_but_detects_changes(tmp_path, newline):
    """Git 换行转换不应误报；真正的内容变化必须失败。"""
    source = tmp_path / "README.md"
    source.write_bytes(b"# Title" + newline)
    manifest = tmp_path / "source.sha256"
    manifest.write_text(hashlib.sha256(b"# Title\n").hexdigest() + "  README.md\n")
    assert check_checksums(manifest, tmp_path) == ([], 1)
    source.write_bytes(b"# Changed" + newline)
    errors, count = check_checksums(manifest, tmp_path)
    assert count == 1 and len(errors) == 1 and "README.md" in errors[0]


@pytest.mark.parametrize("entry", ["", "invalid", "missing.md", "../outside.md"])
def test_bad_source_snapshot_cannot_pass(tmp_path, entry):
    """空清单、格式损坏、缺失或越界目标不能产生通过结论。"""
    manifest = tmp_path / "source.sha256"
    line = entry if entry in {"", "invalid"} else "0" * 64 + "  " + entry
    manifest.write_text(line, encoding="utf-8")
    errors, count = check_checksums(manifest, tmp_path)
    assert errors and count == 0
