"""应用入口。

用法：
    python -m app.main [--config config.jsonc]
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.config import default_config_path, ensure_default_config, load_config, load_state
from app.providers import build_providers
from app.service import QuotaService
from app.ui.tray import TrayController
from app.ui.window import MainWindow, apply_app_style


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Coding Plan 额度悬浮窗")
    parser.add_argument("--config", default=str(default_config_path()), help="用户配置文件路径（JSONC）")
    args = parser.parse_args(argv)

    config_path = Path(args.config)
    ensure_default_config(config_path)
    config = load_config(config_path)
    state_path = config_path.parent / "state.json"
    state = load_state(state_path)

    app = QApplication(sys.argv[:1])
    apply_app_style(app)

    service = QuotaService(build_providers(config))
    window = MainWindow(config, state, str(state_path), service)

    tray = TrayController(window, config)
    tray.refresh_requested.connect(window.refresh)
    window.snapshots_updated.connect(tray.update)
    tray.start()

    # Ctrl+C：Qt 事件循环是 C++ 代码，Python 信号默认没有机会被处理；
    # 注册处理器 + 空转定时器（信号泵）让 SIGINT 能落到 Python 侧优雅退出
    def _handle_sigint(*_args):
        window.close()
        QApplication.quit()

    signal.signal(signal.SIGINT, _handle_sigint)
    pump = QTimer()
    pump.setInterval(300)
    pump.timeout.connect(lambda: None)
    pump.start()

    window.show()
    window.refresh()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
