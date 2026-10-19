"""智谱 GLM Provider 单元测试：fixture 解析 + 鉴权头双格式自适应 + 通道选择。"""
from __future__ import annotations

import json
from pathlib import Path

from app.model import WindowType
from app.providers import glm
from app.providers.glm import GlmProvider, _classify_entry, parse_quota_limit

FIXTURE = Path(__file__).parent / "fixtures" / "glm_quota_limit.json"


class FakeResp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_classify_entry_units():
    assert _classify_entry({"type": "CREDIT_LIMIT", "unit": 3}) == WindowType.FIVE_H
    assert _classify_entry({"type": "CREDIT_LIMIT", "unit": 6}) == WindowType.WEEKLY
    assert _classify_entry({"type": "TIME_LIMIT"}) == WindowType.MONTHLY
    assert _classify_entry({"type": "CREDIT_LIMIT"}) is None
    assert _classify_entry({"unit": 99}) is None


def test_parse_quota_limit_real_shape():
    # 实测形状（.omo/evidence/glm_live_bare.json）：
    # usage=总量 / currentValue=已用 / percentage=百分比 / nextResetTime=epoch 毫秒
    snapshots = parse_quota_limit(_load_fixture(), label="主号")
    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert snapshot.plan_label == "LITE"
    by_type = {w.type: w for w in snapshot.windows}
    assert set(by_type) == {WindowType.FIVE_H, WindowType.WEEKLY}
    five_hour = by_type[WindowType.FIVE_H]
    assert five_hour.used == 0
    assert five_hour.total == 2000
    assert five_hour.percent == 0
    assert five_hour.reset_at is None  # 5h 窗口无 nextResetTime
    weekly = by_type[WindowType.WEEKLY]
    assert weekly.used == 6920
    assert weekly.total == 10000
    assert weekly.remaining == 3079
    assert weekly.percent == 69
    assert weekly.reset_at is not None  # epoch 毫秒解析


def test_parse_quota_limit_empty_body():
    snapshot = parse_quota_limit({}, label="x")
    assert snapshot[0].windows == []
    assert snapshot[0].plan_label == ""


def test_get_json_falls_back_to_bearer_on_401():
    calls = []

    def getter(url, headers=None, timeout=None):
        calls.append(headers["Authorization"])
        if len(calls) == 1:
            return FakeResp(401)
        return FakeResp(200, {"data": {"level": "pro", "limits": []}})

    body = glm._get_json("https://example/api", "KEY", getter=getter)
    assert calls == ["KEY", "Bearer KEY"]
    assert body["data"]["level"] == "pro"


def test_get_json_no_retry_when_first_format_ok():
    calls = []

    def getter(url, headers=None, timeout=None):
        calls.append(headers["Authorization"])
        return FakeResp(200, {"ok": 1})

    body = glm._get_json("https://example/api", "KEY", getter=getter)
    assert calls == ["KEY"]
    assert body == {"ok": 1}


def test_get_json_raises_when_both_formats_401():
    def getter(url, headers=None, timeout=None):
        return FakeResp(401)

    try:
        glm._get_json("https://example/api", "KEY", getter=getter)
    except RuntimeError as exc:
        assert "鉴权失败" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_channel_selection():
    provider = GlmProvider({"providers": {}}, env={"ZAI_API_KEY": "z"})
    assert provider.channel({}) == "global"
    provider_cn = GlmProvider(
        {"providers": {}}, env={"BIGMODEL_API_KEY": "b", "ZAI_API_KEY": "z"}
    )
    assert provider_cn.channel({}) == "cn"
    provider_account = GlmProvider({"providers": {}}, env={})
    assert provider_account.channel({"channel": "global"}) == "global"
