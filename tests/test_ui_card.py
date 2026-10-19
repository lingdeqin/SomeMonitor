"""卡片渲染单元测试（离屏）：结构 / 警示色 / 冻结徽标 / 余额行 / 截图。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QProgressBar

from app.model import (
    BalanceInfo,
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


def _balance_snapshot(**kwargs):
    balance = BalanceInfo(currency="CNY", total=110.0, granted=10.0, today_spent=5.23)
    for key, value in kwargs.items():
        setattr(balance, key, value)
    snapshot = _snapshot("deepseek", [])
    snapshot.balance = balance
    return snapshot


def test_card_renders_balance_row(qapp, tmp_path):
    # 默认 fixture：total=110、granted=10、topped_up 缺失 -> 推导 100，拆分展示
    card = AccountCard(_balance_snapshot(today_spent_estimated=False))
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    for expected in ("今日已用", "余额", "¥5.23", "¥100.00 + ¥10.00"):
        assert expected in labels
    assert not any("（估算）" in text for text in labels)
    assert card.findChildren(QProgressBar) == []
    assert not any("未订阅" in text for text in labels)
    out = tmp_path / "card_deepseek.png"
    assert card.grab().save(str(out))


def test_card_balance_segment_order_in_single_row(qapp):
    # 单行两段从左至右：今日已用、余额（赠送 > 0 时金额拆分为「充值 + 赠送」）
    card = AccountCard(_balance_snapshot(today_spent_estimated=True))
    names = [name.text() for name, _ in card._balance_row._labels]
    values = [value.text() for _, value in card._balance_row._labels]
    assert names == ["今日已用", "余额"]
    assert values == ["¥5.23（估算）", "¥100.00 + ¥10.00"]


def test_card_balance_zero_granted_shows_total_only(qapp):
    card = AccountCard(_balance_snapshot(granted=0))
    card.show()
    values = [value.text() for _, value in card._balance_row._labels]
    assert values[1] == "¥110.00"  # 无赠送：仅总额，无「+ 赠送」部分


def test_card_balance_explicit_topped_up_displayed(qapp):
    # 充值余额显式返回时直接展示：105 + 28（合计即总余额 133）
    card = AccountCard(
        _balance_snapshot(total=133.0, topped_up=105.0, granted=28.0)
    )
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert "余额" in labels
    assert "¥105.00 + ¥28.00" in labels


def test_card_balance_topped_up_derived_when_missing(qapp):
    # 充值余额缺失时以 total - granted 推导：133 - 28 = 105
    card = AccountCard(
        _balance_snapshot(total=133.0, topped_up=None, granted=28.0)
    )
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert "¥105.00 + ¥28.00" in labels


def test_card_balance_granted_exceeds_total_clamps_zero(qapp):
    # 异常数据（赠送 > 总额）推导为负时夹取 0，不显示负数
    card = AccountCard(_balance_snapshot(granted=200.0))
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert "¥0.00 + ¥200.00" in labels


def test_card_balance_estimate_suffix(qapp):
    card = AccountCard(_balance_snapshot(today_spent_estimated=True))
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert "¥5.23（估算）" in labels


def test_card_balance_usd_symbol(qapp):
    card = AccountCard(_balance_snapshot(currency="USD"))
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert "$100.00 + $10.00" in labels


def test_card_balance_granted_missing_shows_plain_balance(qapp):
    # 赠送缺失：按无赠送展示，金额仅为总余额
    card = AccountCard(_balance_snapshot(granted=None))
    card.show()
    values = [value.text() for _, value in card._balance_row._labels]
    assert values[1] == "¥110.00"


def test_card_balance_today_spent_missing_omits_segment(qapp):
    card = AccountCard(_balance_snapshot(today_spent=None))
    card.show()
    visible = [
        (name.text(), value.text())
        for (name, value) in card._balance_row._labels
        if name.isVisible()
    ]
    assert visible == [("余额", "¥100.00 + ¥10.00")]  # 仅余额段可见展示


def test_card_without_balance_shows_unsubscribed(qapp):
    card = AccountCard(_snapshot("deepseek", []))
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("未订阅" in text for text in labels)
    assert card._balance_row is None


def test_card_balance_update_in_place(qapp):
    card = AccountCard(_balance_snapshot())
    row_before = card._balance_row
    card.update_snapshot(
        _balance_snapshot(total=90.0, today_spent=20.0, today_spent_estimated=True)
    )
    assert card._balance_row is row_before  # 原地复用而非重建
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert "¥80.00 + ¥10.00" in labels  # 90 - 10 推导充值余额
    assert "¥20.00（估算）" in labels


def test_card_balance_removed_when_total_missing(qapp):
    card = AccountCard(_balance_snapshot())
    card.update_snapshot(_balance_snapshot(total=None))
    assert card._balance_row is None


def test_card_stale_balance_kept_with_annotation(qapp):
    snapshot = _balance_snapshot()
    snapshot.stale = True
    snapshot.stale_error = "timeout"
    snapshot.stale_since = datetime(2026, 10, 19, 10, 30, tzinfo=timezone.utc)
    card = AccountCard(snapshot)
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert "¥100.00 + ¥10.00" in labels  # 沿用旧余额数据
    assert any("显示旧数据" in text for text in labels)


def test_card_balance_notes_rendered(qapp):
    snapshot = _balance_snapshot()
    snapshot.notes.append("今日精确消费获取失败：userToken 可能已过期，请在浏览器 localStorage 重新复制（步骤见 README）")
    card = AccountCard(snapshot)
    card.show()
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("今日精确消费获取失败" in text for text in labels)
    assert "¥100.00 + ¥10.00" in labels


def test_card_balance_error_state_clears_rows(qapp):
    card = AccountCard(_balance_snapshot())
    card.update_snapshot(
        _snapshot("deepseek", [], status=ProviderStatus.ERROR, error="HTTP 500")
    )
    assert card._balance_row is None
    assert card._body.count() == 1  # 仅剩特殊状态标签（余额行已出布局）
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("获取失败" in text for text in labels)


def test_card_balance_unconfigured_clears_rows(qapp):
    card = AccountCard(_balance_snapshot())
    card.update_snapshot(_snapshot("deepseek", [], status=ProviderStatus.UNCONFIGURED))
    assert card._balance_row is None
    labels = [l.text() for l in card.findChildren(QLabel)]
    assert any("未配置" in text for text in labels)


def test_card_balance_name_width_defaults_to_row_layout(qapp):
    card = AccountCard(
        _balance_snapshot(), row_layout={"name_width": 66}
    )
    name_labels = [
        label
        for label, _ in card._balance_row._labels
    ]
    assert all(label.width() == 52 for label in name_labels)  # 默认对齐 name_width


def test_card_balance_row_layout_configured_independently(qapp):
    card = AccountCard(
        _balance_snapshot(),
        row_layout={"name_width": 40},
        balance_row_layout={"name_width": 80},
    )
    card.show()
    balance_name_labels = [label for label, _ in card._balance_row._labels]
    assert all(label.width() == 80 for label in balance_name_labels)
    window = QuotaWindow(type=WindowType.WEEKLY, percent=50)
    window_card = AccountCard(
        _snapshot("glm", [window]), balance_row_layout={"name_width": 80}
    )
    assert window_card._rows["weekly"].name_label.width() == 52


def test_card_balance_per_segment_width_overrides(qapp):
    # 按段覆盖：今日已用段名称 64、数值 88；余额段回退 name_width 52、数值自适应
    card = AccountCard(
        _balance_snapshot(),
        balance_row_layout={
            "name_width": 52,
            "spent_name_width": 64,
            "spent_value_width": 88,
        },
    )
    card.show()
    (spent_name, spent_value), (balance_name, balance_value) = (
        card._balance_row._labels
    )
    assert spent_name.width() == 64
    assert spent_value.width() == 88
    assert spent_value.alignment() == Qt.AlignRight | Qt.AlignVCenter
    assert balance_name.width() == 52
    assert balance_value.maximumWidth() == 16777215  # 未定宽（Qt 默认上限）


def test_card_balance_unified_value_width_applies_to_all_segments(qapp):
    card = AccountCard(
        _balance_snapshot(),
        balance_row_layout={"value_width": 72},
    )
    values = [value for _, value in card._balance_row._labels]
    assert all(value.width() == 72 for value in values)
    assert all(
        value.alignment() == Qt.AlignRight | Qt.AlignVCenter for value in values
    )


def test_card_balance_per_segment_value_overrides_unified(qapp):
    card = AccountCard(
        _balance_snapshot(),
        balance_row_layout={
            "value_width": 72,
            "balance_value_width": 96,
        },
    )
    values = [value for _, value in card._balance_row._labels]
    assert values[0].width() == 72  # 统一 value_width
    assert values[1].width() == 96  # 按段覆盖优先
