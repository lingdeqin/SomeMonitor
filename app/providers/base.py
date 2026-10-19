"""Provider 基类：凭证三级解析链、账号枚举、错误隔离。

凭证解析优先级（命中即止）：
  1. 账号显式配置（config.jsonc 中该账号的 api_key 等字段）
  2. 环境变量（各 Provider 声明 env_names）
  3. 本机 CLI 登录态自动发现（子类覆写 discover_cli）
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, Optional

from app.model import ProviderStatus, QuotaSnapshot


class BaseProvider:
    """所有厂商 Provider 的基类。"""

    vendor_id: str = ""
    display_name: str = ""
    env_names: tuple = ()
    credential_keys: tuple = ("api_key",)
    # ARK 这类可走本机 CLI 子进程的厂商不需要凭证也能采集
    requires_credential: bool = True

    def __init__(
        self,
        config: dict,
        env: Optional[dict] = None,
        now: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config or {}
        self._env = os.environ if env is None else env
        self._now = now or datetime.now

    # ---------- 配置 ----------

    def provider_config(self) -> dict:
        providers = self.config.get("providers") or {}
        cfg = providers.get(self.vendor_id)
        return cfg if isinstance(cfg, dict) else {}

    def accounts(self) -> list:
        """账号列表；为空时返回一个隐式默认账号（走环境变量 / CLI 登录态）。"""
        accounts = self.provider_config().get("accounts")
        if isinstance(accounts, list) and accounts:
            return list(accounts)
        return [{}]

    def account_label(self, account: dict) -> str:
        return str(account.get("label") or "默认")

    # ---------- 凭证三级解析 ----------

    def env_get(self, *names) -> Optional[str]:
        for name in names or self.env_names:
            value = self._env.get(name)
            if value:
                return value
        return None

    def resolve_credential(self, account: dict) -> Optional[str]:
        # 1. 账号显式配置
        for key in self.credential_keys:
            value = account.get(key)
            if value:
                return str(value)
        # 2. 环境变量
        found = self.env_get()
        if found:
            return found
        # 3. CLI 登录态自动发现
        try:
            return self.discover_cli()
        except Exception:
            return None

    def discover_cli(self) -> Optional[str]:
        """子类覆写：从本机 CLI 的登录凭据文件中发现凭证。"""
        return None

    # ---------- 采集 ----------

    def fetch_account(self, account: dict, credential: str) -> list:
        """采集单账号，返回 QuotaSnapshot 列表（子类实现）。"""
        raise NotImplementedError

    def fetch_all(self) -> list:
        """并发采集全部账号；单账号失败/未配置不影响其他账号。"""
        snapshots = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(self._fetch_one_safe, account) for account in self.accounts()]
            for future in futures:
                snapshots.extend(future.result())
        return snapshots

    def _fetch_one_safe(self, account: dict) -> list:
        label = self.account_label(account)
        credential = self.resolve_credential(account)
        if self.requires_credential and not credential:
            return [
                QuotaSnapshot(
                    vendor=self.vendor_id,
                    account_label=label,
                    status=ProviderStatus.UNCONFIGURED,
                    fetched_at=self._now(),
                )
            ]
        try:
            result = self.fetch_account(account, credential or "")
            for snapshot in result:
                if snapshot.fetched_at is None:
                    snapshot.fetched_at = self._now()
            if not result:
                return [
                    QuotaSnapshot(
                        vendor=self.vendor_id, account_label=label, fetched_at=self._now()
                    )
                ]
            return result
        except Exception as exc:  # 单家失败隔离
            return [
                QuotaSnapshot(
                    vendor=self.vendor_id,
                    account_label=label,
                    status=ProviderStatus.ERROR,
                    error=str(exc),
                    fetched_at=self._now(),
                )
            ]
