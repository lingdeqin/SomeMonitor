"""系统托盘单元测试（离屏）：状态色分级 / 摘要文本 / 菜单 / 降级。"""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from app.model import ProviderStatus, QuotaSnapshot, QuotaWindow, WindowType
from app.ui.tray import (
    LEVEL_COLORS,
    TrayController,
    aggregate_level,
    make_icon,
    tooltip_text,
)


def _snapshot(vendor, windows, status=ProviderStatus.OK, error=None):
    return QuotaSnapshot(
        vendor=vendor,
        account_label="默认",
        status=status,
        error=error,
        windows=windows,
    )


def _window(percent, window_type=WindowType.WEEKLY):
    return QuotaWindow(type=window_type, percent=percent)


def test_aggregate_level_grading():
    # remaining = 100 - percent：50/80 剩余 -> ok；20 剩余 -> warn；2 剩余 -> danger
    ok = [_snapshot("glm", [_window(50)]), _snapshot("kimi", [_window(20)])]
    assert aggregate_level(ok, warn_percent=30, danger_percent=10) == "ok"
    warn = [_snapshot("glm", [_window(50)]), _snapshot("kimi", [_window(80)])]
    assert aggregate_level(warn, warn_percent=30, danger_percent=10) == "warn"
    danger = [_snapshot("glm", [_window(98)])]
    assert aggregate_level(danger, warn_percent=30, danger_percent=10) == "danger"


def test_aggregate_level_no_data_is_none():
    assert aggregate_level([]) == "none"
    empty = [_snapshot("glm", []), _snapshot("kimi", [_window(None)])]
    assert aggregate_level(empty) == "none"


def test_aggregate_level_frozen_counts_as_danger():
    frozen = QuotaWindow(type=WindowType.MONTHLY_FREEZE, frozen=True)
    snapshots = [_snapshot("kimi", [frozen])]
    assert aggregate_level(snapshots, warn_percent=30, danger_percent=10) == "danger"


def test_aggregate_level_ignores_balance_only_cards():
    # 余额型卡片（无窗口）不参与托盘告警分级：混合时以窗口卡为准
    from app.model import BalanceInfo

    snapshot = _snapshot("deepseek", [])
    snapshot.balance = BalanceInfo(currency="CNY", total=110.0, today_spent=5.0)
    assert aggregate_level([snapshot]) == "none"
    mixed = [snapshot, _snapshot("glm", [_window(95)])]
    assert aggregate_level(mixed, warn_percent=30, danger_percent=10) == "danger"


def test_tooltip_lists_each_card():
    snapshots = [
        _snapshot("glm", [_window(80)]),
        _snapshot("kimi", [_window(95)]),
    ]
    text = tooltip_text(snapshots)
    assert "智谱 GLM：最紧剩余 20%" in text
    assert "Kimi：最紧剩余 5%" in text


def test_tooltip_error_and_empty_states():
    failed = _snapshot("glm", [], status=ProviderStatus.ERROR, error="HTTP 500")
    assert tooltip_text([failed]) == "智谱 GLM：获取失败"
    no_data = _snapshot("kimi", [])
    assert tooltip_text([no_data]) == "Kimi：暂无额度数据"


def test_tooltip_truncated_beyond_six_lines():
    snapshots = [_snapshot("glm", [_window(50 + i)]) for i in range(8)]
    lines = tooltip_text(snapshots).splitlines()
    assert len(lines) == 7  # 6 行 + 省略号
    assert lines[-1] == "…"


def test_make_icon_has_all_levels(qapp):
    for level in LEVEL_COLORS:
        assert not make_icon(level).isNull()


def test_tray_menu_contains_actions(qapp, tmp_path):
    from app.ui.window import MainWindow

    window = MainWindow({}, {}, str(tmp_path / "state.json"), _NoopService())
    controller = TrayController(window, {})
    menu = controller._build_menu()
    texts = [action.text() for action in menu.actions()]
    assert "显示悬浮窗" in texts
    assert "立即刷新" in texts
    assert "退出" in texts
    menu.deleteLater()


def test_tray_update_before_start_is_noop(qapp, tmp_path):
    from app.ui.window import MainWindow

    window = MainWindow({}, {}, str(tmp_path / "state.json"), _NoopService())
    controller = TrayController(window, {})
    controller.update([_snapshot("glm", [_window(80)])])  # 未 start，不抛异常
    window.close()
    QApplication.processEvents()


def test_tray_toggle_window_visibility(qapp, tmp_path):
    from app.ui.window import MainWindow

    window = MainWindow({}, {}, str(tmp_path / "state.json"), _NoopService())
    window.show()
    controller = TrayController(window, {})
    controller._toggle_window()
    assert window.isVisible() is False
    assert controller._toggle_action is None  # 未构建菜单时同步文本安全跳过
    controller._toggle_window()
    assert window.isVisible() is True
    window.close()
    QApplication.processEvents()


class _NoopService:
    def refresh(self):
        return []
