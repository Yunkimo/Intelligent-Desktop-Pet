"""开机自启测试：用字典假实现替代 Windows 注册表，跨平台可跑。"""

import pet.autostart as autostart


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeWinreg:
    """只实现 autostart 用到的注册表接口，值存在内存字典里。"""

    HKEY_CURRENT_USER = object()
    KEY_SET_VALUE = 1
    REG_SZ = 1

    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def CreateKeyEx(self, root, sub_key):
        return _FakeKey()

    def OpenKey(self, root, sub_key, reserved=0, access=0):
        return _FakeKey()

    def SetValueEx(self, key, name, reserved, value_type, value):
        self.values[name] = value

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        return self.values[name], self.REG_SZ

    def DeleteValue(self, key, name):
        if name not in self.values:
            raise FileNotFoundError(name)
        del self.values[name]


def _use_fake(monkeypatch) -> _FakeWinreg:
    fake = _FakeWinreg()
    monkeypatch.setattr(autostart, "winreg", fake)
    return fake


def test_enable_writes_quoted_bat_path(tmp_path, monkeypatch):
    fake = _use_fake(monkeypatch)
    bat = tmp_path / "启动桌宠.bat"

    assert autostart.enable(bat) is True
    assert fake.values[autostart._VALUE_NAME] == f'"{bat.resolve()}"'
    assert autostart.is_enabled(bat) is True


def test_is_enabled_true_with_or_without_quotes(tmp_path, monkeypatch):
    fake = _use_fake(monkeypatch)
    bat = tmp_path / "启动桌宠.bat"

    fake.values[autostart._VALUE_NAME] = str(bat.resolve())
    assert autostart.is_enabled(bat) is True

    fake.values[autostart._VALUE_NAME] = f'"{bat.resolve()}"'
    assert autostart.is_enabled(bat) is True


def test_is_enabled_false_when_absent_or_different(tmp_path, monkeypatch):
    fake = _use_fake(monkeypatch)
    bat = tmp_path / "启动桌宠.bat"

    assert autostart.is_enabled(bat) is False

    fake.values[autostart._VALUE_NAME] = str(tmp_path / "另一个.bat")
    assert autostart.is_enabled(bat) is False


def test_disable_removes_entry(tmp_path, monkeypatch):
    fake = _use_fake(monkeypatch)
    bat = tmp_path / "启动桌宠.bat"
    autostart.enable(bat)

    assert autostart.disable(bat) is True
    assert autostart._VALUE_NAME not in fake.values
    assert autostart.is_enabled(bat) is False


def test_disable_without_entry_is_noop_success(tmp_path, monkeypatch):
    _use_fake(monkeypatch)

    assert autostart.disable(tmp_path / "启动桌宠.bat") is True


def test_enable_disable_roundtrip(tmp_path, monkeypatch):
    _use_fake(monkeypatch)
    bat = tmp_path / "启动桌宠.bat"

    assert autostart.is_enabled(bat) is False
    assert autostart.enable(bat) is True
    assert autostart.is_enabled(bat) is True
    assert autostart.disable(bat) is True
    assert autostart.is_enabled(bat) is False


def test_non_windows_returns_false(tmp_path, monkeypatch):
    monkeypatch.setattr(autostart, "winreg", None)
    bat = tmp_path / "启动桌宠.bat"

    assert autostart.enable(bat) is False
    assert autostart.disable(bat) is False
    assert autostart.is_enabled(bat) is False
