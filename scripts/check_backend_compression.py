"""B4 压缩边界复核：80 组 Mock 检查，不访问外网或修改数据库。"""

import argparse
import asyncio
import gzip
import json
import sys
import zlib
from collections.abc import AsyncIterator
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


class Chunks(httpx.AsyncByteStream):
    """按指定大小发送模拟响应，并记录响应流是否被关闭。"""

    def __init__(self, payload: bytes, size: int) -> None:
        self.payload = payload
        self.size = size
        self.close_count = 0

    async def __aiter__(self) -> AsyncIterator[bytes]:
        for offset in range(0, len(self.payload), self.size):
            yield self.payload[offset : offset + self.size]

    async def aclose(self) -> None:
        self.close_count += 1


async def run() -> dict:
    """分别验证两种压缩格式、十类输入、四种分块，失败即报错。"""
    sys.path.insert(0, str(ROOT / "backend"))
    from app import config
    from app.web_query import WebQueryClient, WebQueryError

    original = config.WEB_QUERY_MAX_BYTES, config.WEB_QUERY_MAX_CONCURRENT
    config.WEB_QUERY_MAX_BYTES, config.WEB_QUERY_MAX_CONCURRENT = 1024, 1
    records = []
    try:
        for encoding, compressor in [("gzip", gzip.compress), ("deflate", zlib.compress)]:
            small = b"verified response"
            packed = compressor(small)
            corrupted = packed[:-1] + bytes([packed[-1] ^ 255])
            raw_overlimit = (
                gzip.compress(b"x" * 1024, compresslevel=0)
                if encoding == "gzip"
                else zlib.compress(b"x" * 1024, level=0)
            )
            cases = [
                ("valid", packed, small.decode()),
                ("exact_output_limit", compressor(b"x" * 1024), "x" * 1024),
                ("output_one_byte_over", compressor(b"x" * 1025), "upstream_response_too_large"),
                ("expansion_bomb", compressor(b"x" * 100_000), "upstream_response_too_large"),
                ("raw_overlimit", raw_overlimit, "upstream_response_too_large"),
                ("invalid_stream", b"not compressed", "upstream_invalid_compression"),
                ("truncated", packed[:-1], "upstream_invalid_compression"),
                ("corrupted_checksum", corrupted, "upstream_invalid_compression"),
                ("trailing_data", packed + b"junk", "upstream_invalid_compression"),
                ("concatenated_streams", packed + packed, "upstream_invalid_compression"),
            ]
            for name, payload, expected in cases:
                for chunk_size in [1, 7, 64, 4096]:
                    stream = Chunks(payload, chunk_size)

                    def transport(request: httpx.Request) -> httpx.Response:
                        return httpx.Response(
                            200, stream=stream, headers={"content-encoding": encoding}
                        )

                    adapter = WebQueryClient(httpx.MockTransport(transport))
                    try:
                        status = 200
                        try:
                            actual = await adapter._fetch(config.WEB_SEARCH_URL, {"q": "test"})
                        except WebQueryError as exc:
                            actual, status = exc.code, exc.status
                        expected_status = 200 if name in {"valid", "exact_output_limit"} else 502
                        if actual != expected or status != expected_status:
                            raise RuntimeError(f"{encoding}/{name}/{chunk_size}: unexpected result")
                        if stream.close_count != 1 or adapter._slots.locked():
                            raise RuntimeError(
                                f"{encoding}/{name}/{chunk_size}: resource not released"
                            )
                    finally:
                        await adapter.close()
                    records.append(
                        {
                            "encoding": encoding,
                            "case": name,
                            "chunk_size": chunk_size,
                            "passed": True,
                        }
                    )
    finally:
        config.WEB_QUERY_MAX_BYTES, config.WEB_QUERY_MAX_CONCURRENT = original
    return {
        "python": sys.version.split()[0],
        "budget_bytes": 1024,
        "network": "mock only",
        "passed": len(records),
        "failed": 0,
        "cases": records,
    }


def main() -> None:
    """可选保存 UTF-8 JSON；默认只打印汇总，失败退出非零。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run())
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("python", "network", "passed", "failed")}))


if __name__ == "__main__":
    main()
