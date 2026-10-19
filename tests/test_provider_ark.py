"""火山方舟 Provider 单元测试：arkcli 输出解析 + SigV4 签名构造 + 通道选择。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from app.model import ProviderStatus, QuotaSnapshot, WindowType, window_label
from app.providers.ark import (
    ArkProvider,
    parse_arkcli_output,
    parse_openapi_action,
    sigv4_headers,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ark_usage_plan.json"


def _load_fixture():
    return FIXTURE.read_text(encoding="utf-8")


def test_parse_arkcli_output_multiple_items():
    snapshots = parse_arkcli_output(_load_fixture(), label="默认")
    assert len(snapshots) == 4

    agent = snapshots[0]
    assert agent.plan_label == "Agent Plan · 个人版 · medium"
    assert agent.status == ProviderStatus.OK
    by_type = {w.type: w for w in agent.windows}
    assert set(by_type) == {WindowType.FIVE_H, WindowType.WEEKLY, WindowType.MONTHLY}
    five_hour = by_type[WindowType.FIVE_H]
    assert five_hour.used == 250
    assert five_hour.total == 1000
    assert five_hour.percent == 25
    assert five_hour.reset_at is not None

    coding = snapshots[1]
    assert coding.plan_label == "Coding Plan · 个人版"
    # CodingPlan 只有百分比：used/total 缺省而非伪造
    for window in coding.windows:
        assert window.used is None
        assert window.total is None
    # 「会话」窗口归一化为 5 小时窗口类型
    assert {w.type for w in coding.windows} == {WindowType.FIVE_H, WindowType.WEEKLY}
    assert by_type_percents(coding) == {"5h": 42, "weekly": 71}
    assert window_label(WindowType.FIVE_H) == "5 小时"

    team_error = snapshots[2]
    assert team_error.status == ProviderStatus.ERROR
    assert "no seat bound" in team_error.error

    unsubscribed = snapshots[3]
    assert unsubscribed.status == ProviderStatus.OK
    assert unsubscribed.windows == []  # 未订阅 -> 空窗口，卡片显示「未订阅」


def by_type_percents(snapshot):
    return {w.type.value: w.percent for w in snapshot.windows}


def test_parse_codingplan_percent_fraction_normalized():
    # 实测抓包形态（.omo/evidence/ark_live.json）：CodingPlan percent 为 0-1 比率
    raw = json.dumps(
        {
            "viewer": {},
            "items": [
                {
                    "product": "coding-plan",
                    "edition": "personal",
                    "subscribed": True,
                    "periods": [
                        {"label": "session", "percent": 0.915607,
                         "reset_at": "2026-10-14T16:30:38+08:00"},
                        {"label": "weekly", "percent": 0.12208093333333334,
                         "reset_at": "2026-10-19T00:00:00+08:00"},
                    ],
                    "updated_at": 1791950750,
                }
            ],
        }
    )
    snapshots = parse_arkcli_output(raw, label="x")
    windows = {w.type: w for w in snapshots[0].windows}
    assert windows[WindowType.FIVE_H].percent == 91.56
    assert windows[WindowType.WEEKLY].percent == 12.21
    assert windows[WindowType.FIVE_H].remaining_percent == 8.4


def test_agentplan_percent_scale_untouched_when_used_total_present():
    raw = json.dumps(
        {
            "items": [
                {
                    "product": "agent-plan",
                    "edition": "personal",
                    "subscribed": True,
                    "periods": [
                        {"label": "5h", "used": 250, "total": 1000, "percent": 25}
                    ],
                }
            ]
        }
    )
    snapshots = parse_arkcli_output(raw)
    assert snapshots[0].windows[0].percent == 25


def test_parse_arkcli_output_rejects_non_object():
    with pytest.raises(RuntimeError):
        parse_arkcli_output("[]", label="x")


def test_parse_arkcli_output_carries_viewer_account():
    snapshots = parse_arkcli_output(_load_fixture(), label="x")
    assert snapshots
    assert all(s.viewer_account_id == "210000" for s in snapshots)


def test_duplicate_viewer_accounts_annotated():
    # 回归：两个 profile 实为同一火山账号（一次 SSO 派生多类型 profile），
    # 曾表现为"两个账号数据一模一样"且无任何提示
    first = QuotaSnapshot(vendor="ark", account_label="A", plan_label="Coding Plan",
                          viewer_account_id="111")
    second = QuotaSnapshot(vendor="ark", account_label="B", plan_label="Coding Plan",
                           viewer_account_id="111")
    third = QuotaSnapshot(vendor="ark", account_label="C", plan_label="Coding Plan",
                          viewer_account_id="222")
    ArkProvider._mark_duplicate_viewer_accounts([first, second, third])
    assert "同一火山账号" not in first.plan_label
    assert "同一火山账号" in second.plan_label
    assert "同一火山账号" not in third.plan_label


def test_same_label_same_account_not_annotated():
    # 同一账号多条计划（Coding + Agent Plan）不误报
    a1 = QuotaSnapshot(vendor="ark", account_label="A", plan_label="Coding Plan",
                       viewer_account_id="111")
    a2 = QuotaSnapshot(vendor="ark", account_label="A", plan_label="Agent Plan",
                       viewer_account_id="111")
    ArkProvider._mark_duplicate_viewer_accounts([a1, a2])
    assert "同一火山账号" not in a1.plan_label
    assert "同一火山账号" not in a2.plan_label


def test_sigv4_headers_structure():
    headers = sigv4_headers(
        "GET",
        "https://open.volcengineapi.com",
        {"Version": "2024-01-01", "Action": "GetCodingPlanUsage"},
        "AKTEST",
        "SKTEST",
    )
    auth = headers["Authorization"]
    assert auth.startswith("HMAC-SHA256 Credential=AKTEST/20")
    assert "/cn-beijing/ark/request" in auth
    assert "SignedHeaders=content-type;host;x-content-sha256;x-date" in auth
    signature = auth.split("Signature=")[1]
    assert len(signature) == 64
    assert all(ch in "0123456789abcdef" for ch in signature)
    x_date = headers["X-Date"]
    assert x_date.endswith("Z") and "T" in x_date
    assert headers["x-content-sha256"] == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_sigv4_headers_deterministic_within_same_inputs():
    params = {"Action": "GetAFPUsage", "Version": "2024-01-01"}
    first = sigv4_headers("GET", "https://open.volcengineapi.com", params, "A", "S")
    second = sigv4_headers("GET", "https://open.volcengineapi.com", params, "A", "S")
    assert first["Authorization"] == second["Authorization"]


def test_transport_selection_auto_prefers_openapi_only_with_both_keys():
    provider = ArkProvider({"providers": {"ark": {"transport": "auto"}}}, env={})
    assert provider.select_transport({}, None, None) == "arkcli"
    assert provider.select_transport({}, "ak", None) == "arkcli"
    assert provider.select_transport({}, None, "sk") == "arkcli"
    assert provider.select_transport({}, "ak", "sk") == "openapi"


def test_ark_api_key_without_secret_raises_guidance():
    # 回归：ark- API Key 无 SK 曾静默回落到本机会话，导致多账号显示同一份数据
    provider = ArkProvider({"providers": {}}, env={})
    with pytest.raises(RuntimeError) as excinfo:
        provider.select_transport({}, "ark-1870c643-demo-key", None)
    assert "profile" in str(excinfo.value)
    assert "secret_access_key" in str(excinfo.value)


def test_arkcli_command_with_and_without_profile():
    from app.providers.ark import _arkcli_command

    assert _arkcli_command("arkcli") == ["arkcli", "usage", "plan", "--format", "json"]
    assert _arkcli_command("arkcli", profile="work") == [
        "arkcli", "--profile", "work", "usage", "plan", "--format", "json",
    ]


def test_arkcli_subprocess_suppresses_console_window(monkeypatch):
    # 回归：windowed exe 下 arkcli 子进程缺 CREATE_NO_WINDOW 会每轮刷新闪一次终端
    import subprocess as subprocess_module

    import app.providers.ark as ark_module

    monkeypatch.setattr(ark_module.shutil, "which", lambda name: "arkcli")
    captured = {}

    def fake_run(args, **kwargs):
        captured.update(kwargs)
        return subprocess_module.CompletedProcess(
            args, 0, stdout='{"items":[]}', stderr=""
        )

    monkeypatch.setattr(subprocess_module, "run", fake_run)
    snapshots = ark_module.ArkProvider({"providers": {}}, env={})._fetch_arkcli("默认")
    assert snapshots == []
    assert captured.get("creationflags") == ark_module._NO_WINDOW
    if sys.platform == "win32":
        assert ark_module._NO_WINDOW == subprocess_module.CREATE_NO_WINDOW


def test_profile_account_routes_to_arkcli(monkeypatch):
    provider = ArkProvider({"providers": {}}, env={})
    calls = []

    def fake_arkcli(label, profile=None):
        calls.append((label, profile))
        return []

    monkeypatch.setattr(provider, "_fetch_arkcli", fake_arkcli)
    provider.fetch_account({"label": "A", "profile": "p1"}, "whatever-key")
    assert calls == [("A", "p1")]


def test_transport_selection_explicit_overrides():
    forced = ArkProvider({"providers": {"ark": {"transport": "arkcli"}}}, env={})
    assert forced.select_transport({}, "ak", "sk") == "arkcli"
    forced_openapi = ArkProvider(
        {"providers": {"ark": {"transport": "openapi"}}}, env={}
    )
    assert forced_openapi.select_transport({}, None, None) == "openapi"


def test_transport_invalid_falls_back_to_auto():
    provider = ArkProvider({"providers": {"ark": {"transport": "wat"}}}, env={})
    assert provider.transport({}) == "auto"


def test_ark_requires_no_credential_and_reports_missing_cli(monkeypatch):
    import app.providers.ark as ark_module

    provider = ArkProvider({"providers": {}}, env={})
    assert provider.requires_credential is False
    # 无凭证也能进入采集路径；arkcli 不存在时给出明确错误（不触网）
    monkeypatch.setattr(ark_module.shutil, "which", lambda name: None)
    snapshots = provider.fetch_all()
    assert len(snapshots) == 1
    assert snapshots[0].status == ProviderStatus.ERROR
    assert "arkcli" in (snapshots[0].error or "")


def test_parse_openapi_action_lenient():
    body = {
        "ResponseMetadata": {"RequestId": "r"},
        "Result": {
            "QuotaUsage": [
                {"Label": "5h", "Percent": 30, "Used": 3, "Total": 10,
                 "ResetTime": 1718000000000},
                {"Label": "weekly", "Percent": 55},
            ]
        },
    }
    snapshots = parse_openapi_action(body, "默认", "GetCodingPlanUsage")
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.plan_label == "Coding Plan"
    windows = {w.type: w for w in snapshot.windows}
    assert windows[WindowType.FIVE_H].percent == 30
    assert windows[WindowType.WEEKLY].percent == 55
    assert windows[WindowType.FIVE_H].reset_at is not None


def test_parse_openapi_action_unrecognized_raises():
    with pytest.raises(RuntimeError):
        parse_openapi_action({"Nothing": "here"}, "x", "GetAFPUsage")
