"""Provider 注册表。"""
from __future__ import annotations

import sys
from typing import Optional

from app.providers.base import BaseProvider

PROVIDER_CLASSES = (
    "OpenCodeGoProvider",
    "ArkProvider",
    "GlmProvider",
    "KimiProvider",
)

LEGACY_PROVIDERS_HINT = (
    "配置格式已升级：config.jsonc 中 providers 需改为数组形式，"
    '每项含 "vendor"（厂商）与 "visible"（是否显示）字段，'
    "数组顺序即卡片顺序；示例见 config.example.jsonc 或 README"
)


def _load_classes():
    from app.providers.opencode_go import OpenCodeGoProvider
    from app.providers.ark import ArkProvider
    from app.providers.glm import GlmProvider
    from app.providers.kimi import KimiProvider

    return (OpenCodeGoProvider, ArkProvider, GlmProvider, KimiProvider)


def providers_config_error(config: dict) -> Optional[str]:
    """检测旧版按厂商字典的 providers 配置，返回中文迁移提示；新格式返回 None。"""
    providers = (config or {}).get("providers")
    if isinstance(providers, dict):
        return LEGACY_PROVIDERS_HINT
    return None


def build_providers(config: dict, env: Optional[dict] = None) -> list:
    """按 providers 数组实例化 Provider：数组顺序即返回顺序。

    visible 为 false 或未列出的厂商不实例化；未知 vendor 跳过并提示；
    旧字典格式视为配置错误，返回空列表（由界面展示迁移提示）。
    """
    if providers_config_error(config):
        return []
    providers = (config or {}).get("providers")
    if not isinstance(providers, list):
        providers = []

    classes = {cls.vendor_id: cls for cls in _load_classes()}
    instances = []
    for item in providers:
        if not isinstance(item, dict):
            continue
        vendor = str(item.get("vendor") or "").strip()
        cls = classes.get(vendor)
        if cls is None:
            if sys.stdout:  # windowed 打包下 stdout 为 None，print 会崩
                print(
                    f"忽略未知的厂商配置项：{vendor or '（空）'}；"
                    f"支持的厂商：{' / '.join(classes)}"
                )
            continue
        if item.get("visible", True) is False:
            continue
        # Provider 内部仍按 {vendor: 项} 读取配置（BaseProvider 接口不变）
        per_vendor_config = dict(config or {})
        per_vendor_config["providers"] = {vendor: item}
        instances.append(cls(per_vendor_config, env=env))
    return instances


__all__ = [
    "build_providers",
    "providers_config_error",
    "BaseProvider",
    "PROVIDER_CLASSES",
]
