"""系统托盘集成：状态色图标 + 悬停摘要 + 左键显隐悬浮窗 + 右键菜单。

纯函数（aggregate_level / tooltip_text / make_icon）不依赖托盘可用性，
可在离屏环境单测；托盘不可用时 start() 打中文日志并返回 False，悬浮窗不受影响。
"""
from __future__ import annotations

import sys
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from app.model import ProviderStatus, QuotaSnapshot
from app.ui.card import VENDOR_NAMES, fmt_decimal

LEVEL_COLORS = {
    "ok": "#81c995",
    "warn": "#fdd663",
    "danger": "#f28b82",
    "none": "#9aa0a6",
}
TOOLTIP_MAX_LINES = 6


def _card_name(snapshot: QuotaSnapshot) -> str:
    name = VENDOR_NAMES.get(snapshot.vendor, snapshot.vendor)
    if snapshot.account_label and snapshot.account_label != "默认":
        name += f" · {snapshot.account_label}"
    return name


def aggregate_level(
    snapshots: list, warn_percent: float = 30.0, danger_percent: float = 10.0
) -> str:
    """全部卡片最紧窗口剩余比例的分级：ok / warn / danger；无数据为 none。"""
    worst = None
    for snapshot in snapshots:
        for window in snapshot.windows:
            remaining = window.remaining_percent
            if remaining is None:
                continue
            worst = remaining if worst is None else min(worst, remaining)
    if worst is None:
        return "none"
    if worst <= danger_percent:
        return "danger"
    if worst <= warn_percent:
        return "warn"
    return "ok"


def tooltip_text(snapshots: list) -> str:
    lines = []
    for snapshot in snapshots:
        name = _card_name(snapshot)
        remainings = [
            window.remaining_percent
            for window in snapshot.windows
            if window.remaining_percent is not None
        ]
        if snapshot.status == ProviderStatus.ERROR and not snapshot.windows:
            lines.append(f"{name}：获取失败")
        elif not remainings:
            lines.append(f"{name}：暂无额度数据")
        else:
            lines.append(f"{name}：最紧剩余 {fmt_decimal(min(remainings))}%")
    if not lines:
        return "Coding Plan 额度悬浮窗"
    if len(lines) > TOOLTIP_MAX_LINES:
        lines = lines[:TOOLTIP_MAX_LINES]
        lines.append("…")
    return "\n".join(lines)


def make_icon(level: str) -> QIcon:
    """按状态色绘制圆点图标（无二进制资源依赖）。"""
    pixmap = QPixmap(32, 32)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(LEVEL_COLORS[level]))
    painter.drawEllipse(4, 4, 24, 24)
    painter.end()
    return QIcon(pixmap)


class TrayController(QObject):
    """托盘生命周期与交互；悬浮窗渲染后经 update() 同步状态。"""

    refresh_requested = Signal()

    def __init__(self, window, config: dict, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._window = window
        self._warn_percent = float(config.get("warn_percent", 30))
        self._danger_percent = float(config.get("danger_percent", 10))
        self._tray: Optional[QSystemTrayIcon] = None
        self._menu: Optional[QMenu] = None
        self._toggle_action = None
        self._level = "none"

    def start(self) -> bool:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            if sys.stdout:  # windowed 打包下 stdout 为 None，print 会崩
                print("系统托盘不可用，跳过托盘功能（悬浮窗不受影响）")
            return False
        self._build_menu()
        self._tray = QSystemTrayIcon(make_icon("none"))
        self._tray.setContextMenu(self._menu)
        self._tray.setToolTip("Coding Plan 额度悬浮窗")
        self._tray.activated.connect(self._on_activated)
        self._tray.show()
        self._sync_toggle_text()
        return True

    def _build_menu(self) -> QMenu:
        self._menu = QMenu()
        self._toggle_action = self._menu.addAction("显示悬浮窗")
        self._toggle_action.triggered.connect(self._toggle_window)
        refresh_action = self._menu.addAction("立即刷新")
        refresh_action.triggered.connect(self.refresh_requested.emit)
        self._menu.addSeparator()
        quit_action = self._menu.addAction("退出")
        quit_action.triggered.connect(self._window._quit_app)
        return self._menu

    def update(self, snapshots: list) -> None:
        if self._tray is None:
            return
        self._tray.setToolTip(tooltip_text(snapshots))
        level = aggregate_level(snapshots, self._warn_percent, self._danger_percent)
        if level != self._level:
            self._level = level
            self._tray.setIcon(make_icon(level))
        self._sync_toggle_text()

    def _on_activated(self, reason) -> None:
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_window()

    def _toggle_window(self) -> None:
        if self._window.isVisible():
            self._window.hide()
        else:
            self._window.show()
        self._sync_toggle_text()

    def _sync_toggle_text(self) -> None:
        if self._toggle_action is None:
            return
        visible = self._window.isVisible()
        self._toggle_action.setText("隐藏悬浮窗" if visible else "显示悬浮窗")
