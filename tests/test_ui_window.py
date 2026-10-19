"""主悬浮窗单元测试（离屏）：拖拽 / 不透明度 / 置顶开关 / 菜单 / 位置记忆。"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QLabel

from app.config import load_state
from app.model import QuotaSnapshot
from app.ui.window import MainWindow


class DummyService:
    def refresh(self):
        return [
            QuotaSnapshot(vendor="kimi", account_label="默认", windows=[]),
        ]


class ExplodingService:
    """迁移提示场景下绝不应被调用。"""

    def refresh(self):
        raise AssertionError("旧配置格式下不应发起采集")


def _make_window(tmp_path, config=None, state=None):
    state_path = tmp_path / "state.json"
    window = MainWindow(config or {}, state or {}, str(state_path), DummyService())
    window.show()
    QApplication.processEvents()
    return window


def _mouse(event_type, local, glob, button, buttons):
    return QMouseEvent(
        event_type, QPointF(local), QPointF(glob), button, buttons, Qt.NoModifier
    )


def test_window_flags_frameless_and_on_top(qapp, tmp_path):
    window = _make_window(tmp_path)
    flags = window.windowFlags()
    assert flags & Qt.FramelessWindowHint
    assert flags & Qt.WindowStaysOnTopHint
    # Qt 将不透明度量化为 8-bit（229/255），用容差比较
    assert abs(window.windowOpacity() - 0.9) < 0.01


def test_drag_moves_window(qapp, tmp_path):
    window = _make_window(tmp_path)
    window.move(QPoint(50, 60))
    QApplication.processEvents()
    # 按下：全局 (100,160) - 窗口左上 (50,60) = 偏移 (50,100)
    window.mousePressEvent(
        _mouse(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(100, 160),
               Qt.LeftButton, Qt.LeftButton)
    )
    # 移动到全局 (220,260) -> 新位置 (170,160)
    window.mouseMoveEvent(
        _mouse(QEvent.MouseMove, QPointF(10, 5), QPointF(220, 260),
               Qt.NoButton, Qt.LeftButton)
    )
    assert window.pos() == QPoint(170, 160)
    window.mouseReleaseEvent(
        _mouse(QEvent.MouseButtonRelease, QPointF(10, 5), QPointF(220, 260),
               Qt.LeftButton, Qt.NoButton)
    )


def test_opacity_slider_persists_to_state(qapp, tmp_path):
    state_path = tmp_path / "state.json"
    window = _make_window(tmp_path, config={})
    window._set_opacity_from_slider(80)
    assert abs(window.windowOpacity() - 0.8) < 0.01
    window._set_opacity_from_slider(20)  # 低于下限 -> 钳制到 0.3（8-bit 量化，容差比较）
    assert abs(window.windowOpacity() - 0.3) < 0.01
    assert load_state(state_path)["opacity"] == 0.3


def test_state_overrides_config(qapp, tmp_path):
    window = _make_window(
        tmp_path,
        config={"opacity": 0.9, "always_on_top": True},
        state={"opacity": 0.5, "always_on_top": False},
    )
    assert abs(window.windowOpacity() - 0.5) < 0.01
    assert not (window.windowFlags() & Qt.WindowStaysOnTopHint)


def test_on_top_toggle_persists_to_state(qapp, tmp_path):
    state_path = tmp_path / "state.json"
    window = _make_window(tmp_path, config={})
    window._toggle_on_top(False)
    assert window.state["always_on_top"] is False
    assert not (window.windowFlags() & Qt.WindowStaysOnTopHint)
    window._toggle_on_top(True)
    assert window.windowFlags() & Qt.WindowStaysOnTopHint
    assert load_state(state_path)["always_on_top"] is True


def test_menu_contains_chinese_actions(qapp, tmp_path):
    window = _make_window(tmp_path)
    menu, refresh_action, quit_action = window._build_menu()
    texts = [action.text() for action in menu.actions()]
    assert "立即刷新" in texts
    assert "退出" in texts
    assert any("不透明度" in text for text in texts)
    assert any("置顶" in text for text in texts)
    assert refresh_action.text() == "立即刷新"
    assert quit_action.text() == "退出"
    menu.deleteLater()


def test_position_persisted_to_state_on_close(qapp, tmp_path):
    state_path = tmp_path / "state.json"
    window = _make_window(tmp_path, config={})
    window.move(QPoint(123, 45))
    window.close()
    QApplication.processEvents()
    state = load_state(state_path)
    assert state["window"]["x"] == 123
    assert state["window"]["y"] == 45


def test_position_restored_from_state(qapp, tmp_path):
    state = {"window": {"x": 77, "y": 88}, "opacity": None, "always_on_top": None}
    window = _make_window(tmp_path, config={}, state=state)
    assert window.pos() == QPoint(77, 88)


def test_legacy_providers_dict_shows_migration_hint(qapp, tmp_path):
    # 旧 dict 配置：显示迁移提示、不发起采集、不显示「加载中」
    from PySide6.QtWidgets import QApplication

    config = {"providers": {"ark": {"transport": "auto"}, "kimi": {"accounts": []}}}
    state_path = tmp_path / "state.json"
    window = MainWindow(config, {}, str(state_path), ExplodingService())
    window.show()
    QApplication.processEvents()
    assert window._status_label.isVisible() is True
    assert "数组" in window._status_label.text()
    assert "加载中" not in window._status_label.text()
    window.refresh()  # 不应触发 ExplodingService
    assert window._worker is None
    assert window._cards == []


def test_hide_window_type_toggle_global_and_persistent(qapp, tmp_path):
    from app.model import QuotaWindow, WindowType

    class TwoVendorService:
        def refresh(self):
            return [
                QuotaSnapshot(
                    vendor="glm",
                    account_label="默认",
                    windows=[
                        QuotaWindow(type=WindowType.WEEKLY, percent=50),
                        QuotaWindow(type=WindowType.MONTHLY, percent=70),
                    ],
                ),
                QuotaSnapshot(
                    vendor="kimi",
                    account_label="主号",
                    windows=[
                        QuotaWindow(type=WindowType.WEEKLY, percent=20),
                        QuotaWindow(type=WindowType.MONTHLY, percent=80),
                    ],
                ),
            ]

    state_path = tmp_path / "state.json"
    window = MainWindow({}, {}, str(state_path), TwoVendorService())
    window.refresh_sync()
    assert all(set(c._rows) == {"weekly", "monthly"} for c in window._cards)

    # 菜单仅含当前数据出现的窗口类型开关；未出现的类型（如 5 小时）不出
    menu, refresh_action, quit_action = window._build_menu()
    texts = [action.text() for action in menu.actions()]
    assert "隐藏本周" in texts
    assert "隐藏本月" in texts
    assert not any("小时" in text for text in texts)

    # 勾选「隐藏本月」-> 两张卡片的本月行都消失（按类型全局生效）
    window._toggle_window_type("monthly", True)
    assert load_state(state_path)["hidden_window_types"] == ["monthly"]
    assert all(set(c._rows) == {"weekly"} for c in window._cards)

    # 菜单勾选状态与隐藏状态一致
    menu2, _, _ = window._build_menu()
    checked = {
        action.text(): action.isChecked()
        for action in menu2.actions()
        if action.isCheckable()
    }
    assert checked["隐藏本月"] is True
    assert checked["隐藏本周"] is False

    # 重启（重新构造窗口）后隐藏状态保持
    restarted = MainWindow(
        {}, load_state(state_path), str(state_path), TwoVendorService()
    )
    restarted.refresh_sync()
    assert all(set(c._rows) == {"weekly"} for c in restarted._cards)

    # 取消勾选 -> 恢复显示
    restarted._toggle_window_type("monthly", False)
    assert all(set(c._rows) == {"weekly", "monthly"} for c in restarted._cards)
    assert load_state(state_path)["hidden_window_types"] == []
    menu.deleteLater()
    menu2.deleteLater()


def test_menu_hidden_toggles_absent_without_window_data(qapp, tmp_path):
    # 数据无任何额度窗口 -> 菜单不出现「隐藏X」开关
    window = _make_window(tmp_path, config={})  # DummyService 返回空窗口快照
    window.refresh_sync()
    menu, _, _ = window._build_menu()
    assert not any("隐藏" in action.text() for action in menu.actions())
    menu.deleteLater()


def test_render_reuses_cards_across_refresh(qapp, tmp_path):
    # 刷新稳定性：同数据两轮渲染复用同一卡片实例，不销毁重建
    window = _make_window(tmp_path, config={})
    snapshots = [QuotaSnapshot(vendor="kimi", account_label="默认", windows=[])]
    window.render_snapshots(snapshots)
    first_card = window._cards[0]

    window.render_snapshots([QuotaSnapshot(vendor="kimi", account_label="默认", windows=[])])
    assert window._cards[0] is first_card

    # 增删卡片时其余卡片不重建
    snapshot_glm = QuotaSnapshot(vendor="glm", account_label="默认", windows=[])
    window.render_snapshots([snapshot_glm, snapshots[0]])
    assert window._cards[1] is first_card
    window.render_snapshots([snapshots[0]])
    assert window._cards == [first_card]


def test_lock_size_guard_skips_unchanged_size(qapp, tmp_path):
    window = _make_window(tmp_path, config={})
    window.render_snapshots(
        [QuotaSnapshot(vendor="kimi", account_label="默认", windows=[])]
    )
    locked = window._last_locked_size
    assert locked is not None
    calls = []
    original = window.setFixedSize

    def counting_setFixedSize(*args):
        calls.append(args)
        original(*args)

    window.setFixedSize = counting_setFixedSize
    window._lock_size_to_content()  # 尺寸未变 -> 不再 setFixedSize
    assert calls == []


def test_render_snapshots_builds_cards(qapp, tmp_path):
    from app.model import ProviderStatus

    window = _make_window(tmp_path, config={})
    snapshots = [
        QuotaSnapshot(vendor="kimi", account_label="默认", windows=[]),
        QuotaSnapshot(vendor="ark", account_label="主号", plan_label="Coding Plan"),
        QuotaSnapshot(vendor="glm", account_label="默认",
                      status=ProviderStatus.UNCONFIGURED),
    ]
    window.render_snapshots(snapshots)
    assert len(window._cards) == 3
    assert window._status_label.isVisible() is False


def test_render_locks_size_to_content(qapp, tmp_path):
    # setFixedSize 消除 setGeometry 告警：请求几何 == 布局最小尺寸
    window = _make_window(tmp_path, config={})
    window.render_snapshots(
        [QuotaSnapshot(vendor="kimi", account_label="默认", windows=[])]
    )
    assert window.minimumWidth() == window.maximumWidth()
    assert window.minimumHeight() == window.maximumHeight()
    assert window.size() == window.layout().totalMinimumSize()


def test_refresh_sync_renders(qapp, tmp_path):
    window = _make_window(tmp_path, config={})
    window.refresh_sync()
    assert len(window._cards) == 1
    label_texts = [l.text() for l in window.findChildren(QLabel)]
    assert any("Kimi" in text for text in label_texts)


def test_refresh_repeated_after_worker_finishes(qapp, tmp_path):
    # 回归：deleteLater 曾导致 C++ 对象先于引用销毁，第二轮 refresh 抛
    # "Internal C++ object (RefreshWorker) already deleted"
    window = _make_window(tmp_path, config={})
    window.refresh()
    assert window._worker is not None
    window._worker.wait(5000)
    QApplication.processEvents()
    assert len(window._cards) == 1
    window.refresh()  # 不应抛 RuntimeError
    window._worker.wait(5000)
    QApplication.processEvents()
    assert len(window._cards) == 1
    assert window._worker.isRunning() is False


def test_refresh_skipped_while_worker_running(qapp, tmp_path):
    import time

    class SlowService:
        def refresh(self):
            time.sleep(0.3)
            return []

    state_path = tmp_path / "state.json"
    window = MainWindow({}, {}, str(state_path), SlowService())
    window.show()
    QApplication.processEvents()
    window.refresh()
    first_worker = window._worker
    window.refresh()  # 运行中 -> 跳过，不新建 worker
    assert window._worker is first_worker
    first_worker.wait(5000)
    QApplication.processEvents()


def test_quit_app_closes_and_quits(qapp, tmp_path, monkeypatch):
    # 回归：Qt.Tool 窗口不触发 last-window-closed 退出，必须显式 QApplication.quit()
    import app.ui.window as window_module

    state_path = tmp_path / "state.json"
    quit_calls = []

    class _FakeQApplication:
        @staticmethod
        def quit():
            quit_calls.append(1)

    monkeypatch.setattr(window_module, "QApplication", _FakeQApplication)
    window = _make_window(tmp_path, config={})
    window.move(QPoint(9, 19))
    window._quit_app()
    # _quit_app 显式 quit 一次，closeEvent 内再 quit 一次（幂等）
    assert len(quit_calls) >= 1
    state = load_state(state_path)
    assert state["window"]["x"] == 9
    assert state["window"]["y"] == 19
