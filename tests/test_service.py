"""QuotaService 单元测试：成功 -> 失败(stale) -> 恢复 的状态转换。"""
from __future__ import annotations

import copy
from datetime import datetime

from app.model import ProviderStatus, QuotaSnapshot, QuotaWindow, WindowType
from app.service import QuotaService


def _ok_snapshot(vendor="x", plan=""):
    return QuotaSnapshot(
        vendor=vendor,
        account_label="默认",
        plan_label=plan,
        windows=[QuotaWindow(type=WindowType.FIVE_H, used=1, total=10)],
    )


def _error_snapshot(vendor="x", plan="", error="boom"):
    return QuotaSnapshot(
        vendor=vendor,
        account_label="默认",
        plan_label=plan,
        status=ProviderStatus.ERROR,
        error=error,
    )


class ScriptedProvider:
    """按脚本顺序返回结果的假 Provider。"""

    def __init__(self, sequence):
        self.sequence = [copy.deepcopy(item) for item in sequence]
        self.calls = 0

    def fetch_all(self):
        item = self.sequence[min(self.calls, len(self.sequence) - 1)]
        self.calls += 1
        return [copy.deepcopy(item)]


def test_success_failure_recovery_cycle():
    provider = ScriptedProvider(
        [_ok_snapshot(), _error_snapshot(), _ok_snapshot()]
    )
    service = QuotaService([provider], now=lambda: datetime(2026, 10, 14, 10, 30))

    # 1) 成功
    first = service.refresh()
    assert first[0].status == ProviderStatus.OK
    assert first[0].stale is False
    assert len(service.last_good) == 1

    # 2) 失败 -> 回填 last-good 并标注 stale
    second = service.refresh()
    assert second[0].stale is True
    assert second[0].stale_error == "boom"
    assert second[0].stale_since == datetime(2026, 10, 14, 10, 30)
    assert [w.used for w in second[0].windows] == [1]  # 旧数据仍在
    assert service.last_error

    # 3) 恢复 -> stale 清除
    third = service.refresh()
    assert third[0].status == ProviderStatus.OK
    assert third[0].stale is False
    assert not service.last_error


def test_failure_without_history_shows_error_snapshot():
    provider = ScriptedProvider([_error_snapshot()])
    service = QuotaService([provider])
    merged = service.refresh()
    assert merged[0].status == ProviderStatus.ERROR
    assert merged[0].error == "boom"
    assert merged[0].stale is False


def test_unconfigured_passthrough_no_last_good():
    unconfigured = QuotaSnapshot(
        vendor="y", account_label="默认", status=ProviderStatus.UNCONFIGURED
    )
    provider = ScriptedProvider([unconfigured])
    service = QuotaService([provider])
    merged = service.refresh()
    assert merged[0].status == ProviderStatus.UNCONFIGURED
    assert service.last_good == {}


def test_stale_snapshot_is_a_copy_not_mutation():
    provider = ScriptedProvider([_ok_snapshot(), _error_snapshot()])
    service = QuotaService([provider])
    first = service.refresh()
    original = first[0]
    service.refresh()
    assert original.stale is False  # last_good 原件未被就地污染
