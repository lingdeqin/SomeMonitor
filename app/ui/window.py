"""主悬浮窗：无边框 / 置顶 / 半透明 / 拖拽 / 右键菜单 / 自动刷新。"""
from __future__ import annotations

from functools import partial
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMenu,
    QSlider,
    QVBoxLayout,
    QWidget,
    QWidgetAction,
)

from app.autostart import is_autostart_enabled, set_autostart_enabled
from app.config import save_state
from app.model import QuotaSnapshot, WindowType, window_label
from app.providers import providers_config_error
from app.service import QuotaService
from app.ui.card import WINDOW_ORDER, AccountCard

QSS = """
#rootPanel {
    background-color: rgba(28, 30, 36, 235);
    border-radius: 12px;
}
#accountCard {
    background-color: rgba(52, 56, 66, 205);
    border-radius: 8px;
}
QLabel { color: #e8eaed; font-size: 12px; }
#cardTitle { font-weight: bold; }
#statusText, #muted { color: #9aa0a6; }
#errorText { color: #f28b82; }
#staleText { color: #fdd663; }
#frozenBadge { color: #f28b82; font-weight: bold; }
#okBadge { color: #81c995; }
#windowInfo { color: #bec3c9; }
QProgressBar {
    background-color: rgba(255, 255, 255, 30);
    border: none;
    border-radius: 4px;
}
QProgressBar::chunk { background-color: #81c995; border-radius: 4px; }
QProgressBar#warnBar::chunk { background-color: #fdd663; }
QProgressBar#dangerBar::chunk { background-color: #f28b82; }
QMenu { background-color: #2d2f33; color: #e8eaed; }
QMenu::item:selected { background-color: #3c4043; }
QSlider::groove:horizontal { height: 4px; background: #5f6368; }
QSlider::handle:horizontal { background: #8ab4f8; width: 12px; margin: -5px 0; }
"""


def apply_app_style(app: QApplication) -> None:
    app.setStyleSheet(QSS)


class RefreshWorker(QThread):
    """后台采集线程：避免网络请求阻塞 UI。"""

    finished_with_data = Signal(object)

    def __init__(self, service: QuotaService, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.service = service

    def run(self) -> None:  # pragma: no cover - 线程入口
        try:
            snapshots = self.service.refresh()
        except Exception:
            snapshots = []
        self.finished_with_data.emit(snapshots)


class MainWindow(QWidget):
    """Coding Plan 额度悬浮窗主窗体。"""

    snapshots_updated = Signal(object)

    def __init__(
        self,
        config: dict,
        state: dict,
        state_path: str,
        service: QuotaService,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.config = config
        self.state = state
        self.state_path = state_path
        self.service = service
        self._drag_offset = None
        self._cards = []
        self._worker = None
        self._last_snapshots = []
        self._last_locked_size = None

        self._providers_error = providers_config_error(config)

        self.setWindowTitle("Coding Plan 额度悬浮窗")
        self.resize(324, 40)

        self._apply_window_flags()
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowOpacity(float(self._effective_setting("opacity", 0.9)))

        root = QWidget(self)
        root.setObjectName("rootPanel")
        self._root = root
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(root)

        self._inner = QVBoxLayout(root)
        self._inner.setContentsMargins(8, 8, 8, 8)
        self._inner.setSpacing(6)

        self._status_label = QLabel("加载中…")
        self._status_label.setObjectName("statusText")
        self._inner.addWidget(self._status_label)
        if self._providers_error:
            self._status_label.setText(self._providers_error)
            self._status_label.setWordWrap(True)

        window_pos = self.state.get("window") or {}
        if window_pos.get("x") is not None and window_pos.get("y") is not None:
            self.move(int(window_pos["x"]), int(window_pos["y"]))

        self._timer = QTimer(self)
        self._timer.setInterval(max(5, int(self.config.get("refresh_seconds", 60))) * 1000)
        self._timer.timeout.connect(self.refresh)
        self._timer.start()

    # ---------- 窗口形态 ----------

    def _effective_setting(self, key: str, default):
        """运行时状态（state.json）优先于用户配置（config.jsonc）。"""
        value = self.state.get(key)
        if value is None:
            value = self.config.get(key, default)
        return value

    def _apply_window_flags(self) -> None:
        flags = Qt.FramelessWindowHint | Qt.Tool
        if bool(self._effective_setting("always_on_top", True)):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._drag_offset = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            )
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_offset = None
        event.accept()

    # ---------- 右键菜单 ----------

    def _build_menu(self) -> QMenu:
        menu = QMenu(self)

        refresh_action = menu.addAction("立即刷新")

        opacity_menu = menu.addMenu("不透明度")
        slider = QSlider(Qt.Horizontal)
        slider.setRange(30, 100)
        slider.setValue(int(round(self.windowOpacity() * 100)))
        slider_action = QWidgetAction(opacity_menu)
        slider_action.setDefaultWidget(slider)
        opacity_menu.addAction(slider_action)
        slider.valueChanged.connect(self._set_opacity_from_slider)

        top_action = menu.addAction("始终置顶")
        top_action.setCheckable(True)
        top_action.setChecked(bool(self._effective_setting("always_on_top", True)))
        top_action.toggled.connect(self._toggle_on_top)

        autostart_action = menu.addAction("开机自启")
        autostart_action.setCheckable(True)
        autostart_action.setChecked(is_autostart_enabled())
        autostart_action.toggled.connect(set_autostart_enabled)

        for window_type_value in self._present_window_type_values():
            label = window_label(WindowType(window_type_value))
            hide_action = menu.addAction(f"隐藏{label}")
            hide_action.setCheckable(True)
            hide_action.setChecked(window_type_value in self._hidden_types())
            hide_action.toggled.connect(
                partial(self._toggle_window_type, window_type_value)
            )

        menu.addSeparator()
        quit_action = menu.addAction("退出")
        return menu, refresh_action, quit_action

    def contextMenuEvent(self, event) -> None:
        menu, refresh_action, quit_action = self._build_menu()
        chosen = menu.exec(event.globalPos())
        if chosen == refresh_action:
            self.refresh()
        elif chosen == quit_action:
            self._quit_app()
        menu.deleteLater()

    # ---------- 窗口类型隐藏 ----------

    def _hidden_types(self) -> set:
        types = self.state.get("hidden_window_types")
        return {str(value) for value in types} if isinstance(types, list) else set()

    def _present_window_type_values(self) -> list:
        """当前数据中出现的额度窗口类型（不含月度冻结徽章），按窗口行顺序。"""
        present = set()
        for snapshot in self._last_snapshots:
            for window in snapshot.windows:
                if window.type is not WindowType.MONTHLY_FREEZE:
                    present.add(window.type.value)
        return [
            window_type.value
            for window_type in WINDOW_ORDER
            if window_type.value in present
        ]

    def _toggle_window_type(self, window_type_value: str, checked: bool) -> None:
        types = self.state.setdefault("hidden_window_types", [])
        if checked == (window_type_value in types):
            return
        if checked:
            types.append(window_type_value)
        else:
            types.remove(window_type_value)
        save_state(self.state_path, self.state)
        self.render_snapshots(self._last_snapshots)

    def _quit_app(self) -> None:
        # Qt.Tool 窗口不参与 last-window-closed 退出判定，必须显式退出事件循环
        self.close()
        QApplication.quit()

    def _set_opacity_from_slider(self, value: int) -> None:
        opacity = max(0.3, min(1.0, value / 100.0))
        self.setWindowOpacity(opacity)
        self.state["opacity"] = opacity
        save_state(self.state_path, self.state)

    def _toggle_on_top(self, checked: bool) -> None:
        self.state["always_on_top"] = bool(checked)
        self._apply_window_flags()
        self.show()  # setWindowFlags 后需重新 show 才生效
        save_state(self.state_path, self.state)

    # ---------- 刷新与渲染 ----------

    def _make_card(self, snapshot: QuotaSnapshot) -> AccountCard:
        return AccountCard(
            snapshot,
            warn_percent=float(self.config.get("warn_percent", 30)),
            danger_percent=float(self.config.get("danger_percent", 10)),
            row_layout=dict(self.config.get("row_layout") or {}),
            card_width=int(self.config.get("card_width", 380)),
            hidden_types=self._hidden_types(),
            balance_row_layout=dict(self.config.get("balance_row_layout") or {}),
        )

    def refresh(self) -> None:
        """后台线程采集，完成后渲染（避免网络阻塞 UI）。"""
        if self._providers_error:
            return  # 旧配置格式：只展示迁移提示，不发起采集
        if self._worker is not None and self._worker.isRunning():
            return
        if not self._cards:
            self._status_label.setText("刷新中…")
            self._status_label.setVisible(True)
        worker = RefreshWorker(self.service)
        worker.finished_with_data.connect(self.render_snapshots)
        # 引用保活：不用 deleteLater（会让 C++ 对象先于本引用销毁，下一轮
        # isRunning() 抛 RuntimeError）；已结束的旧 worker 在下一轮被替换时
        # 由 Python 正常回收
        self._worker = worker
        worker.start()

    def refresh_sync(self) -> None:
        """同步采集（供测试与脚本使用）。"""
        self.render_snapshots(self.service.refresh())

    def render_snapshots(self, snapshots) -> None:
        """按 key 原地复用卡片，仅增删变化的卡片（消除刷新闪烁）。"""
        self._last_snapshots = list(snapshots)
        self.setUpdatesEnabled(False)
        try:
            hidden = self._hidden_types()
            existing = {self._card_key(card.snapshot): card for card in self._cards}
            new_cards = []
            for snapshot in snapshots:
                card = existing.pop(self._card_key(snapshot), None)
                if card is None:
                    card = self._make_card(snapshot)
                else:
                    card.hidden_types = hidden
                    card.update_snapshot(snapshot)
                new_cards.append(card)

            if [id(c) for c in self._cards] != [id(c) for c in new_cards]:
                for card in self._cards:
                    self._inner.removeWidget(card)
                for card in new_cards:
                    self._inner.addWidget(card)
            for card in existing.values():
                card.deleteLater()
            self._cards = new_cards
            self._status_label.setVisible(False)
        finally:
            self.setUpdatesEnabled(True)
        # 先同步激活布局，再按布局总最小尺寸锁定窗口；卡片样式 polish 是异步的，
        # 事件循环空闲后再锁定一次终态（期间 Qt 平台层可能打印 setGeometry 噪音，无害）
        self._inner.activate()
        self.layout().activate()
        self._lock_size_to_content()
        QTimer.singleShot(0, self._lock_size_to_content)
        self.snapshots_updated.emit(list(snapshots))

    @staticmethod
    def _card_key(snapshot: QuotaSnapshot) -> str:
        return f"{snapshot.vendor}|{snapshot.account_label}|{snapshot.plan_label}"

    def _lock_size_to_content(self) -> None:
        self._inner.invalidate()
        self.layout().invalidate()
        self.layout().activate()
        size = self.layout().totalMinimumSize()
        if size != self._last_locked_size:
            self._last_locked_size = size
            self.setFixedSize(size)

    # ---------- 持久化 ----------

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        position = self.pos()
        self.state.setdefault("window", {})
        self.state["window"]["x"] = position.x()
        self.state["window"]["y"] = position.y()
        save_state(self.state_path, self.state)
        # 单窗口应用：窗口以任何方式关闭（菜单退出 / Ctrl+C / WM_CLOSE）
        # 都必须结束事件循环，否则 Qt.Tool 窗口会导致进程残留
        QApplication.quit()
        super().closeEvent(event)
