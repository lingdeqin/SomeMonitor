"""DeepSeek 按量付费账户 Provider。

官方接口：GET https://api.deepseek.com/user/balance（Bearer API Key）
  响应：{is_available, balance_infos: [{currency, total_balance,
  granted_balance, topped_up_balance}]}——金额均为字符串；多币种数组
  （CNY/USD 可并存、不可相加）顺序不保证。

当日已用金额无官方接口，双通道：
  1. 差值记账（默认，估算）：轮询官方余额，累加同币种余额的下降差值；
     跨天归零、充值不计负、币种切换重置；持久化到 deepseek_ledger.json
  2. 精确通道（可选 user_token）：控制台非官方接口
     GET https://platform.deepseek.com/api/v0/usage/by_api_key/cost
     （Bearer userToken，浏览器 localStorage 获取，会过期）；
     任何失败自动回退差值记账估算并附灰字提示
"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from app.model import BalanceInfo, QuotaSnapshot, to_number
from app.providers.base import BaseProvider

BALANCE_URL = "https://api.deepseek.com/user/balance"
USAGE_COST_URL = "https://platform.deepseek.com/api/v0/usage/by_api_key/cost"
LEDGER_FILENAME = "deepseek_ledger.json"


def _get_json(url: str, credential: str, getter=None) -> Any:
    if getter is None:
        import httpx

        getter = httpx.get
    resp = getter(url, headers={"Authorization": f"Bearer {credential}"}, timeout=15)
    if resp.status_code == 401:
        raise RuntimeError("DeepSeek 接口鉴权失败（API Key 无效，status=401）")
    resp.raise_for_status()
    return resp.json()


def _select_balance_entry(entries: list, preferred: Optional[str]) -> Optional[dict]:
    if preferred:
        wanted = str(preferred).upper()
        for entry in entries:
            if str(entry.get("currency") or "").upper() == wanted:
                return entry
    if not entries:
        return None
    # 数组顺序不保证：默认取总余额最大项（金额无效排最后，并列取第一项）
    best = None
    best_total = None
    for entry in entries:
        total = to_number(entry.get("total_balance"))
        if total is None:
            total = float("-inf")
        if best is None or total > best_total:
            best, best_total = entry, total
    return best


def parse_balance(body: Any, preferred_currency: Optional[str] = None) -> BalanceInfo:
    """解析官方余额响应；金额为字符串，缺失/非法保持缺省而非置 0。"""
    info = BalanceInfo()
    if not isinstance(body, dict):
        return info
    entries = [
        entry for entry in body.get("balance_infos") or [] if isinstance(entry, dict)
    ]
    chosen = _select_balance_entry(entries, preferred_currency)
    if chosen is None:
        return info
    currency = str(chosen.get("currency") or "").strip()
    info.currency = currency or None
    info.total = to_number(chosen.get("total_balance"))
    info.granted = to_number(chosen.get("granted_balance"))
    info.topped_up = to_number(chosen.get("topped_up_balance"))
    return info


def apply_observation(
    entry: Optional[dict], total: float, currency: Optional[str], day: str
) -> dict:
    """差值记账单步：返回新 entry，不修改入参。

    首观测 / 跨天 / 币种切换 -> 重置（基准取当前余额，当日归零）；
    余额下降 -> 累加差值；余额上升（充值/到账）-> 只抬基准不计负。
    """
    if (
        not isinstance(entry, dict)
        or entry.get("currency") != currency
        or entry.get("day") != day
    ):
        return {"currency": currency, "day": day, "last_seen": total, "spent_today": 0.0}
    last_seen = to_number(entry.get("last_seen"))
    spent = to_number(entry.get("spent_today")) or 0.0
    if last_seen is None:
        return {"currency": currency, "day": day, "last_seen": total, "spent_today": spent}
    delta = last_seen - total
    if delta > 0:
        spent += delta
    return {"currency": currency, "day": day, "last_seen": total, "spent_today": spent}


class LedgerStore:
    """差值记账持久化：deepseek_ledger.json，key = credential 短哈希。

    path 为 None 时仅内存（单测用）；损坏/缺失文件视为无记账，
    以当前余额重新起步；写入走临时文件 + 原子替换避免半文件。
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = Path(path) if path is not None else None
        self._lock = threading.Lock()
        self._entries = self._load()

    def _load(self) -> dict:
        if self._path is None or not self._path.exists():
            return {}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    def update(self, key: str, total: float, currency: Optional[str], day: str) -> float:
        with self._lock:
            entry = apply_observation(self._entries.get(key), total, currency, day)
            self._entries[key] = entry
            self._flush()
            return entry["spent_today"]

    def _flush(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        tmp.replace(self._path)


def parse_usage_cost(body: Any, currency: Optional[str]) -> Optional[float]:
    """解析控制台当日消费：按展示币种过滤后对各桶 cost 求和。

    信封 {code, msg, data: {biz_code, biz_msg, biz_data}}——HTTP 200 也可能
    携带错误码（40002 缺 token / 40003 token 无效），code 非 0 视为失败；
    biz_data.data: [{currency, series: [{buckets: [{time, cost}]}]}]，
    cost 兼容数字/字符串；当日无消费求和为 0；形状不合法返回 None。
    """
    if not isinstance(body, dict):
        return None
    code = to_number(body.get("code"))
    if code is not None and int(code) != 0:
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        return None
    biz = data.get("biz_data")
    if not isinstance(biz, dict):
        return None
    groups = biz.get("data")
    if not isinstance(groups, list):
        return None
    total = 0.0
    for group in groups:
        if not isinstance(group, dict) or group.get("currency") != currency:
            continue
        for series in group.get("series") or []:
            if not isinstance(series, dict):
                continue
            for bucket in series.get("buckets") or []:
                if not isinstance(bucket, dict):
                    continue
                cost = to_number(bucket.get("cost"))
                if cost is not None:
                    total += cost
    return total


def _today_window(now: datetime) -> tuple:
    """本地当日零点的 epoch 秒与时区偏移秒（接口仅接受整小时偏移）。"""
    aware = now if now.tzinfo is not None else now.astimezone()
    midnight = aware.replace(hour=0, minute=0, second=0, microsecond=0)
    tz = int(midnight.utcoffset().total_seconds())
    tz -= tz % 3600
    return int(midnight.timestamp()), tz


def _credential_key(credential: str) -> str:
    return hashlib.sha256(credential.encode("utf-8")).hexdigest()[:16]


class DeepSeekProvider(BaseProvider):
    vendor_id = "deepseek"
    display_name = "DeepSeek"
    env_names = ("DEEPSEEK_API_KEY",)
    credential_keys = ("api_key",)

    def __init__(
        self,
        config: dict,
        env: Optional[dict] = None,
        now: Optional[Callable[[], datetime]] = None,
        data_dir=None,
        getter: Optional[Callable] = None,
    ):
        super().__init__(config, env=env, now=now)
        ledger_path = Path(data_dir) / LEDGER_FILENAME if data_dir else None
        self._ledger = LedgerStore(ledger_path)
        self._getter = getter

    def resolve_user_token(self, account: dict) -> Optional[str]:
        value = account.get("user_token")
        if value:
            return str(value)
        return self.env_get("DEEPSEEK_USER_TOKEN")

    def fetch_account(self, account: dict, credential: str) -> list:
        body = _get_json(BALANCE_URL, credential, self._getter)
        balance = parse_balance(body, account.get("currency"))
        if balance.total is None:
            raise RuntimeError("DeepSeek 余额响应中无有效币种项")

        snapshot = QuotaSnapshot(
            vendor=self.vendor_id, account_label=self.account_label(account)
        )
        # 记账先于精确通道：精确值仅在展示层覆盖，token 失效当日估算仍可用
        day = self._now().strftime("%Y-%m-%d")
        balance.today_spent = self._ledger.update(
            _credential_key(credential), balance.total, balance.currency, day
        )
        balance.today_spent_estimated = True

        token = self.resolve_user_token(account)
        if token:
            precise = self._fetch_today_cost(token, balance.currency)
            if precise is not None:
                balance.today_spent = precise
                balance.today_spent_estimated = False
            else:
                snapshot.notes.append(
                    "今日精确消费获取失败：userToken 可能已过期，"
                    "请在浏览器 localStorage 重新复制（步骤见 README）"
                )
        snapshot.balance = balance
        return [snapshot]

    def _fetch_today_cost(self, token: str, currency: Optional[str]) -> Optional[float]:
        start, tz = _today_window(self._now())
        params = {"start": start, "end": start + 86400, "tz": tz}
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "x-client-platform": "web",
        }
        getter = self._getter
        if getter is None:
            import httpx

            getter = httpx.get
        try:
            resp = getter(USAGE_COST_URL, headers=headers, params=params, timeout=15)
            if resp.status_code != 200:
                return None
            body = resp.json()
        except Exception:
            return None
        return parse_usage_cost(body, currency)
