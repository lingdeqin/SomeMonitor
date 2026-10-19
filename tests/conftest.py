"""pytest 全局配置：离屏 Qt 环境 + 仓库根入 sys.path。"""
import os
import sys
from pathlib import Path

# 必须在导入任何 PySide6 模块之前设置
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


import pytest


@pytest.fixture(scope="session")
def qapp():
    """共享一个离屏 QApplication。"""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
