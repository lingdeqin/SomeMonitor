"""归一化额度数据模型与推导规则。

各厂商的原始响应统一归一化为 QuotaSnapshot / QuotaWindow；
端上缺失的字段保持缺省（None），不伪造数值。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional


class WindowType(str, Enum):
    FIVE_H = "5h"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    SESSION = "session"
    # Kimi totalQuota：月度会员额度冻结的二元信号，不是百分比
    MONTHLY_FREEZE = "monthly_freeze"


class ProviderStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    UNCONFIGURED = "unconfigured"


_WINDOW_TYPE_LABELS = {
    WindowType.FIVE_H: "5 小时",
    WindowType.WEEKLY: "本周",
    WindowType.MONTHLY: "本月",
    WindowType.SESSION: "会话",
    WindowType.MONTHLY_FREEZE: "月度额度",
}


def window_label(window_type: WindowType) -> str:
    return _WINDOW_TYPE_LABELS.get(window_type, window_type.value)


@dataclass
class QuotaWindow:
    """单个额度窗口（5 小时 / 周 / 月 / 会话 / 月度冻结信号）。"""

    type: WindowType
    used: Optional[float] = None
    total: Optional[float] = None
    remaining: Optional[float] = None
    # 已用百分比（0-100）；厂商只返回百分比时 used/total 为 None
    percent: Optional[float] = None
    reset_at: Optional[datetime] = None
    # 仅 MONTHLY_FREEZE 使用：True 表示月度会员额度已冻结
    frozen: Optional[bool] = None

    def ensure_derived(self) -> None:
        """按已知字段推导缺失字段（不覆盖已有值）。"""
        if self.used is None and self.total is not None and self.remaining is not None:
            self.used = max(self.total - self.remaining, 0.0)
        if self.remaining is None and self.total is not None and self.used is not None:
            self.remaining = max(self.total - self.used, 0.0)
        if self.percent is None and self.used is not None and self.total:
            self.percent = round(min(self.used / self.total * 100.0, 100.0), 1)

    @property
    def remaining_percent(self) -> Optional[float]:
        """剩余百分比（0-100），用于告警分级。"""
        if self.frozen is not None:
            # 二元信号：冻结 -> 0，正常 -> 100
            return 0.0 if self.frozen else 100.0
        if self.percent is not None:
            return round(max(100.0 - self.percent, 0.0), 1)
        if self.remaining is not None and self.total:
            return round(max(self.remaining / self.total * 100.0, 0.0), 1)
        return None


@dataclass
class QuotaSnapshot:
    """某厂商某账号一次采集的结果（一家可能拆多个计划，如 ARK 的 Coding/Agent Plan）。"""

    vendor: str
    account_label: str
    plan_label: str = ""
    status: ProviderStatus = ProviderStatus.OK
    error: Optional[str] = None
    windows: list = field(default_factory=list)
    fetched_at: Optional[datetime] = None
    # 降级标注：本次采集失败，展示的是上次成功数据
    stale: bool = False
    stale_error: Optional[str] = None
    stale_since: Optional[datetime] = None
    # 数据实际归属的火山账号 ID（ARK 专用：用于检测多 profile 指向同一账号）
    viewer_account_id: Optional[str] = None
    # 卡片底部展示的灰字提示行（如「月度会员额度获取失败：Cookie 已过期」）
    notes: list = field(default_factory=list)


def to_number(value: Any) -> Optional[float]:
    """数值解析：兼容 int/float/字符串（含千分位逗号）；非法或空返回 None。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return float(text)
        except ValueError:
            return None
    return None


_FRACTION_RE = re.compile(r"\.(\d+)")


def parse_datetime(value: Any) -> Optional[datetime]:
    """时间解析：ISO8601/RFC3339 字符串（兼容 Z 后缀、1-9 位小数秒）或 epoch 秒/毫秒。

    无时区信息时按 UTC 处理；epoch 毫秒以 1e12 为界粗分。
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        num = float(value)
        if num > 1e12:  # 毫秒级 epoch
            num = num / 1000.0
        try:
            return datetime.fromtimestamp(num, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        match = _FRACTION_RE.search(text)
        if match and len(match.group(1)) != 6:
            # Python 3.9 的 fromisoformat 只接受 3 或 6 位小数，统一补/裁成 6 位
            digits = (match.group(1) + "000000")[:6]
            text = text[: match.start(1)] + digits + text[match.end(1):]
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None
