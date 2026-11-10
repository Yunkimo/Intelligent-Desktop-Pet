"""图片仅检查受限尺寸头，不调用解码器。"""

import struct
import zlib

import pytest
from app.image_header import inspect_image


def test_png_dimensions_and_checksum():
    chunk = b"IHDR" + struct.pack(">II", 1200, 680) + b"\x08\x02\x00\x00\x00"
    image = (
        b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + chunk + struct.pack(">I", zlib.crc32(chunk))
    )
    assert inspect_image(image) == ("image/png", 1200, 680)
    with pytest.raises(ValueError):
        inspect_image(image[:-1] + bytes([image[-1] ^ 1]))


@pytest.mark.parametrize("marker", [0xC0, 0xC2])
def test_jpeg_segment_walk(marker):
    frame = b"\x08" + struct.pack(">HH", 680, 1200) + b"\x01\x01\x11\x00"
    image = (
        b"\xff\xd8\xff\xe0\x00\x04ab\xff"
        + bytes([marker])
        + struct.pack(">H", len(frame) + 2)
        + frame
    )
    assert inspect_image(image) == ("image/jpeg", 1200, 680)
    with pytest.raises(ValueError):
        inspect_image(image[:-4])


@pytest.mark.parametrize(
    "data", [b"", b"fake", b"\xff\xd8", b"\xff\xd8\xff\xda", b"\x89PNG\r\n\x1a\n"]
)
def test_bad_images_rejected(data):
    with pytest.raises(ValueError):
        inspect_image(data)
