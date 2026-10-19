"""配置加载：config.jsonc（用户配置，JSONC）+ state.json（运行时状态）。

config.jsonc 由用户手工编辑，支持 // 与 /* */ 注释及尾随逗号；
首次运行生成带中文注释的模板，此后 App 只读、绝不覆盖。
state.json 由 App 读写（窗口位置、菜单调整的不透明度/置顶）。
取值优先级：state.json > config.jsonc > 内置默认。
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from typing import Any, Union

DEFAULT_CONFIG: dict = {
    "refresh_seconds": 60,
    "opacity": 0.9,
    "always_on_top": True,
    # 剩余百分比告警阈值：<=30 黄，<=10 红
    "warn_percent": 30,
    "danger_percent": 10,
    # 卡片宽度（像素）；窗口行各段宽度见 row_layout
    "card_width": 380,
    "row_layout": {
        "name_width": 52,
        "percent_width": 48,
        "usage_width": 88,
        "reset_width": 104,
    },
    # 各厂商配置：数组顺序即卡片顺序；
    # visible 为 false 或未列出的厂商不采集、不显示（适合没买套餐的厂商）
    "providers": [
        {"vendor": "opencode-go", "visible": True, "accounts": []},
        {"vendor": "ark", "visible": True, "transport": "auto", "accounts": []},
        {"vendor": "glm", "visible": True, "accounts": []},
        {"vendor": "kimi", "visible": True, "accounts": []},
    ],
}

DEFAULT_STATE: dict = {
    "window": {"x": None, "y": None},
    "opacity": None,
    "always_on_top": None,
    # 被隐藏的额度窗口类型（WindowType value 列表，全局生效）
    "hidden_window_types": [],
}

CONFIG_TEMPLATE = r"""{
  // 自动刷新间隔（秒）
  "refresh_seconds": 60,

  // 整窗不透明度（0.3 - 1.0）。右键菜单里调节的结果存 state.json，优先生效
  "opacity": 0.9,

  // 始终置顶
  "always_on_top": true,

  // 剩余百分比告警阈值：<=30 黄色，<=10 红色
  "warn_percent": 30,
  "danger_percent": 10,

  // 卡片宽度（像素）
  "card_width": 380,

  // 窗口行各段显示宽度（像素）：类型名 / 百分比 / 已用总量 / 重置时间；
  // 进度条占据该行剩余空间
  "row_layout": {
    "name_width": 52,
    "percent_width": 48,
    "usage_width": 88,
    "reset_width": 104
  },

  // 各厂商配置：数组顺序即卡片顺序。
  // "visible": false 或整项删除 -> 该厂商不采集、不显示（适合没买套餐的厂商）。
  // 凭证优先级：账号里的 api_key > 环境变量 > 本机 CLI 登录态（零配置）
  "providers": [
    {
      // OpenCode Go：环境变量 OPENCODE_GO_API_KEY / OPENCODE_API_KEY，
      // 或 opencode CLI 登录态（~\.config\opencode\auth.json）
      // 例：{ "label": "主号", "api_key": "oc_sk_..." }
      "vendor": "opencode-go",
      "visible": true,
      "accounts": []
    },
    {
      // 火山方舟：transport 可选 "arkcli" / "openapi" / "auto"（默认）。
      // 多账号推荐 IAM AK/SK 直连：{ "label": "B", "access_key_id": "AKLTxxx",
      //   "secret_access_key": "xxx" }；或引用 arkcli profile（见 README）。
      // 注意：ark- 开头的 API Key 不能直连控制面（实测 400）。
      "vendor": "ark",
      "visible": true,
      "transport": "auto",
      "accounts": []
    },
    {
      // 智谱 GLM：国内 bigmodel.cn；国际版加 "channel": "global"
      // 例：{ "label": "国内号", "api_key": "..." }
      "vendor": "glm",
      "visible": true,
      "accounts": []
    },
    {
      // Kimi：Key 在 kimi.com/code/console 创建（sk-kimi-* 开头）
      // 月度会员额度建议配 "refresh_token"（约 90 天有效，自动续期，见 README）
      "vendor": "kimi",
      "visible": true,
      "accounts": []
    }
  ]
}
"""


def parse_jsonc(text: str) -> Any:
    """解析 JSONC：剥离 // 与 /* */ 注释、容忍尾随逗号。

    单趟扫描且对字符串字面量逐字保留——"https://..." 里的 // 不会被误当注释，
    字符串内的 ", }" 也不会被误当尾随逗号剔除。
    """
    text = text.lstrip("\ufeff")
    n = len(text)
    out = []
    i = 0
    while i < n:
        ch = text[i]
        if ch == '"':
            out.append(ch)
            i += 1
            while i < n:
                c = text[i]
                out.append(c)
                i += 1
                if c == "\\" and i < n:
                    out.append(text[i])
                    i += 1
                elif c == '"':
                    break
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "/":
            i += 2
            while i < n and text[i] not in "\r\n":
                i += 1
            continue
        if ch == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2
            continue
        if ch == ",":
            j = i + 1
            # 跨过空白与注释后再判断是否尾随逗号（", // 注释 ]" 同样合法）
            while j < n:
                c2 = text[j]
                if c2 in " \t\r\n":
                    j += 1
                elif c2 == "/" and j + 1 < n and text[j + 1] == "/":
                    j += 2
                    while j < n and text[j] not in "\r\n":
                        j += 1
                elif c2 == "/" and j + 1 < n and text[j + 1] == "*":
                    j += 2
                    while j + 1 < n and not (text[j] == "*" and text[j + 1] == "/"):
                        j += 1
                    j += 2
                else:
                    break
            if j < n and text[j] in "}]":
                i += 1
                continue
        out.append(ch)
        i += 1
    return json.loads("".join(out))


def deep_merge(base: dict, override: dict) -> dict:
    """深合并：override 覆盖 base，嵌套 dict 递归合并。"""
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(path: Union[str, Path]) -> dict:
    """加载用户配置（JSONC）；文件不存在 / 损坏 / 非对象时返回默认配置。"""
    file_path = Path(path)
    if not file_path.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        data = parse_jsonc(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_CONFIG)
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_CONFIG)
    return deep_merge(DEFAULT_CONFIG, data)


def ensure_default_config(path: Union[str, Path]) -> bool:
    """config.jsonc 不存在时生成注释模板；已存在则返回 False（绝不覆盖用户配置）。"""
    file_path = Path(path)
    if file_path.exists():
        return False
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(CONFIG_TEMPLATE, encoding="utf-8")
    return True


def load_state(path: Union[str, Path]) -> dict:
    file_path = Path(path)
    if not file_path.exists():
        return copy.deepcopy(DEFAULT_STATE)
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return copy.deepcopy(DEFAULT_STATE)
    if not isinstance(data, dict):
        return copy.deepcopy(DEFAULT_STATE)
    return deep_merge(DEFAULT_STATE, data)


def save_state(path: Union[str, Path], state: dict) -> None:
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _app_dir() -> Path:
    """默认配置锚定目录：打包后为 exe 所在目录，源码运行为仓库根。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def default_config_path() -> Path:
    """默认用户配置路径。"""
    return _app_dir() / "config.jsonc"


def default_state_path() -> Path:
    """默认运行时状态路径。"""
    return _app_dir() / "state.json"
