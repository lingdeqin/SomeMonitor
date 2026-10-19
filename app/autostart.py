"""开机自启：当前用户注册表 Run 键读写（Windows）。

注册表是唯一事实源——菜单勾选态查询注册表，切换直接写注册表，
不落 state.json，避免双源漂移。
"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "SomeMonitor"


def autostart_command() -> str:
    """登录时执行的命令行；不依赖工作目录。"""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    repo_root = Path(__file__).resolve().parent.parent
    interpreter = Path(sys.executable)
    # 源码运行优先 pythonw，避免登录时闪控制台窗口
    pythonw = interpreter.with_name("pythonw.exe")
    if pythonw.is_file():
        interpreter = pythonw
    return f'"{interpreter}" "{repo_root / "run.py"}"'


def is_autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, APP_NAME)
        return value == autostart_command()
    except OSError:
        return False


def set_autostart_enabled(enabled: bool) -> None:
    if enabled:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, autostart_command())
    else:
        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
            ) as key:
                winreg.DeleteValue(key, APP_NAME)
        except OSError:
            pass
