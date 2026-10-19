"""OpenCode Go 额度 Provider。

端点：GET https://opencode.ai/zen/go/v1/usage（社区实证端点，无官方文档）。
鉴权：Bearer API Key；或自动发现 opencode CLI 的 auth.json 登录态。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.model import (
    QuotaSnapshot,
    QuotaWindow,
    WindowType,
    parse_datetime,
    to_number,
)
from app.providers.base import BaseProvider

ENDPOINT = "https://opencode.ai/zen/go/v1/usage"


def _first_present(mapping: dict, keys: tuple) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


class OpenCodeGoProvider(BaseProvider):
    vendor_id = "opencode-go"
    display_name = "OpenCode Go"
    env_names = ("OPENCODE_GO_API_KEY", "OPENCODE_API_KEY")

    def discover_cli(self) -> Optional[str]:
        """从 opencode CLI 的 auth.json 发现登录态。"""
        path = Path.home() / ".config" / "opencode" / "auth.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        candidates = []
        entry = data.get("opencode")
        if isinstance(entry, dict):
            candidates.append(entry)
        candidates.append(data)
        for item in candidates:
            for key in ("access_token", "api_key", "apiKey", "token"):
                value = item.get(key)
                if value:
                    return str(value)
        return None

    def fetch_account(self, account: dict, credential: str) -> list:
        body = _get_json(ENDPOINT, credential)
        return parse_usage(body, self.account_label(account))


def _get_json(url: str, credential: str) -> dict:
    import httpx

    resp = httpx.get(url, headers={"Authorization": f"Bearer {credential}"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _classify_window(key: str) -> Optional[WindowType]:
    text = key.lower()
    if "5" in text or "five" in text or "rolling" in text:
        return WindowType.FIVE_H
    if "week" in text:
        return WindowType.WEEKLY
    if "month" in text:
        return WindowType.MONTHLY
    return None


def parse_usage(body: Any, label: str = "默认") -> list:
    """解析 OpenCode Go 用量响应。

    真实形状（.omo/evidence/opencode_go_live.json 实测 2026-10-14）：
    {"usage": {"rolling": {"status","percent"(0-100),"resetsAt"},
               "weekly": {...}, "monthly": {...}}}
    解析对键名保持防御式兼容（used/limit 形状也能读）。
    """
    snapshot = QuotaSnapshot(vendor="opencode-go", account_label=label)
    usage = None
    if isinstance(body, dict):
        candidate = body.get("usage")
        usage = candidate if isinstance(candidate, dict) else body
    if not isinstance(usage, dict):
        return [snapshot]
    for key, value in usage.items():
        window_type = _classify_window(str(key))
        if window_type is None or not isinstance(value, dict):
            continue
        used = to_number(_first_present(value, ("used", "usedAmount", "currentValue")))
        total = to_number(_first_present(value, ("limit", "total", "quota", "usage")))
        percent = to_number(_first_present(value, ("percent", "percentage")))
        reset_raw = _first_present(
            value, ("resetsAt", "resets_at", "resetAt", "reset_at", "resetTime", "reset")
        )
        window = QuotaWindow(
            type=window_type,
            used=used,
            total=total,
            percent=percent,
            reset_at=parse_datetime(reset_raw),
        )
        window.ensure_derived()
        snapshot.windows.append(window)
    return [snapshot]
