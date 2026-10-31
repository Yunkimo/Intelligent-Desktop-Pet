"""检查 PNG/JPEG 的尺寸，不解压不执行第三方图片解码器。"""

import struct
import zlib


def inspect_image(data: bytes) -> tuple[str, int, int]:
    """从固定 PNG IHDR 或 JPEG SOF 中读取尺寸，损坏文件交由上游继续校验。"""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        if len(data) < 33 or data[8:16] != b"\x00\x00\x00\x0dIHDR":
            raise ValueError("invalid PNG header")
        if zlib.crc32(data[12:29]) != int.from_bytes(data[29:33], "big"):
            raise ValueError("invalid PNG checksum")
        width, height = struct.unpack(">II", data[16:24])
        mime = "image/png"
    elif data.startswith(b"\xff\xd8"):
        pos = 2
        while pos < len(data):
            if data[pos] != 255:
                raise ValueError("invalid JPEG marker")
            while pos < len(data) and data[pos] == 255:
                pos += 1
            if pos >= len(data):
                break
            marker = data[pos]
            pos += 1
            if marker in (0xD9, 0xDA):
                break
            if marker == 0x01 or 0xD0 <= marker <= 0xD8:
                continue
            if pos + 2 > len(data):
                break
            length = int.from_bytes(data[pos : pos + 2], "big")
            if length < 2 or pos + length > len(data):
                raise ValueError("invalid JPEG segment")
            if marker in (
                0xC0,
                0xC1,
                0xC2,
                0xC3,
                0xC5,
                0xC6,
                0xC7,
                0xC9,
                0xCA,
                0xCB,
                0xCD,
                0xCE,
                0xCF,
            ):
                if length < 8:
                    raise ValueError("invalid JPEG dimensions")
                height, width = struct.unpack(">HH", data[pos + 3 : pos + 7])
                mime = "image/jpeg"
                break
            pos += length
        else:
            raise ValueError("missing JPEG dimensions")
        if "mime" not in locals():
            raise ValueError("missing JPEG dimensions")
    else:
        raise ValueError("only PNG/JPEG supported")
    if width < 1 or height < 1:
        raise ValueError("invalid dimensions")
    return mime, width, height
