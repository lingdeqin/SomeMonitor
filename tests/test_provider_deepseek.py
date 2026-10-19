"""DeepSeek Provider 单元测试：余额解析 + 差值记账 + 精确通道 + 回退。"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.model import ProviderStatus
from app.providers.deepseek import (
    BALANCE_URL,
    DeepSeekProvider,
    LedgerStore,
    _get_json,
    _today_window,
    apply_observation,
    parse_balance,
    parse_usage_cost,
)

FIXTURE_BALANCE = Path(__file__).parent / "fixtures" / "deepseek_balance.json"
FIXTURE_COST = Path(__file__).parent / "fixtures" / "deepseek_usage_cost.json"
TZ8 = timezone(timedelta(hours=8))


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _make_getter(
    balance_body=None,
    cost_body=None,
    balance_status=200,
    cost_status=200,
    calls=None,
):
    def getter(url, headers=None, params=None, timeout=None):
        if calls is not None:
            calls.append({"url": url, "headers": headers, "params": params})
        if "user/balance" in url:
            return FakeResp(balance_status, balance_body)
        if "by_api_key/cost" in url:
            return FakeResp(cost_status, cost_body)
        raise AssertionError(f"意外请求：{url}")

    return getter


def _provider(accounts, getter=None, now=None, data_dir=None, env=None):
    config = {
        "providers": {
            "deepseek": {"vendor": "deepseek", "visible": True, "accounts": accounts}
        }
    }
    return DeepSeekProvider(
        config, env=env or {}, now=now, data_dir=data_dir, getter=getter
    )


# ---------- 官方余额接口：解析 ----------


def test_parse_balance_string_amounts_and_default_currency():
    info = parse_balance(_load(FIXTURE_BALANCE))
    assert info.currency == "CNY"  # 默认取余额最大项（110 > 3.5）
    assert info.total == 110.0
    assert info.granted == 10.0
    assert info.topped_up == 100.0


def test_parse_balance_preferred_currency_overrides():
    info = parse_balance(_load(FIXTURE_BALANCE), preferred_currency="USD")
    assert info.currency == "USD"
    assert info.total == 3.5
    assert info.granted is None  # USD 项缺 granted_balance -> 缺省


def test_parse_balance_preferred_missing_falls_back_to_max():
    info = parse_balance(_load(FIXTURE_BALANCE), preferred_currency="EUR")
    assert info.currency == "CNY"


def test_parse_balance_granted_missing_keeps_none():
    body = {
        "is_available": True,
        "balance_infos": [
            {"currency": "CNY", "total_balance": "110.00", "granted_balance": None}
        ],
    }
    info = parse_balance(body)
    assert info.total == 110.0
    assert info.granted is None
    assert info.topped_up is None


def test_parse_balance_invalid_body_returns_empty_info():
    assert parse_balance(None).total is None
    assert parse_balance({}).total is None
    assert parse_balance({"balance_infos": []}).total is None
    assert parse_balance({"balance_infos": "bad"}).total is None


def test_get_json_401_raises_chinese_error():
    with pytest.raises(RuntimeError, match="鉴权失败"):
        _get_json(BALANCE_URL, "sk-bad", _make_getter(balance_status=401))


# ---------- Provider 主流程 ----------


def test_fetch_account_builds_balance_snapshot():
    provider = _provider(
        accounts=[{"label": "主号", "api_key": "sk-test"}],
        getter=_make_getter(balance_body=_load(FIXTURE_BALANCE)),
        now=lambda: datetime(2026, 10, 19, 10, 0, tzinfo=TZ8),
    )
    snapshots = provider.fetch_all()
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.vendor == "deepseek"
    assert snapshot.account_label == "主号"
    assert snapshot.status == ProviderStatus.OK
    assert snapshot.windows == []
    balance = snapshot.balance
    assert balance.currency == "CNY"
    assert balance.total == 110.0
    assert balance.today_spent == 0.0  # 首观测：基准建立，当日为 0
    assert balance.today_spent_estimated is True
    assert snapshot.notes == []


def test_fetch_account_without_credential_is_unconfigured():
    provider = _provider(accounts=[{}])
    snapshots = provider.fetch_all()
    assert snapshots[0].status == ProviderStatus.UNCONFIGURED
    assert snapshots[0].balance is None


def test_fetch_account_env_credential_used():
    provider = _provider(
        accounts=[{"label": "默认"}],
        env={"DEEPSEEK_API_KEY": "sk-env"},
        getter=_make_getter(balance_body=_load(FIXTURE_BALANCE)),
        now=lambda: datetime(2026, 10, 19, 10, 0, tzinfo=TZ8),
    )
    assert provider.fetch_all()[0].status == ProviderStatus.OK


def test_fetch_account_invalid_balance_shape_is_error():
    provider = _provider(
        accounts=[{"api_key": "sk-test"}],
        getter=_make_getter(
            balance_body={"is_available": True, "balance_infos": []}
        ),
    )
    snapshot = provider.fetch_all()[0]
    assert snapshot.status == ProviderStatus.ERROR
    assert "无有效币种项" in snapshot.error


# ---------- 差值记账：纯函数规则 ----------


def test_apply_observation_first_observation_creates_baseline():
    entry = apply_observation(None, 110.0, "CNY", "2026-10-19")
    assert entry == {
        "currency": "CNY",
        "day": "2026-10-19",
        "last_seen": 110.0,
        "spent_today": 0.0,
    }


def test_apply_observation_decrease_accumulates_without_mutation():
    entry = {"currency": "CNY", "day": "2026-10-19", "last_seen": 110.0, "spent_today": 0.0}
    updated = apply_observation(entry, 105.0, "CNY", "2026-10-19")
    assert updated["spent_today"] == 5.0
    assert updated["last_seen"] == 105.0
    assert entry["spent_today"] == 0.0  # 入参不被修改


def test_apply_observation_topup_not_negative():
    entry = {"currency": "CNY", "day": "2026-10-19", "last_seen": 105.0, "spent_today": 5.0}
    updated = apply_observation(entry, 200.0, "CNY", "2026-10-19")
    assert updated["spent_today"] == 5.0
    assert updated["last_seen"] == 200.0


def test_apply_observation_day_rollover_resets():
    entry = {"currency": "CNY", "day": "2026-10-19", "last_seen": 105.0, "spent_today": 5.0}
    updated = apply_observation(entry, 103.5, "CNY", "2026-10-20")
    assert updated == {
        "currency": "CNY",
        "day": "2026-10-20",
        "last_seen": 103.5,
        "spent_today": 0.0,
    }


def test_apply_observation_currency_switch_resets():
    entry = {"currency": "CNY", "day": "2026-10-19", "last_seen": 105.0, "spent_today": 5.0}
    updated = apply_observation(entry, 3.0, "USD", "2026-10-19")
    assert updated == {
        "currency": "USD",
        "day": "2026-10-19",
        "last_seen": 3.0,
        "spent_today": 0.0,
    }


# ---------- 差值记账：持久化 ----------


def test_ledger_store_roundtrip_and_reload(tmp_path):
    path = tmp_path / "deepseek_ledger.json"
    store = LedgerStore(path)
    assert store.update("k1", 110.0, "CNY", "2026-10-19") == 0.0
    assert store.update("k1", 105.0, "CNY", "2026-10-19") == 5.0
    reloaded = LedgerStore(path)  # 模拟应用重启
    assert reloaded.update("k1", 100.0, "CNY", "2026-10-19") == 10.0
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["k1"] == {
        "currency": "CNY",
        "day": "2026-10-19",
        "last_seen": 100.0,
        "spent_today": 10.0,
    }


def test_ledger_store_corrupt_file_starts_fresh(tmp_path):
    path = tmp_path / "deepseek_ledger.json"
    path.write_text("{broken", encoding="utf-8")
    store = LedgerStore(path)
    assert store.update("k1", 110.0, "CNY", "2026-10-19") == 0.0


def test_ledger_store_memory_mode_without_path():
    store = LedgerStore(None)
    assert store.update("k1", 110.0, "CNY", "2026-10-19") == 0.0
    assert store.update("k1", 100.0, "CNY", "2026-10-19") == 10.0


def test_provider_two_accounts_concurrent_ledger(tmp_path):
    accounts = [
        {"label": "A", "api_key": "sk-aaa"},
        {"label": "B", "api_key": "sk-bbb"},
    ]
    provider = _provider(
        accounts=accounts,
        getter=_make_getter(balance_body=_load(FIXTURE_BALANCE)),
        now=lambda: datetime(2026, 10, 19, 10, 0, tzinfo=TZ8),
        data_dir=tmp_path,
    )
    snapshots = provider.fetch_all()
    assert sorted(s.account_label for s in snapshots) == ["A", "B"]
    ledger = json.loads(
        (tmp_path / "deepseek_ledger.json").read_text(encoding="utf-8")
    )
    assert len(ledger) == 2  # 各账号按 credential 哈希独立记账


def test_ledger_persists_across_provider_instances(tmp_path):
    now = lambda: datetime(2026, 10, 19, 10, 0, tzinfo=TZ8)  # noqa: E731
    first = _provider(
        accounts=[{"api_key": "sk-test"}],
        getter=_make_getter(balance_body=_load(FIXTURE_BALANCE)),
        now=now,
        data_dir=tmp_path,
    )
    first.fetch_all()  # 建立基准 110
    dropped = {
        "is_available": True,
        "balance_infos": [{"currency": "CNY", "total_balance": "100.00"}],
    }
    second = _provider(
        accounts=[{"api_key": "sk-test"}],
        getter=_make_getter(balance_body=dropped),
        now=now,
        data_dir=tmp_path,
    )
    snapshot = second.fetch_all()[0]
    assert snapshot.balance.today_spent == 10.0  # 重启后当日累计延续


# ---------- 精确通道（userToken） ----------


def test_parse_usage_cost_sums_matching_currency():
    assert parse_usage_cost(_load(FIXTURE_COST), "CNY") == pytest.approx(5.23)
    assert parse_usage_cost(_load(FIXTURE_COST), "USD") == pytest.approx(0.15)


def test_parse_usage_cost_zero_usage_is_zero():
    body = {"code": 0, "data": {"biz_data": {"data": []}}}
    assert parse_usage_cost(body, "CNY") == 0.0


def test_parse_usage_cost_envelope_error_codes():
    for code in (40002, 40003, "40003"):
        body = {"code": code, "msg": "Authorization Failed", "data": None}
        assert parse_usage_cost(body, "CNY") is None


def test_parse_usage_cost_invalid_shape_returns_none():
    assert parse_usage_cost(None, "CNY") is None
    assert parse_usage_cost({}, "CNY") is None
    assert parse_usage_cost({"code": 0, "data": {"biz_data": {"data": "bad"}}}, "CNY") is None


def test_today_window_local_midnight():
    start, tz = _today_window(datetime(2026, 10, 19, 14, 30, tzinfo=TZ8))
    assert start == int(datetime(2026, 10, 19, tzinfo=TZ8).timestamp())
    assert tz == 28800


def test_user_token_resolution_account_over_env():
    provider = _provider(accounts=[{}], env={"DEEPSEEK_USER_TOKEN": "ut-env"})
    assert provider.resolve_user_token({"user_token": "ut-acc"}) == "ut-acc"
    assert provider.resolve_user_token({}) == "ut-env"


def test_fetch_with_token_uses_precise_value():
    calls = []
    provider = _provider(
        accounts=[{"label": "主号", "api_key": "sk-test", "user_token": "ut-abc"}],
        getter=_make_getter(
            balance_body=_load(FIXTURE_BALANCE),
            cost_body=_load(FIXTURE_COST),
            calls=calls,
        ),
        now=lambda: datetime(2026, 10, 19, 14, 30, tzinfo=TZ8),
    )
    snapshot = provider.fetch_all()[0]
    balance = snapshot.balance
    assert balance.today_spent == pytest.approx(5.23)
    assert balance.today_spent_estimated is False
    assert snapshot.notes == []
    # 精确通道请求参数：当日零点窗口 + 整小时时区偏移 + 平台头
    cost_call = calls[1]
    midnight = int(datetime(2026, 10, 19, tzinfo=TZ8).timestamp())
    assert cost_call["params"]["start"] == midnight
    assert cost_call["params"]["end"] == midnight + 86400
    assert cost_call["params"]["tz"] == 28800
    assert cost_call["headers"]["Authorization"] == "Bearer ut-abc"
    assert cost_call["headers"]["x-client-platform"] == "web"


def test_fetch_with_token_zero_cost_is_precise_zero():
    provider = _provider(
        accounts=[{"api_key": "sk-test", "user_token": "ut-abc"}],
        getter=_make_getter(
            balance_body=_load(FIXTURE_BALANCE),
            cost_body={"code": 0, "data": {"biz_data": {"data": []}}},
        ),
        now=lambda: datetime(2026, 10, 19, 14, 30, tzinfo=TZ8),
    )
    snapshot = provider.fetch_all()[0]
    assert snapshot.balance.today_spent == 0.0
    assert snapshot.balance.today_spent_estimated is False
    assert snapshot.notes == []


def test_fetch_token_envelope_failure_falls_back_with_note():
    provider = _provider(
        accounts=[{"api_key": "sk-test", "user_token": "ut-expired"}],
        getter=_make_getter(
            balance_body=_load(FIXTURE_BALANCE),
            cost_body={"code": 40003, "msg": "invalid token", "data": None},
        ),
        now=lambda: datetime(2026, 10, 19, 14, 30, tzinfo=TZ8),
    )
    snapshot = provider.fetch_all()[0]
    assert snapshot.balance.today_spent == 0.0  # 首观测估算
    assert snapshot.balance.today_spent_estimated is True
    assert len(snapshot.notes) == 1
    assert "userToken" in snapshot.notes[0]
    assert "README" in snapshot.notes[0]


def test_fetch_token_http_401_403_fall_back():
    for status in (401, 403):
        provider = _provider(
            accounts=[{"api_key": "sk-test", "user_token": "ut-abc"}],
            getter=_make_getter(
                balance_body=_load(FIXTURE_BALANCE), cost_status=status
            ),
            now=lambda: datetime(2026, 10, 19, 14, 30, tzinfo=TZ8),
        )
        snapshot = provider.fetch_all()[0]
        assert snapshot.balance.today_spent_estimated is True
        assert snapshot.notes


def test_precise_and_ledger_run_in_parallel_across_rounds():
    """同一实例多轮采集：精确值仅覆盖展示，记账持续；token 失效后估算当日可用。"""
    full = _load(FIXTURE_BALANCE)  # 110
    dropped = {
        "is_available": True,
        "balance_infos": [{"currency": "CNY", "total_balance": "106.00"}],
    }
    provider = _provider(
        accounts=[{"api_key": "sk-test", "user_token": "ut-abc"}],
        getter=_make_getter(
            balance_body=full, cost_body=_load(FIXTURE_COST)
        ),
        now=lambda: datetime(2026, 10, 19, 10, 0, tzinfo=TZ8),
    )
    first = provider.fetch_all()[0]
    assert first.balance.today_spent == pytest.approx(5.23)
    assert first.balance.today_spent_estimated is False

    provider._getter = _make_getter(
        balance_body=dropped,
        cost_body={"code": 40003, "msg": "invalid", "data": None},
    )
    second = provider.fetch_all()[0]
    # 余额 110 -> 106：记账全程累计 4.0（未因精确通道成功而中断）
    assert second.balance.today_spent == pytest.approx(4.0)
    assert second.balance.today_spent_estimated is True
    assert second.notes
