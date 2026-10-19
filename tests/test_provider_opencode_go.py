"""OpenCode Go Provider 单元测试：fixture 解析 + auth.json 自动发现。"""
from __future__ import annotations

import json
from pathlib import Path

from app.model import WindowType
from app.providers.opencode_go import (
    OpenCodeGoProvider,
    _classify_window,
    parse_usage,
)

FIXTURE = Path(__file__).parent / "fixtures" / "opencode_go_usage.json"


def _load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_classify_window_keys():
    assert _classify_window("five_hour") == WindowType.FIVE_H
    assert _classify_window("5h") == WindowType.FIVE_H
    assert _classify_window("rolling_usage") == WindowType.FIVE_H
    assert _classify_window("weekly") == WindowType.WEEKLY
    assert _classify_window("monthly") == WindowType.MONTHLY
    assert _classify_window("other") is None


def test_parse_usage_real_shape():
    # 实测形状（.omo/evidence/opencode_go_live.json）：rolling/weekly/monthly + percent(0-100) + resetsAt
    snapshots = parse_usage(_load_fixture(), label="主号")
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.vendor == "opencode-go"
    assert snapshot.account_label == "主号"
    by_type = {w.type: w for w in snapshot.windows}
    assert set(by_type) == {WindowType.FIVE_H, WindowType.WEEKLY, WindowType.MONTHLY}
    rolling = by_type[WindowType.FIVE_H]
    assert rolling.percent == 0
    assert rolling.used is None and rolling.total is None  # percent-only 形态
    assert rolling.reset_at is not None  # resetsAt 驼峰键 + 3 位小数秒
    weekly = by_type[WindowType.WEEKLY]
    assert weekly.percent == 80
    assert weekly.remaining_percent == 20.0
    monthly = by_type[WindowType.MONTHLY]
    assert monthly.percent == 40
    assert monthly.reset_at is not None


def test_parse_usage_used_limit_shape_still_supported():
    body = {"usage": {"five_hour": {"used": 4.2, "limit": 12, "resets_at": "2026-10-14T12:00:00Z"}}}
    snapshot = parse_usage(body, label="x")[0]
    window = snapshot.windows[0]
    assert window.used == 4.2
    assert window.total == 12
    assert window.percent == 35.0


def test_parse_usage_non_dict_returns_empty_windows():
    snapshot = parse_usage("oops", label="x")
    assert snapshot[0].windows == []


def test_discover_cli_from_auth_json(tmp_path, monkeypatch):
    auth_dir = tmp_path / ".config" / "opencode"
    auth_dir.mkdir(parents=True)
    (auth_dir / "auth.json").write_text(
        json.dumps({"opencode": {"access_token": "tok-123"}}), encoding="utf-8"
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    provider = OpenCodeGoProvider({"providers": {}}, env={})
    assert provider.discover_cli() == "tok-123"


def test_discover_cli_missing_file_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    provider = OpenCodeGoProvider({"providers": {}}, env={})
    assert provider.discover_cli() is None


def test_credential_priority(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    provider = OpenCodeGoProvider(
        {"providers": {"opencode-go": {"accounts": [{"api_key": "cfg"}]}}},
        env={"OPENCODE_GO_API_KEY": "env"},
    )
    account = provider.accounts()[0]
    assert provider.resolve_credential(account) == "cfg"
