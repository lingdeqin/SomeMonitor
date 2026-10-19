"""app.model 单元测试：归一化四场景 + 数值/时间解析 + 余额模型。"""
from __future__ import annotations

from datetime import datetime, timezone

from app.model import (
    BalanceInfo,
    QuotaSnapshot,
    QuotaWindow,
    WindowType,
    parse_datetime,
    to_number,
)


def test_full_fields_window_derives_percent():
    w = QuotaWindow(type=WindowType.FIVE_H, used=250, total=1000)
    w.ensure_derived()
    assert w.percent == 25.0
    assert w.remaining == 750
    assert w.remaining_percent == 75.0


def test_percent_only_window_keeps_used_missing():
    w = QuotaWindow(type=WindowType.WEEKLY, percent=71)
    w.ensure_derived()
    assert w.used is None
    assert w.total is None
    assert w.percent == 71
    assert w.remaining_percent == 29.0


def test_string_numbers_are_parsed():
    assert to_number("100") == 100.0
    assert to_number("1,000") == 1000.0
    assert to_number(42) == 42.0
    assert to_number("") is None
    assert to_number(None) is None
    assert to_number("abc") is None
    assert to_number(True) is None


def test_used_derived_from_total_and_remaining():
    w = QuotaWindow(type=WindowType.WEEKLY, total=100, remaining=40)
    w.ensure_derived()
    assert w.used == 60
    assert w.percent == 60.0


def test_frozen_window_remaining_percent_is_zero():
    w = QuotaWindow(type=WindowType.MONTHLY_FREEZE, frozen=True)
    assert w.remaining_percent == 0.0


def test_parse_datetime_rfc3339_with_offset():
    dt = parse_datetime("2026-05-30T05:26:40+08:00")
    assert dt is not None
    assert dt.year == 2026 and dt.month == 5 and dt.day == 30


def test_parse_datetime_z_suffix_and_microseconds():
    dt = parse_datetime("2026-07-20T09:59:07.479363Z")
    assert dt is not None
    assert dt.microsecond == 479363
    assert dt.tzinfo is not None


def test_parse_datetime_three_digit_fraction_normalized():
    dt = parse_datetime("2026-07-13T13:59:07.123Z")
    assert dt is not None
    assert dt.microsecond == 123000


def test_parse_datetime_epoch_seconds_and_millis():
    from_epoch_s = parse_datetime(1718000000)
    assert from_epoch_s is not None
    from_epoch_ms = parse_datetime(1718000000000)
    assert from_epoch_ms is not None
    assert abs((from_epoch_ms - from_epoch_s).total_seconds()) < 1


def test_parse_datetime_invalid_returns_none():
    assert parse_datetime("") is None
    assert parse_datetime("not-a-date") is None
    assert parse_datetime(None) is None


def test_balance_info_defaults_keep_missing():
    info = BalanceInfo()
    assert info.currency is None
    assert info.total is None
    assert info.granted is None
    assert info.topped_up is None
    assert info.today_spent is None
    assert info.today_spent_estimated is False


def test_snapshot_balance_defaults_to_none():
    snapshot = QuotaSnapshot(vendor="deepseek", account_label="默认")
    assert snapshot.balance is None

    info = BalanceInfo(currency="CNY", total=110.0, granted=10.0)
    snapshot_with_balance = QuotaSnapshot(
        vendor="deepseek", account_label="默认", balance=info
    )
    assert snapshot_with_balance.balance is info
    assert snapshot_with_balance.windows == []
