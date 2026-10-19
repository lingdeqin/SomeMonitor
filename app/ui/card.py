"""厂商账号卡片渲染：每账号一卡，单行窗口行 + 分级警示色 + 原地更新。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from app.model import ProviderStatus, QuotaSnapshot, QuotaWindow, WindowType, window_label

VENDOR_NAMES = {
    "opencode-go": "OpenCode Go",
    "ark": "火山方舟",
    "glm": "智谱 GLM",
    "kimi": "Kimi",
}

WINDOW_ORDER = [
    WindowType.FIVE_H,
    WindowType.SESSION,
    WindowType.WEEKLY,
    WindowType.MONTHLY,
    WindowType.MONTHLY_FREEZE,
]

DEFAULT_CARD_WIDTH = 380
DEFAULT_ROW_LAYOUT = {
    "name_width": 52,
    "percent_width": 48,
    "usage_width": 88,
    "reset_width": 104,
}


def fmt_decimal(value: float) -> str:
    """最多保留两位小数并去掉尾随零：91.5607 -> 91.56，6.10 -> 6.1，100.0 -> 100。"""
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text or "0"


def fmt_number(value: float) -> str:
    if value >= 1000:
        return f"{value:,.0f}"
    return fmt_decimal(value)


def _percent_text(window: QuotaWindow) -> str:
    if window.percent is not None:
        return fmt_decimal(window.percent) + "%"
    return "—"


def _usage_text(window: QuotaWindow) -> str:
    if window.used is not None and window.total is not None:
        return f"{fmt_number(window.used)}/{fmt_number(window.total)}"
    return ""


def _reset_text(window: QuotaWindow, now: Optional[datetime] = None) -> str:
    return format_reset_countdown(
        window.reset_at, now or datetime.now(timezone.utc)
    )


def format_reset_countdown(reset_at, now: datetime) -> str:
    """距重置的相对倒计时文案；不足 1 天按「H小时M分」，满 1 天按「D天H小时」。"""
    if reset_at is None:
        return ""
    delta = reset_at - now
    total_seconds = delta.total_seconds()
    if total_seconds < 60:  # 已到期或不足一分钟
        return "即将重置"
    total_minutes = int(total_seconds // 60)
    days, remainder = divmod(total_minutes, 1440)
    hours, minutes = divmod(remainder, 60)
    if days >= 1:
        return f"{days}天{hours}小时后重置"
    if hours >= 1:
        return f"{hours}小时{minutes}分后重置"
    return f"{minutes}分后重置"


def _repolish(widget: QWidget) -> None:
    # QSS 不会随 objectName 变化自动重算，需手动刷新
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class WindowRow(QWidget):
    """单行额度窗口：[类型名][进度条][百分比][已用/总量][重置时间]。

    首尾各段固定宽度保证多行进度条等长；字段缺失时对应段为空占位，
    不破坏对齐。
    """

    def __init__(
        self,
        window: QuotaWindow,
        warn_percent: float = 30.0,
        danger_percent: float = 10.0,
        layout_cfg: Optional[dict] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.warn_percent = warn_percent
        self.danger_percent = danger_percent
        cfg = {**DEFAULT_ROW_LAYOUT, **(layout_cfg or {})}

        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(6)

        self.name_label = QLabel(self)
        self.name_label.setFixedWidth(int(cfg["name_width"]))
        hbox.addWidget(self.name_label)

        self.bar = QProgressBar(self)
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)
        self.bar.setMinimumWidth(32)
        hbox.addWidget(self.bar, 1)

        self.percent_label = QLabel(self)
        self.percent_label.setFixedWidth(int(cfg["percent_width"]))
        self.percent_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hbox.addWidget(self.percent_label)

        self.usage_label = QLabel(self)
        self.usage_label.setFixedWidth(int(cfg["usage_width"]))
        self.usage_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hbox.addWidget(self.usage_label)

        self.reset_label = QLabel(self)
        self.reset_label.setFixedWidth(int(cfg["reset_width"]))
        self.reset_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hbox.addWidget(self.reset_label)

        self.window: Optional[QuotaWindow] = None
        self.update_window(window)

    def update_window(self, window: QuotaWindow) -> None:
        self.window = window
        self.name_label.setText(window_label(window.type))
        self.bar.setValue(int(window.percent) if window.percent is not None else 0)
        self._apply_warn_color(window)
        self.percent_label.setText(_percent_text(window))
        self.usage_label.setText(_usage_text(window))
        self.reset_label.setText(_reset_text(window))

    def _apply_warn_color(self, window: QuotaWindow) -> None:
        object_name = ""
        remaining = window.remaining_percent
        if remaining is not None:
            if remaining <= self.danger_percent:
                object_name = "dangerBar"
            elif remaining <= self.warn_percent:
                object_name = "warnBar"
        if self.bar.objectName() != object_name:
            self.bar.setObjectName(object_name)
            _repolish(self.bar)


class FreezeRow(QWidget):
    """月度额度冻结徽章行：[月度额度][已冻结/正常]。"""

    def __init__(
        self,
        window: QuotaWindow,
        layout_cfg: Optional[dict] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        cfg = {**DEFAULT_ROW_LAYOUT, **(layout_cfg or {})}
        hbox = QHBoxLayout(self)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(6)

        self.name_label = QLabel(self)
        self.name_label.setFixedWidth(int(cfg["name_width"]))
        self.badge_label = QLabel(self)
        hbox.addWidget(self.name_label)
        hbox.addWidget(self.badge_label)
        hbox.addStretch(1)

        self.window: Optional[QuotaWindow] = None
        self.update_window(window)

    def update_window(self, window: QuotaWindow) -> None:
        self.window = window
        self.name_label.setText(window_label(window.type))
        frozen = bool(window.frozen)
        object_name = "frozenBadge" if frozen else "okBadge"
        if self.badge_label.objectName() != object_name:
            self.badge_label.setObjectName(object_name)
            _repolish(self.badge_label)
        self.badge_label.setText("已冻结" if frozen else "正常")


class AccountCard(QFrame):
    """单个账号（或计划）的额度卡片。

    骨架（标题 + 内容布局）一次建成；`update_snapshot` 原地复用窗口行
    与标签控件，仅按需增删，避免整卡销毁重建。
    """

    def __init__(
        self,
        snapshot: QuotaSnapshot,
        warn_percent: float = 30.0,
        danger_percent: float = 10.0,
        row_layout: Optional[dict] = None,
        card_width: int = DEFAULT_CARD_WIDTH,
        hidden_types: Optional[set] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.warn_percent = warn_percent
        self.danger_percent = danger_percent
        self._layout_cfg = {**DEFAULT_ROW_LAYOUT, **(row_layout or {})}
        self.hidden_types = set(hidden_types or ())
        self.setObjectName("accountCard")
        self.setFixedWidth(int(card_width))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(4)

        self._title_label = QLabel(self)
        self._title_label.setObjectName("cardTitle")
        self._title_label.setWordWrap(True)
        layout.addWidget(self._title_label)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(2)
        layout.addLayout(self._body)

        self._rows = {}
        self._special_label = None
        self._info_labels = []
        self.snapshot: Optional[QuotaSnapshot] = None
        self.update_snapshot(snapshot)

    def update_snapshot(self, snapshot: QuotaSnapshot) -> None:
        self.snapshot = snapshot
        self._title_label.setText(self._title_text())

        if snapshot.status == ProviderStatus.UNCONFIGURED:
            self._clear_rows()
            self._special_label = self._set_special(
                "未配置：在 config.jsonc 填入 API Key，或设置环境变量 / 登录对应 CLI"
            )
            self._set_info([])
            self._sync_body_order()
            return

        if snapshot.status == ProviderStatus.ERROR and not snapshot.windows:
            self._clear_rows()
            self._special_label = self._set_special(
                f"获取失败：{snapshot.error or '未知错误'}", "errorText"
            )
            self._set_info([])
            self._sync_body_order()
            return

        self._special_label = self._set_special(None)
        ordered = self._ordered_windows()
        row_widgets = self._sync_rows(ordered)
        if not ordered and snapshot.status == ProviderStatus.OK:
            self._special_label = self._set_special("未订阅")
        info_entries = []
        if snapshot.stale:
            since = snapshot.stale_since
            stamp = since.strftime("%H:%M") if since is not None else ""
            info_entries.append((f"获取失败 {stamp}，显示旧数据", "staleText"))
        for text in snapshot.notes:
            info_entries.append((text, "muted"))
        self._set_info(info_entries)
        self._sync_body_order(row_widgets)

    # ---------- 文案 ----------

    def _title_text(self) -> str:
        snapshot = self.snapshot
        name = VENDOR_NAMES.get(snapshot.vendor, snapshot.vendor)
        if snapshot.account_label and snapshot.account_label != "默认":
            name = f"{name} · {snapshot.account_label}"
        if snapshot.plan_label:
            name += f"（{snapshot.plan_label}）"
        return name

    # ---------- 结构同步 ----------

    def _ordered_windows(self) -> list:
        return [
            window
            for window in sorted(
                self.snapshot.windows,
                key=lambda w: WINDOW_ORDER.index(w.type)
                if w.type in WINDOW_ORDER
                else 99,
            )
            if window.type.value not in self.hidden_types
        ]

    def _make_row(self, window: QuotaWindow) -> QWidget:
        if window.type == WindowType.MONTHLY_FREEZE:
            return FreezeRow(window, self._layout_cfg, parent=self)
        return WindowRow(
            window,
            self.warn_percent,
            self.danger_percent,
            self._layout_cfg,
            parent=self,
        )

    def _sync_rows(self, ordered: list) -> list:
        wanted = {window.type.value for window in ordered}
        for key in list(self._rows):
            if key not in wanted:
                row = self._rows.pop(key)
                self._body.removeWidget(row)  # 先出布局再销毁，最小尺寸即时收缩
                row.deleteLater()
        rows = []
        for window in ordered:
            key = window.type.value
            row = self._rows.get(key)
            if row is None:
                row = self._make_row(window)
                self._rows[key] = row
            elif row not in rows:
                row.update_window(window)
            if row not in rows:
                rows.append(row)
        return rows

    def _clear_rows(self) -> None:
        for row in self._rows.values():
            self._body.removeWidget(row)
            row.deleteLater()
        self._rows = {}

    def _set_special(self, text, object_name: str = "muted"):
        """维护唯一的特殊状态标签（未配置 / 获取失败 / 未订阅）；text 为 None 时移除。"""
        if text is None:
            if self._special_label is not None:
                self._body.removeWidget(self._special_label)
                self._special_label.deleteLater()
            return None
        label = self._special_label
        if label is None:
            label = QLabel(self)
            label.setWordWrap(True)
        if label.objectName() != object_name:
            label.setObjectName(object_name)
            _repolish(label)
        label.setText(text)
        return label

    def _set_info(self, entries: list) -> None:
        while len(self._info_labels) > len(entries):
            label = self._info_labels.pop()
            self._body.removeWidget(label)
            label.deleteLater()
        while len(self._info_labels) < len(entries):
            label = QLabel(self)
            label.setWordWrap(True)
            self._info_labels.append(label)
        for label, (text, object_name) in zip(self._info_labels, entries):
            if label.objectName() != object_name:
                label.setObjectName(object_name)
                _repolish(label)
            if label.text() != text:
                label.setText(text)

    def _sync_body_order(self, row_widgets: Optional[list] = None) -> None:
        """按「窗口行 -> 特殊标签 -> 附加信息行」顺序重排；仅顺序变化时移动。"""
        widgets = list(row_widgets or [])
        if self._special_label is not None:
            widgets.append(self._special_label)
        widgets.extend(self._info_labels)
        current = [self._body.itemAt(i).widget() for i in range(self._body.count())]
        if current != widgets:
            for widget in widgets:
                self._body.removeWidget(widget)
            for widget in widgets:
                self._body.addWidget(widget)
        # QLayout 缓存逐层独立：行增删后需失效自身并通知父级，否则上层拿到陈旧最小尺寸
        self.layout().invalidate()
        self.updateGeometry()
