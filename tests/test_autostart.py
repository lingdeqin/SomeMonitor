"""开机自启单元测试：命令构造 + 注册表读写（假 winreg，不触真实注册表）。"""
from __future__ import annotations

import app.autostart as autostart


class FakeWinreg:
    """winreg 内存替身：仅覆盖 autostart 用到的 API。"""

    HKEY_CURRENT_USER = 1
    REG_SZ = 1
    KEY_SET_VALUE = 2

    def __init__(self):
        self.store = {}

    class _FakeKey:
        def __init__(self, store, path, access=None):
            self._store = store
            self._path = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def _values(self):
            return self._store.setdefault(self._path, {})

    def OpenKey(self, root, path, reserved=0, access=0):
        if path not in self.store:
            raise OSError("key not found")
        return self._FakeKey(self.store, path)

    def CreateKey(self, root, path):
        return self._FakeKey(self.store, path)

    def SetValueEx(self, key, name, reserved, typ, value):
        key._values()[name] = value

    def QueryValueEx(self, key, name):
        values = key._values()
        if name not in values:
            raise OSError("value not found")
        return values[name], self.REG_SZ

    def DeleteValue(self, key, name):
        if key._values().pop(name, None) is None:
            raise OSError("value not found")


def _patch(monkeypatch):
    fake = FakeWinreg()
    monkeypatch.setattr(autostart, "winreg", fake)
    return fake


def test_autostart_command_not_frozen(monkeypatch):
    monkeypatch.setattr(autostart.sys, "frozen", False, raising=False)
    command = autostart.autostart_command()
    assert command.endswith('run.py"')
    assert command.startswith('"')


def test_autostart_command_frozen(monkeypatch):
    monkeypatch.setattr(autostart.sys, "frozen", True, raising=False)
    monkeypatch.setattr(autostart.sys, "executable", r"C:\apps\SomeMonitor.exe")
    assert autostart.autostart_command() == '"C:\\apps\\SomeMonitor.exe"'


def test_enable_disable_roundtrip(monkeypatch):
    fake = _patch(monkeypatch)
    assert autostart.is_autostart_enabled() is False  # 键不存在

    autostart.set_autostart_enabled(True)
    assert fake.store[autostart.RUN_KEY][autostart.APP_NAME] == (
        autostart.autostart_command()
    )
    assert autostart.is_autostart_enabled() is True

    autostart.set_autostart_enabled(False)
    assert autostart.APP_NAME not in fake.store[autostart.RUN_KEY]
    assert autostart.is_autostart_enabled() is False


def test_mismatched_command_reads_as_disabled(monkeypatch):
    # 手动改过命令（如换了 Python 路径）-> 视为未启用，重勾选即修正
    fake = _patch(monkeypatch)
    fake.store[autostart.RUN_KEY] = {autostart.APP_NAME: '"other.exe"'}
    assert autostart.is_autostart_enabled() is False


def test_disable_missing_value_is_noop(monkeypatch):
    _patch(monkeypatch)
    autostart.set_autostart_enabled(False)  # 不抛异常


def test_menu_contains_autostart_toggle(qapp, tmp_path, monkeypatch):
    from app.ui.window import MainWindow

    calls = []
    monkeypatch.setattr(
        "app.ui.window.is_autostart_enabled", lambda: False
    )
    monkeypatch.setattr(
        "app.ui.window.set_autostart_enabled",
        lambda enabled: calls.append(enabled),
    )

    class _NoopService:
        def refresh(self):
            return []

    window = MainWindow({}, {}, str(tmp_path / "state.json"), _NoopService())
    menu, _, _ = window._build_menu()
    autostart_action = next(
        action for action in menu.actions() if action.text() == "开机自启"
    )
    assert autostart_action.isCheckable() is True
    assert autostart_action.isChecked() is False
    autostart_action.toggled.emit(True)  # 模拟用户点击勾选
    assert calls == [True]
    menu.deleteLater()
