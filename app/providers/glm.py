"""智谱 GLM Coding Plan 额度 Provider。

端点：GET {base}/api/monitor/usage/quota/limit
  国内版 base = https://open.bigmodel.cn
  国际版 base = https://api.z.ai
鉴权：Authorization 头；社区来源对是否带 Bearer 前缀存在分歧，
     实现为「先裸 Key、401 自动换 Bearer 重试」。
响应：data.level 为套餐档位；data.limits[] 中
  unit=3   -> 5 小时滚动窗口
  unit=6   -> 周配额
  TIME_LIMIT -> 月度（MCP 工具）额度
"""
from __future__ import annotations

from typing import Any, Optional

from app.model import (
    QuotaSnapshot,
    QuotaWindow,
    WindowType,
    parse_datetime,
    to_number,
)
from app.providers.base import BaseProvider

ENDPOINTS = {"cn": "https://open.bigmodel.cn", "global": "https://api.z.ai"}
API_PATH = "/api/monitor/usage/quota/limit"


def _first_present(mapping: dict, keys: tuple) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


class GlmProvider(BaseProvider):
    vendor_id = "glm"
    display_name = "智谱 GLM"
    env_names = ("BIGMODEL_API_KEY", "ZAI_CODING_CN_API_KEY", "ZAI_API_KEY")

    def channel(self, account: dict) -> str:
        configured = str(account.get("channel") or "")
        if configured in ENDPOINTS:
            return configured
        # 只配置了 ZAI 国际版 Key 时走国际端点
        if self.env_get("ZAI_API_KEY") and not self.env_get("BIGMODEL_API_KEY"):
            return "global"
        return "cn"

    def fetch_account(self, account: dict, credential: str) -> list:
        url = ENDPOINTS[self.channel(account)] + API_PATH
        body = _get_json(url, credential)
        return parse_quota_limit(body, self.account_label(account))


def _get_json(url: str, credential: str, getter=None) -> dict:
    """请求并解析；Authorization 头双格式自适应（401 换 Bearer 重试一次）。"""
    if getter is None:
        import httpx

        getter = httpx.get
    last_status = None
    for header_value in (credential, f"Bearer {credential}"):
        resp = getter(url, headers={"Authorization": header_value}, timeout=15)
        if resp.status_code == 401:
            last_status = 401
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError(
        f"GLM 接口鉴权失败（两种 Authorization 格式均返回 401，status={last_status}）"
    )


def _classify_entry(entry: dict) -> Optional[WindowType]:
    values_text = " ".join(
        str(value) for value in entry.values() if isinstance(value, str)
    ).upper()
    if "TIME_LIMIT" in values_text:
        return WindowType.MONTHLY
    unit = to_number(_first_present(entry, ("unit", "timeUnit", "time_unit")))
    if unit is not None:
        if int(unit) == 3:
            return WindowType.FIVE_H
        if int(unit) == 6:
            return WindowType.WEEKLY
    type_text = str(
        _first_present(entry, ("type", "limitType", "limit_type")) or ""
    ).upper()
    if "5" in type_text and ("H" in type_text or "HOUR" in type_text):
        return WindowType.FIVE_H
    if "WEEK" in type_text:
        return WindowType.WEEKLY
    if "MONTH" in type_text:
        return WindowType.MONTHLY
    return None


def parse_quota_limit(body: Any, label: str = "默认") -> list:
    """解析 GLM quota/limit 响应。

    真实形状（.omo/evidence/glm_live_bare.json 实测 2026-10-14）：
    {"data": {"level": "lite", "limits": [
       {"type": "CREDIT_LIMIT", "unit": 3|6, "usage": 总量,
        "currentValue": 已用, "remaining": 剩余,
        "percentage": 已用百分比(0-100), "nextResetTime": epoch 毫秒}]}}
    """
    snapshot = QuotaSnapshot(vendor="glm", account_label=label)
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict):
        return [snapshot]
    level = data.get("level")
    if level:
        snapshot.plan_label = str(level).upper()
    for entry in data.get("limits") or []:
        if not isinstance(entry, dict):
            continue
        window_type = _classify_entry(entry)
        if window_type is None:
            continue
        used = to_number(_first_present(entry, ("currentValue", "used", "usedTokens")))
        total = to_number(_first_present(entry, ("usage", "limit", "total", "quota")))
        remaining = to_number(_first_present(entry, ("remaining",)))
        percent = to_number(_first_present(entry, ("percentage", "percent")))
        reset_raw = _first_present(
            entry, ("nextResetTime", "resetTime", "reset_at", "resetAt", "reset")
        )
        window = QuotaWindow(
            type=window_type,
            used=used,
            total=total,
            remaining=remaining,
            percent=percent,
            reset_at=parse_datetime(reset_raw),
        )
        window.ensure_derived()
        snapshot.windows.append(window)
    return [snapshot]
