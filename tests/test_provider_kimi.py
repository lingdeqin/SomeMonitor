"""Kimi Provider 单元测试：三态 fixture（正常 / used 缺省 / 月度冻结）+ 月度会员增强。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from app.model import WindowType
from app.providers.kimi import (
    KimiProvider,
    _parse_membership_stats,
    parse_usages,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _by_type(snapshot):
    return {w.type: w for w in snapshot.windows}


def test_parse_usages_normal():
    snapshots = parse_usages(_load("kimi_usages_normal.json"), label="主号")
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.vendor == "kimi"
    assert snapshot.plan_label == "PRO"
    windows = _by_type(snapshot)
    assert set(windows) == {WindowType.WEEKLY, WindowType.FIVE_H, WindowType.MONTHLY_FREEZE}
    # 字符串数字解析 + used 推导：limit=100, remaining=40 -> used=60
    weekly = windows[WindowType.WEEKLY]
    assert weekly.total == 100
    assert weekly.used == 60
    assert weekly.percent == 60.0
    assert weekly.reset_at is not None
    five_hour = windows[WindowType.FIVE_H]
    assert five_hour.used == 45  # 100 - 55
    # totalQuota 无 used 字段 -> 未冻结
    freeze = windows[WindowType.MONTHLY_FREEZE]
    assert freeze.frozen is False
    assert freeze.remaining_percent == 100.0


def test_parse_usages_used_missing_derived():
    snapshot = parse_usages(_load("kimi_usages_no_used.json"), label="x")[0]
    windows = _by_type(snapshot)
    assert windows[WindowType.WEEKLY].used == 28  # 100 - 72
    assert windows[WindowType.WEEKLY].percent == 28.0
    assert windows[WindowType.MONTHLY_FREEZE].frozen is False


def test_parse_usages_monthly_frozen_signal():
    snapshot = parse_usages(_load("kimi_usages_frozen.json"), label="x")[0]
    windows = _by_type(snapshot)
    freeze = windows[WindowType.MONTHLY_FREEZE]
    # totalQuota.used = "1"（>0）-> 月度会员额度冻结
    assert freeze.frozen is True
    assert freeze.remaining_percent == 0.0
    # 冻结不影响周限/5h 窗口本身的解析
    assert windows[WindowType.WEEKLY].percent == 100.0


def test_parse_usages_empty_body():
    snapshot = parse_usages({}, label="x")[0]
    assert snapshot.windows == []


def test_credential_env_priority():
    provider = KimiProvider(
        {"providers": {"kimi": {"accounts": [{"api_key": "cfg"}]}}},
        env={"KIMI_API_KEY": "env"},
    )
    assert provider.resolve_credential(provider.accounts()[0]) == "cfg"
    provider_env_only = KimiProvider({"providers": {}}, env={"KIMI_API_KEY": "env"})
    assert provider_env_only.resolve_credential({}) == "env"


def test_discover_cli_from_credentials_dir(tmp_path, monkeypatch):
    cred_dir = tmp_path / ".kimi-code" / "credentials"
    cred_dir.mkdir(parents=True)
    (cred_dir / "default.json").write_text(
        json.dumps({"api_key": "sk-kimi-test"}), encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    provider = KimiProvider({"providers": {}}, env={})
    assert provider.discover_cli() == "sk-kimi-test"


def test_discover_cli_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    provider = KimiProvider({"providers": {}}, env={})
    assert provider.discover_cli() is None


def test_parse_membership_stats_ratio_normalized():
    body = {
        "subscription_balance": {
            "amount_used_ratio": 0.1612,
            "expire_time": "2026-11-01T00:00:00Z",
        }
    }
    window = _parse_membership_stats(body)
    assert window is not None
    assert window.type == WindowType.MONTHLY
    assert window.percent == 16.12  # 0-1 比率归一化为百分比
    assert window.reset_at is not None


def test_parse_membership_stats_camel_case():
    window = _parse_membership_stats(
        {"subscriptionBalance": {"amountUsedRatio": 0.5}}
    )
    assert window is not None
    assert window.percent == 50.0


def test_parse_membership_stats_over_one_passthrough():
    window = _parse_membership_stats({"subscription_balance": {"amount_used_ratio": 16.12}})
    assert window.percent == 16.12


def test_parse_membership_stats_invalid_returns_none():
    assert _parse_membership_stats({}) is None
    assert _parse_membership_stats({"subscription_balance": {}}) is None
    assert _parse_membership_stats("nope") is None


def test_parse_membership_stats_real_success_body():
    # 实测 200 响应（.omo/evidence/kimi_membership_success.json，2026-10-14）
    body = json.loads(
        (Path(__file__).parent / "fixtures" / "kimi_membership_success.json").read_text(
            encoding="utf-8"
        )
    )
    window = _parse_membership_stats(body)
    assert window is not None
    assert window.type == WindowType.MONTHLY
    assert window.percent == 0.84  # amountUsedRatio 0.0084 -> 0.84%
    assert window.reset_at is not None
    assert window.reset_at.year == 2026 and window.reset_at.month == 11


def test_resolve_kimi_auth_priority():
    provider = KimiProvider({"providers": {}}, env={"KIMI_AUTH_TOKEN": "from-env"})
    assert provider.resolve_kimi_auth({}) == "from-env"
    assert provider.resolve_kimi_auth({"kimi_auth": "cfg"}) == "cfg"
    provider_no_env = KimiProvider({"providers": {}}, env={})
    assert provider_no_env.resolve_kimi_auth({}) is None


def test_cookie_expiry_text_decodes_jwt():
    import base64
    import json as jsonlib

    from app.providers.kimi import _cookie_expiry_text

    payload = jsonlib.dumps({"exp": 1787102645})
    token = "h." + base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=") + ".s"
    text = _cookie_expiry_text(token)
    assert text is not None
    assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}$", text)
    assert _cookie_expiry_text("not-a-jwt") is None


def test_auth_header_value_accepts_both_paste_forms():
    from app.providers.kimi import _auth_header_value

    assert _auth_header_value("eyJxxx") == "Bearer eyJxxx"
    assert _auth_header_value("Bearer eyJxxx") == "Bearer eyJxxx"
    assert _auth_header_value("bearer eyJxxx") == "bearer eyJxxx"


def test_monthly_token_prefers_refresh_and_caches(monkeypatch):
    import app.providers.kimi as kimi_module

    provider = KimiProvider({"providers": {}}, env={})
    calls = []

    def fake_refresh(refresh_token):
        calls.append(refresh_token)
        return "ACCESS", None

    monkeypatch.setattr(kimi_module, "_refresh_access_token", fake_refresh)
    first = provider._get_monthly_token({"refresh_token": "R"})
    second = provider._get_monthly_token({"refresh_token": "R"})
    assert first == "ACCESS"
    assert second == "ACCESS"
    assert len(calls) == 1  # 第二次命中内存缓存，不重复换 token


def test_monthly_token_falls_back_to_manual_kimi_auth():
    provider = KimiProvider({"providers": {}}, env={})
    assert provider._get_monthly_token({"kimi_auth": "MANUAL"}) == "MANUAL"
    assert provider._get_monthly_token({}) is None


def test_fetch_account_refresh_failure_note(monkeypatch):
    import app.providers.kimi as kimi_module

    provider = KimiProvider({"providers": {}}, env={})
    body = _load("kimi_usages_normal.json")
    monkeypatch.setattr(kimi_module, "_get_json", lambda url, cred: body)
    monkeypatch.setattr(
        kimi_module, "_refresh_access_token", lambda rt: (None, None)
    )
    snapshots = provider.fetch_account({"refresh_token": "R"}, "k")
    assert snapshots[0].notes
    assert "refresh_token" in snapshots[0].notes[0]
    assert "localStorage" in snapshots[0].notes[0]


def test_fetch_account_notes_on_monthly_failure(monkeypatch):
    # 回归：cookie 配置但月度获取失败（如已过期）曾静默跳过，用户无从排查
    import app.providers.kimi as kimi_module

    provider = KimiProvider({"providers": {}}, env={})
    body = _load("kimi_usages_normal.json")
    monkeypatch.setattr(kimi_module, "_get_json", lambda url, cred: body)
    monkeypatch.setattr(kimi_module, "_fetch_monthly_membership", lambda cookie: None)
    snapshots = provider.fetch_account({"kimi_auth": "abc"}, "k")
    assert snapshots[0].notes
    assert "月度会员额度获取失败" in snapshots[0].notes[0]
    assert "authorization" in snapshots[0].notes[0]


def test_fetch_account_monthly_success_no_note(monkeypatch):
    import app.providers.kimi as kimi_module
    from app.model import QuotaWindow as QW

    provider = KimiProvider({"providers": {}}, env={})
    body = _load("kimi_usages_normal.json")
    monkeypatch.setattr(kimi_module, "_get_json", lambda url, cred: body)
    monthly = QW(type=WindowType.MONTHLY, percent=16.12)
    monkeypatch.setattr(kimi_module, "_fetch_monthly_membership", lambda cookie: monthly)
    snapshots = provider.fetch_account({"kimi_auth": "abc"}, "k")
    assert snapshots[0].notes == []
    assert WindowType.MONTHLY in [w.type for w in snapshots[0].windows]
