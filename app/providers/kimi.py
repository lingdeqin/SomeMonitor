"""Kimi for Coding 额度 Provider。

端点：GET https://api.kimi.com/coding/v1/usages（官方接口，Bearer sk-kimi-*）
响应已知坑（design.md D6 / quotas crate 逆向）：
  - 数值字段是字符串
  - 周限在 usage（resetTime 为 PascalCase；used 常缺省 -> limit - remaining 推导）
  - 5h 窗口在 limits[]（window.duration=300 且 timeUnit 含 MINUTE）
  - totalQuota 是月度会员额度「冻结」二元信号：used 存在且 >0 即冻结，
    绝不当作百分比绘制；服务端不返回重置时间
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
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

ENDPOINT = "https://api.kimi.com/coding/v1/usages"

# 月度会员共享额度（非官方接口）：优先用 refresh_token 自动续期（推荐），
# 或手动粘贴短期 access token；失败时卡片显示灰字提示，不影响周限 / 5h
MEMBERSHIP_URL = (
    "https://www.kimi.com/apiv2/"
    "kimi.gateway.membership.v2.MembershipService/GetSubscriptionStats"
)
REFRESH_URL = "https://auth.kimi.com/api/account.gateway.v1.AuthService/RefreshToken"


def _first_present(mapping: dict, keys: tuple) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


class KimiProvider(BaseProvider):
    vendor_id = "kimi"
    display_name = "Kimi"
    env_names = ("KIMI_FOR_CODING_API_KEY", "KIMI_CODING_API_KEY", "KIMI_API_KEY")

    def __init__(self, config, env=None, now=None):
        super().__init__(config, env=env, now=now)
        self._cached_access = None
        self._cached_access_exp = 0

    def discover_cli(self) -> Optional[str]:
        """从 Kimi Code CLI 登录态发现凭证。

        新版：%USERPROFILE%\\.kimi-code\\credentials\\*.json
        旧版：%USERPROFILE%\\.kimi\\credentials\\kimi-code.json
        """
        home = Path.home()
        credential_dirs = [
            home / ".kimi-code" / "credentials",
            home / ".kimi" / "credentials",
        ]
        files = []
        for directory in credential_dirs:
            if directory.is_dir():
                files.extend(sorted(directory.glob("*.json")))
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(data, dict):
                continue
            for key in ("api_key", "apiKey", "token", "access_token"):
                value = data.get(key)
                if value:
                    return str(value)
        return None

    def fetch_account(self, account: dict, credential: str) -> list:
        body = _get_json(ENDPOINT, credential)
        snapshots = parse_usages(body, self.account_label(account))
        token = self._get_monthly_token(account)
        if token:
            monthly = _fetch_monthly_membership(token)
            if monthly is not None:
                snapshots[0].windows.append(monthly)
                return snapshots
        refresh = self.resolve_refresh_token(account)
        if refresh:
            expiry = _cookie_expiry_text(refresh)
            hint = "月度会员额度获取失败：refresh_token 无效或已过期"
            if expiry:
                hint += f"（本地解码有效期至 {expiry}）"
            hint += "，请在浏览器 localStorage 重新复制 refresh_token"
            snapshots[0].notes.append(hint)
        elif token:
            expiry = _cookie_expiry_text(token)
            hint = "月度会员额度获取失败：凭证可能已过期"
            if expiry:
                hint += f"（本地解码有效期至 {expiry}）"
            hint += "，请在浏览器 Network 面板复制 GetSubscriptionStats 请求头 authorization 的最新值"
            snapshots[0].notes.append(hint)
        return snapshots

    def resolve_kimi_auth(self, account: dict) -> Optional[str]:
        """手动短期凭证：账号 kimi_auth > 环境变量 KIMI_AUTH_TOKEN（裸 JWT 或 Bearer xxx）。"""
        value = account.get("kimi_auth")
        if value:
            return str(value)
        return self.env_get("KIMI_AUTH_TOKEN")

    def resolve_refresh_token(self, account: dict) -> Optional[str]:
        """长效凭证：账号 refresh_token > 环境变量 KIMI_REFRESH_TOKEN（推荐，约 90 天有效）。"""
        value = account.get("refresh_token")
        if value:
            return str(value)
        return self.env_get("KIMI_REFRESH_TOKEN")

    def _get_monthly_token(self, account: dict) -> Optional[str]:
        """月度凭证解析：refresh_token 自动续期（优先，软旋转可安全重复使用），
        内存缓存 access token（过期前 2 分钟内不重复换）；无 refresh_token 时退回手动 kimi_auth。
        """
        import time

        refresh = self.resolve_refresh_token(account)
        if not refresh:
            return self.resolve_kimi_auth(account)
        now_ts = time.time()
        if self._cached_access and self._cached_access_exp > now_ts + 120:
            return self._cached_access
        access, exp = _refresh_access_token(refresh)
        if access:
            self._cached_access = access
            self._cached_access_exp = exp or (now_ts + 600)
            return access
        return None


def _get_json(url: str, credential: str) -> dict:
    import httpx

    resp = httpx.get(url, headers={"Authorization": f"Bearer {credential}"}, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _is_five_hour_window(window: dict) -> bool:
    duration = to_number(window.get("duration"))
    unit = str(window.get("timeUnit") or window.get("time_unit") or "").upper()
    if duration is None:
        return False
    if "MINUTE" in unit:
        return duration == 300
    if "HOUR" in unit:
        return duration == 5
    return False


def parse_usages(body: Any, label: str = "默认") -> list:
    """解析 Kimi /coding/v1/usages 响应。"""
    snapshot = QuotaSnapshot(vendor="kimi", account_label=label)
    if not isinstance(body, dict):
        return [snapshot]
    user = body.get("user")
    if isinstance(user, dict):
        membership = user.get("membership")
        if isinstance(membership, dict) and membership.get("level"):
            snapshot.plan_label = str(membership["level"])

    # 周限（usage）
    usage = body.get("usage")
    if isinstance(usage, dict) and to_number(usage.get("limit")) is not None:
        window = QuotaWindow(
            type=WindowType.WEEKLY,
            used=to_number(usage.get("used")),
            total=to_number(usage.get("limit")),
            remaining=to_number(usage.get("remaining")),
            reset_at=parse_datetime(_first_present(usage, ("resetTime", "reset_at", "reset"))),
        )
        window.ensure_derived()
        snapshot.windows.append(window)

    # 5 小时窗口（limits[]）
    for entry in body.get("limits") or []:
        if not isinstance(entry, dict):
            continue
        window_meta = entry.get("window")
        if not isinstance(window_meta, dict) or not _is_five_hour_window(window_meta):
            continue
        detail = entry.get("detail")
        if not isinstance(detail, dict):
            continue
        window = QuotaWindow(
            type=WindowType.FIVE_H,
            used=to_number(detail.get("used")),
            total=to_number(detail.get("limit")),
            remaining=to_number(detail.get("remaining")),
            reset_at=parse_datetime(
                _first_present(detail, ("resetTime", "reset_at", "reset"))
            ),
        )
        window.ensure_derived()
        snapshot.windows.append(window)

    # 月度会员额度冻结二元信号（totalQuota）
    total_quota = body.get("totalQuota")
    if isinstance(total_quota, dict):
        has_signal = ("used" in total_quota) or ("remaining" in total_quota)
        if has_signal:
            used = to_number(total_quota.get("used"))
            frozen = used is not None and used > 0
            snapshot.windows.append(
                QuotaWindow(type=WindowType.MONTHLY_FREEZE, frozen=frozen)
            )

    return [snapshot]


def _cookie_expiry_text(token: str) -> Optional[str]:
    """本地解码 kimi_auth JWT 的 exp，返回 'YYYY-MM-DD HH:MM'（本地时区）；解码失败返回 None。

    新版 access token 寿命可能只有几小时，日期之外必须展示到分钟。
    """
    import base64

    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        if not exp:
            return None
        return (
            datetime.fromtimestamp(int(exp), tz=timezone.utc)
            .astimezone()
            .strftime("%Y-%m-%d %H:%M")
        )
    except Exception:
        return None


def _refresh_access_token(refresh_token: str) -> tuple:
    """用 refresh_token 换新 access token；返回 (token, exp_epoch) 或 (None, None)。

    实测（2026-10-14）：RefreshToken 接口为软旋转——旧 refresh_token 换新后
    仍可用，浏览器与悬浮窗可共用同一条凭证链、互不失效。
    """
    import base64

    import httpx

    try:
        resp = httpx.post(REFRESH_URL, json={"refresh_token": refresh_token}, timeout=15)
        if resp.status_code != 200:
            return None, None
        access = resp.json().get("accessToken")
        if not access:
            return None, None
        exp = None
        try:
            payload = access.split(".")[1]
            payload += "=" * (-len(payload) % 4)
            exp = json.loads(base64.urlsafe_b64decode(payload)).get("exp")
        except Exception:
            pass
        return access, exp
    except Exception:
        return None, None


def _auth_header_value(token: str) -> str:
    """kimi_auth 值兼容两种粘贴形式：裸 JWT 或完整 'Bearer xxx' 请求头值。"""
    if token[:7].lower() == "bearer ":
        return token
    return f"Bearer {token}"


def _fetch_monthly_membership(token: str) -> Optional[QuotaWindow]:
    """调用非官方会员接口获取月度共享额度；任何失败返回 None（由调用方加提示）。

    Kimi 网页端已把会话凭证从 kimi-auth Cookie 迁移到 Authorization 请求头
    （Connect RPC 风格，2026-10 实测）；凭证为浏览器中该接口请求头里的
    authorization 值。
    """
    import httpx

    try:
        resp = httpx.post(
            MEMBERSHIP_URL,
            headers={
                "Authorization": _auth_header_value(token),
                "Content-Type": "application/json",
            },
            json={},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return _parse_membership_stats(resp.json())
    except Exception:
        return None


def _parse_membership_stats(body: Any) -> Optional[QuotaWindow]:
    """解析 GetSubscriptionStats：amount_used_ratio 为 0-1 比率，归一化为百分比。"""
    if not isinstance(body, dict):
        return None
    balance = body.get("subscription_balance") or body.get("subscriptionBalance")
    if not isinstance(balance, dict):
        return None
    ratio = to_number(
        _first_present(balance, ("amount_used_ratio", "amountUsedRatio"))
    )
    if ratio is None:
        return None
    percent = round(ratio * 100.0, 2) if ratio <= 1.0 else ratio
    expire = parse_datetime(
        _first_present(balance, ("expire_time", "expireTime"))
    )
    return QuotaWindow(type=WindowType.MONTHLY, percent=percent, reset_at=expire)
