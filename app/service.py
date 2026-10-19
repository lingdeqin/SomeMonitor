"""轮询调度与降级：并发采集全部 Provider，维护 last-good 与 stale 标注。

纯 Python 逻辑（无 Qt 依赖），可单测；
QTimer 的接线在 ui/window.py 与 main.py 中完成。
"""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable, List, Optional

from app.model import ProviderStatus, QuotaSnapshot


class QuotaService:
    """聚合全部 Provider 的采集入口。"""

    def __init__(self, providers: list, now: Optional[Callable[[], datetime]] = None):
        self.providers = list(providers)
        self._now = now or datetime.now
        self.last_good = {}  # key -> QuotaSnapshot
        self.last_error = {}  # key -> 错误文本（当前失败中的账号）

    @staticmethod
    def _key(snapshot: QuotaSnapshot) -> str:
        return f"{snapshot.vendor}|{snapshot.account_label}|{snapshot.plan_label}"

    def refresh(self) -> List[QuotaSnapshot]:
        """并发采集全部 Provider；失败账号回填上次成功数据并标注 stale。"""
        results: List[QuotaSnapshot] = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(provider.fetch_all) for provider in self.providers]
            for future in futures:
                results.extend(future.result())

        merged: List[QuotaSnapshot] = []
        for snapshot in results:
            key = self._key(snapshot)
            if snapshot.status == ProviderStatus.OK:
                self.last_good[key] = snapshot
                self.last_error.pop(key, None)
                merged.append(snapshot)
            elif snapshot.status == ProviderStatus.ERROR:
                self.last_error[key] = snapshot.error or "获取失败"
                previous = self.last_good.get(key)
                if previous is not None:
                    merged.append(_stale_copy(previous, snapshot.error or "获取失败", self._now()))
                else:
                    merged.append(snapshot)
            else:  # UNCONFIGURED：中性展示，不参与 last-good
                merged.append(snapshot)
        return merged


def _stale_copy(previous: QuotaSnapshot, error: str, now: datetime) -> QuotaSnapshot:
    duplicated = copy.deepcopy(previous)
    duplicated.stale = True
    duplicated.stale_error = error
    duplicated.stale_since = now
    return duplicated
