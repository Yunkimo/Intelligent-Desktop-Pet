"""图片归一化测试：格式转换、透明边裁剪、自复制保护（不依赖 Qt）。"""

from PIL import Image

from pet.image_utils import normalize_image, trim_transparent


def _make_static(path):
    Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(path)


def _make_animated(path):
    frames = [
        Image.new("RGBA", (16, 16), (255, 0, 0, 255)),
        Image.new("RGBA", (16, 16), (0, 0, 255, 255)),
    ]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=100, loop=0)


def test_static_converts_to_webp(tmp_path):
    src = tmp_path / "photo.png"
    _make_static(src)
    assets = tmp_path / "assets"
    assets.mkdir()

    dest = normalize_image(src, assets)

    assert dest.name == "photo.webp"
    assert dest.exists()


def test_animated_keeps_extension(tmp_path):
    src = tmp_path / "anim.gif"
    _make_animated(src)
    assets = tmp_path / "assets"
    assets.mkdir()

    dest = normalize_image(src, assets)

    assert dest.name == "anim.gif"
    assert dest.exists()


def test_self_copy_returns_same_path(tmp_path):
    """再次选中已生成的 anim.gif 时，源即目标，应直接复用而非自复制崩溃。"""
    src = tmp_path / "anim.gif"
    _make_animated(src)
    assets = tmp_path / "assets"
    assets.mkdir()

    dest = normalize_image(src, assets)
    again = normalize_image(dest, assets)

    assert again == dest
    assert dest.exists()


def test_keeps_original_name_and_preserves_old(tmp_path):
    """切换形象保留原文件名，且旧图不会被覆盖删除。"""
    a = tmp_path / "cat.png"
    b = tmp_path / "dog.png"
    _make_static(a)
    _make_static(b)
    assets = tmp_path / "assets"
    assets.mkdir()

    da = normalize_image(a, assets)
    db = normalize_image(b, assets)

    assert da.name == "cat.webp"
    assert db.name == "dog.webp"
    assert da.exists() and db.exists()  # 两张都保留


def test_trim_transparent_crops_border():
    im = Image.new("RGBA", (4, 4), (0, 0, 0, 0))
    im.putpixel((1, 1), (255, 0, 0, 255))
    im.putpixel((2, 2), (255, 0, 0, 255))

    trimmed = trim_transparent(im)

    assert trimmed.size == (2, 2)
