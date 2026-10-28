"""图片归一化：把用户选中的图转成 Qt 能稳定读取的格式，复制进 assets/。"""

import shutil
from pathlib import Path

from PIL import Image


def trim_transparent(im: Image.Image) -> Image.Image:
    """裁掉四周全透明边，让形象更贴合、显示更大。"""
    bbox = im.getchannel("A").getbbox()
    return im.crop(bbox) if bbox else im


def normalize_image(src: Path, assets_dir: Path) -> Path:
    """把用户选中的图统一转成 Qt 能稳定读取的格式，复制进 assets/ 并返回目标路径。

    - 动图（GIF / WebP 动画）保留原后缀，按原文件名复制为 <原名>.<ext>；
    - 静态图裁掉透明边后，按原文件名转成 <原名>.webp；
    - 再次选中已生成的文件时，源与目标同文件，直接复用、避免自复制崩溃。
    """
    src = src.resolve()
    assets_dir = assets_dir.resolve()

    with Image.open(src) as im:
        animated = getattr(im, "is_animated", False)
        if animated:
            ext = src.suffix.lower() or ".gif"
            dest = (assets_dir / f"{src.stem}{ext}").resolve()
        else:
            dest = (assets_dir / f"{src.stem}.webp").resolve()

        if src == dest:
            # 再次选中已生成的文件：无需（也不能）自己复制自己
            return dest

        if animated:
            shutil.copyfile(src, dest)
        else:
            trimmed = trim_transparent(im.convert("RGBA"))
            trimmed.save(dest, lossless=True)
    return dest
