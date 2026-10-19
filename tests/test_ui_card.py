"""卡片渲染单元测试（离屏）：结构 / 警示色 / 冻结徽标 / 截图。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtWidgets import QLabel, QProgressBar

from app.model import (
    ProviderStatus,
    QuotaSnapshot,
    QuotaWindow,
    WindowType,
)
from app.ui.card import AccountCard, format_reset_countdown


def _snapshot(vendor, windows, status=ProviderStatus.OK, plan_label="", error=None):
    return QuotaSnapshot(
        vendor=vendor,
        account_label="默认",
        plan_label=plan_label,
        status=status,
        error=error,
        windows=windows,
    )


def test_card_renders_window_rows(qapp, tmp_path):
    windows = [
        QuotaWindow(type=WindowType.FIVE_H, used=4.2, total=12),      # 35%
        QuotaWindow(type=WindowType.WEEKLY, used=28.5, total=30),     # 95% -> 红
        QuotaWindow(type=WindowType.MONTHLY, used=21, total=30),      # 70% -> 黄(剩余30)
    ]
    for w in windows:
        w.ensure_derived()
    card = AccountCard(_snapshot("opencode-go", windows))
    card.show()
    bars = card.findChildren(QProgressBar)
    assert len(bars) == 3
    object_names = {bar.objectName() for bar in bars}
    assert "dangerBar" in object_names
    assert "warnBar" in object_names
    # 截图证据
    out = tmp_path / "card_opencode.png"
    assert card.grab().save(str(out))
    assert out.exists() and out.stat().st_size > 0


def test_card_percent_only_window(qapp):
    windows = [
        QuotaWindow(type=WindowType.SESSION, percent=42),
        QuotaWindow(type=WindowType.WEEKLY, percent=71),
    ]
    card = AccountCard(_snapshot("ark", windows, plan_label="Coding Plan · 个人版"))
    card.show()
    bars = card.findChildren(QProgressBar)
    assert [bar.value() for bar in bars] == [42, 71]
    assert card.findChild(QLabel).text().startswith("火山方舟")


def test_card_kimi_monthly_freeze_badge(qapp, tmp_path):
    weekly = QuotaWindow(type=WindowType.WEEKLY, used=60, total=100)
    weekly.ensure_derived()
    freeze = QuotaWindow(type=WindowType.MONTHLY_FREEZE, frozen=True)
    card = AccountCard(_snapshot("kimi", [weekly, freeze], plan_label="PRO"))
    card.show()
    bars = card.findChildren(QProgressBar)
    assert len(bars) == 1  # 冻结信号不画进度条
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert "已冻结" in labels
    out = tmp_path / "card_kimi.png"
    assert card.grab().save(str(out))


def test_card_unconfigured_state(qapp):
    card = AccountCard(_snapshot("glm", [], status=ProviderStatus.UNCONFIGURED))
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("未配置" in text for text in labels)
    assert card.findChildren(QProgressBar) == []


def test_card_error_without_windows(qapp):
    card = AccountCard(
        _snapshot("glm", [], status=ProviderStatus.ERROR, error="HTTP 500")
    )
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("获取失败" in text for text in labels)


def test_card_unsubscribed_state(qapp):
    card = AccountCard(_snapshot("ark", []))
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("未订阅" in text for text in labels)


def test_card_renders_notes(qapp):
    snapshot = _snapshot("kimi", [])
    snapshot.notes.append("月度会员额度获取失败：Cookie 可能已过期，请重新复制 kimi-auth")
    card = AccountCard(snapshot)
    card.show()
    texts = [l.text() for l in card.findChildren(QLabel)]
    assert any("月度会员额度获取失败" in t for t in texts)


def test_card_stale_annotation(qapp):
    window = QuotaWindow(type=WindowType.FIVE_H, used=1, total=10)
    window.ensure_derived()
    snapshot = _snapshot("kimi", [window])
    snapshot.stale = True
    snapshot.stale_error = "timeout"
    snapshot.stale_since = datetime(2026, 10, 14, 10, 30, tzinfo=timezone.utc)
    card = AccountCard(snapshot)
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("显示旧数据" in text for text in labels)


def test_card_reset_time_rendered_local(qapp):
    window = QuotaWindow(
        type=WindowType.WEEKLY,
        used=1,
        total=10,
        reset_at=datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc),
    )
    window.ensure_derived()
    card = AccountCard(_snapshot("opencode-go", [window]))
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("重置" in text for text in labels)


NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=timezone.utc)


def test_reset_countdown_hours_minutes():
    # 17 小时 32 分后 -> 「17小时32分后重置」（用户示例）（用户示例）
    reset_at = NOW + timedelta(hours=17, minutes=32, seconds=59)
    assert format_reset_countdown(reset_at, NOW) == "17小时32分后重置"


def test_reset_countdown_days_hours():
    reset_at = NOW + timedelta(days=3, hours=5, minutes=1)
    assert format_reset_countdown(reset_at, NOW) == "3天5小时后重置"


def test_reset_countdown_boundaries():
    # 恰好 1 天 / 恰好 1 小时 / 不足 1 小时 / 不足 1 分钟 / 已过期
    assert format_reset_countdown(NOW + timedelta(days=1), NOW) == "1天0小时后重置"
    assert format_reset_countdown(NOW + timedelta(hours=1), NOW) == "1小时0分后重置"
    assert format_reset_countdown(NOW + timedelta(minutes=45), NOW) == "45分后重置"
    assert format_reset_countdown(NOW + timedelta(seconds=30), NOW) == "即将重置"
    assert format_reset_countdown(NOW - timedelta(minutes=5), NOW) == "即将重置"
    assert format_reset_countdown(None, NOW) == ""


def test_reset_countdown_used_in_row(qapp):
    window = QuotaWindow(
        type=WindowType.MONTHLY,
        percent=70,
        reset_at=datetime.now(timezone.utc)
        + timedelta(hours=2, minutes=10, seconds=30),
    )
    card = AccountCard(_snapshot("glm", [window]))
    row = card._rows["monthly"]
    assert row.reset_label.text() == "2小时10分后重置"


def test_card_percent_at_most_two_decimals(qapp):
    windows = [
        QuotaWindow(type=WindowType.WEEKLY, percent=95.016),
        QuotaWindow(type=WindowType.MONTHLY, percent=6.1),
        QuotaWindow(type=WindowType.FIVE_H, percent=100.0),
    ]
    card = AccountCard(_snapshot("opencode-go", windows))
    card.show()
    texts = [l.text() for l in card.findChildren(QLabel)]
    assert any("95.02%" in text for text in texts)
    assert any("6.1%" in text for text in texts)
    assert any("100%" in text for text in texts)


def test_bars_equal_length_with_and_without_reset(qapp):
    # 回归：GLM 5h 窗口无重置时间，此前文字长度差异会挤压进度条导致长短不一
    windows = [
        QuotaWindow(type=WindowType.FIVE_H, percent=0),  # 无 used/total/重置
        QuotaWindow(
            type=WindowType.WEEKLY,
            percent=69.2,
            used=6920,
            total=10000,
            reset_at=datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc),
        ),
    ]
    card = AccountCard(_snapshot("glm", windows))
    card.show()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    card.layout().activate()
    bars = card.findChildren(QProgressBar)
    assert len(bars) == 2
    assert bars[0].width() == bars[1].width()
    assert bars[0].width() > 0
    texts = [l.text() for l in card.findChildren(QLabel)]
    assert any("69.2%" in t for t in texts)          # 百分比在首行
    assert any("重置" in t for t in texts)            # 重置时间在第二行


def test_window_row_single_line_segments(qapp):
    # 单行布局：[类型名][进度条][百分比][已用/总量][重置倒计时]
    window = QuotaWindow(
        type=WindowType.MONTHLY,
        percent=70,
        used=21,
        total=30,
        reset_at=datetime.now(timezone.utc)
        + timedelta(hours=2, minutes=30, seconds=30),
    )
    card = AccountCard(_snapshot("glm", [window]))
    row = card._rows["monthly"]
    assert row.name_label.text() == "本月"
    assert row.percent_label.text() == "70%"
    assert row.usage_label.text() == "21/30"
    assert row.reset_label.text() == "2小时30分后重置"
    assert row.bar.value() == 70


def test_row_layout_widths_applied(qapp):
    row_layout = {
        "name_width": 70,
        "percent_width": 60,
        "usage_width": 100,
        "reset_width": 120,
    }
    window = QuotaWindow(type=WindowType.WEEKLY, percent=50)
    card = AccountCard(_snapshot("kimi", [window]), row_layout=row_layout)
    row = card._rows["weekly"]
    assert row.name_label.width() == 70
    assert row.percent_label.width() == 60
    assert row.usage_label.width() == 100
    assert row.reset_label.width() == 120


def test_card_width_applied(qapp):
    window = QuotaWindow(type=WindowType.WEEKLY, percent=50)
    default_card = AccountCard(_snapshot("kimi", [window]))
    assert default_card.maximumWidth() == 380
    wide_card = AccountCard(_snapshot("kimi", [window]), card_width=460)
    assert wide_card.maximumWidth() == 460


def test_missing_fields_keep_empty_placeholders(qapp):
    # 仅百分比形态（ark Coding Plan）：用量/重置段为空占位，不显示 0
    windows = [
        QuotaWindow(type=WindowType.FIVE_H, percent=42,
                    reset_at=datetime.now(timezone.utc)
                    + timedelta(hours=5, seconds=30)),
        QuotaWindow(type=WindowType.MONTHLY, percent=71),
    ]
    card = AccountCard(_snapshot("ark", windows, plan_label="Coding Plan"))
    five_h = card._rows["5h"]
    assert five_h.percent_label.text() == "42%"
    assert five_h.usage_label.text() == ""
    assert five_h.reset_label.text() == "5小时0分后重置"
    monthly = card._rows["monthly"]
    assert monthly.percent_label.text() == "71%"
    assert monthly.usage_label.text() == ""
    assert monthly.reset_label.text() == ""


def test_hidden_types_filtered_from_card(qapp):
    # 按窗口类型全局过滤：hidden_types 含 monthly 时本月行不渲染
    windows = [
        QuotaWindow(type=WindowType.WEEKLY, percent=50),
        QuotaWindow(type=WindowType.MONTHLY, percent=70),
    ]
    card = AccountCard(_snapshot("glm", windows), hidden_types={"monthly"})
    assert set(card._rows) == {"weekly"}
    assert card.findChildren(QProgressBar) == [card._rows["weekly"].bar]


def test_update_snapshot_reuses_row_widgets(qapp):
    # 刷新稳定性：同一窗口集合两次 update_snapshot 复用全部行控件
    snapshot = _snapshot(
        "glm",
        [
            QuotaWindow(type=WindowType.FIVE_H, percent=30),
            QuotaWindow(type=WindowType.WEEKLY, percent=50),
            QuotaWindow(type=WindowType.MONTHLY, percent=70),
        ],
    )
    card = AccountCard(snapshot)
    rows_before = dict(card._rows)
    bar_before = rows_before["weekly"].bar

    snapshot.windows[1].percent = 55
    card.update_snapshot(snapshot)
    assert card._rows == rows_before
    assert card._rows["weekly"].bar is bar_before
    assert card._rows["weekly"].percent_label.text() == "55%"


def test_update_snapshot_diffs_window_set(qapp):
    # 窗口集合增减时仅增删对应行，未变行复用
    snapshot = _snapshot(
        "glm",
        [
            QuotaWindow(type=WindowType.FIVE_H, percent=30),
            QuotaWindow(type=WindowType.WEEKLY, percent=50),
        ],
    )
    card = AccountCard(snapshot)
    weekly_row = card._rows["weekly"]

    snapshot.windows = [
        QuotaWindow(type=WindowType.WEEKLY, percent=60),
        QuotaWindow(type=WindowType.MONTHLY, percent=80),
    ]
    card.update_snapshot(snapshot)
    assert set(card._rows) == {"weekly", "monthly"}
    assert card._rows["weekly"] is weekly_row  # 周行复用而非重建
    assert card._rows["weekly"].percent_label.text() == "60%"


def test_update_snapshot_status_transitions(qapp):
    # ok -> error（无窗口）-> ok：特殊标签与行集合全量切换，无残留
    windows = [QuotaWindow(type=WindowType.WEEKLY, percent=50)]
    snapshot = _snapshot("glm", windows)
    card = AccountCard(snapshot)
    assert set(card._rows) == {"weekly"}

    snapshot.status = ProviderStatus.ERROR
    snapshot.error = "HTTP 500"
    snapshot.windows = []
    card.update_snapshot(snapshot)
    assert card._rows == {}
    texts = [l.text() for l in card.findChildren(QLabel)]
    assert any("获取失败：HTTP 500" in t for t in texts)

    snapshot.status = ProviderStatus.OK
    snapshot.error = None
    snapshot.windows = [QuotaWindow(type=WindowType.WEEKLY, percent=51)]
    card.update_snapshot(snapshot)
    assert set(card._rows) == {"weekly"}
    assert card._rows["weekly"].percent_label.text() == "51%"
