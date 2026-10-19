"""app.config 单元测试：JSONC 解析 / 模板生成 / 深合并 / 状态持久化。"""
from __future__ import annotations

from app.config import (
    CONFIG_TEMPLATE,
    DEFAULT_CONFIG,
    DEFAULT_STATE,
    default_config_path,
    default_state_path,
    deep_merge,
    ensure_default_config,
    load_config,
    load_state,
    parse_jsonc,
    save_state,
)


def test_parse_jsonc_comments_and_trailing_commas():
    text = """
    {
      // 行注释
      "a": 1, /* 块注释 */
      "b": [1, 2, 3,],
      "c": "值",
    }
    """
    assert parse_jsonc(text) == {"a": 1, "b": [1, 2, 3], "c": "值"}


def test_parse_jsonc_preserves_urls_in_strings():
    # "https://" 里的 // 不能被误当注释剥离
    text = '{"url": "https://api.example.com/v1", "b": 2,}'
    data = parse_jsonc(text)
    assert data["url"] == "https://api.example.com/v1"
    assert data["b"] == 2


def test_parse_jsonc_trailing_comma_before_comment():
    # 尾随逗号后跟注释再闭合（", // 注释 ]"）同样合法
    text = """
    {
      "providers": [
        { "vendor": "ark" },
        // 未购买的厂商注释掉
      ],
      "x": 1, /* 块注释 */
    }
    """
    assert parse_jsonc(text) == {"providers": [{"vendor": "ark"}], "x": 1}


def test_parse_jsonc_preserves_brace_chars_in_strings():
    # 字符串内的 ", }" 不能被误当尾随逗号剔除
    text = '{"weird": "a, }b", "x": 1}'
    assert parse_jsonc(text) == {"weird": "a, }b", "x": 1}


def test_parse_jsonc_handles_escapes_and_bom():
    text = '﻿{"say": "it \\"works\\""}'
    assert parse_jsonc(text) == {"say": 'it "works"'}


def test_missing_config_returns_defaults(tmp_path):
    assert load_config(tmp_path / "none.jsonc") == DEFAULT_CONFIG


def test_corrupt_config_returns_defaults(tmp_path):
    path = tmp_path / "bad.jsonc"
    path.write_text("{oops", encoding="utf-8")
    assert load_config(path) == DEFAULT_CONFIG


def test_non_object_config_returns_defaults(tmp_path):
    path = tmp_path / "arr.jsonc"
    path.write_text("[1, 2]", encoding="utf-8")
    assert load_config(path) == DEFAULT_CONFIG


def test_config_override_merges_over_defaults(tmp_path):
    path = tmp_path / "config.jsonc"
    path.write_text(
        """
        {
          // 只改两个值，其余走默认
          "refresh_seconds": 5,
          "providers": [
            { "vendor": "ark", "transport": "openapi", "accounts": [] }
          ]
        }
        """,
        encoding="utf-8",
    )
    cfg = load_config(path)
    assert cfg["refresh_seconds"] == 5
    # providers 为数组：用户列表整体替换默认列表（顺序即卡片顺序）
    assert cfg["providers"] == [
        {"vendor": "ark", "transport": "openapi", "accounts": []}
    ]
    assert cfg["opacity"] == 0.9


def test_default_providers_is_visible_list():
    providers = DEFAULT_CONFIG["providers"]
    assert isinstance(providers, list)
    assert [item["vendor"] for item in providers] == [
        "opencode-go", "ark", "glm", "kimi", "deepseek",
    ]
    assert all(item.get("visible") is True for item in providers)


def test_template_providers_parse_as_list():
    data = parse_jsonc(CONFIG_TEMPLATE)
    assert isinstance(data["providers"], list)
    assert data["providers"][0]["vendor"] == "opencode-go"
    assert {item["vendor"] for item in data["providers"]} == {
        "opencode-go", "ark", "glm", "kimi", "deepseek",
    }


def test_template_documents_deepseek_user_token():
    assert '"vendor": "deepseek"' in CONFIG_TEMPLATE
    assert '"user_token"' in CONFIG_TEMPLATE
    assert '"currency"' in CONFIG_TEMPLATE


def test_balance_row_layout_defaults_align_with_row_layout():
    assert DEFAULT_CONFIG["balance_row_layout"] == {"name_width": 52}
    assert (
        DEFAULT_CONFIG["balance_row_layout"]["name_width"]
        == DEFAULT_CONFIG["row_layout"]["name_width"]
    )
    data = parse_jsonc(CONFIG_TEMPLATE)
    assert data["balance_row_layout"] == {"name_width": 52}


def test_ensure_default_config_writes_template_once(tmp_path):
    path = tmp_path / "config.jsonc"
    assert ensure_default_config(path) is True
    assert ensure_default_config(path) is False  # 已存在时绝不覆盖
    assert load_config(path) == DEFAULT_CONFIG  # 模板值与默认值一致


def test_state_roundtrip(tmp_path):
    path = tmp_path / "state.json"
    state = {
        "window": {"x": 11, "y": 22},
        "opacity": 0.55,
        "always_on_top": False,
        "hidden_window_types": ["monthly"],
    }
    save_state(path, state)
    assert load_state(path) == state


def test_state_missing_returns_defaults(tmp_path):
    assert load_state(tmp_path / "none.json") == DEFAULT_STATE


def test_deep_merge_nested_dict():
    merged = deep_merge({"a": {"b": 1, "c": 2}}, {"a": {"c": 3, "d": 4}})
    assert merged == {"a": {"b": 1, "c": 3, "d": 4}}


def test_default_paths():
    assert default_config_path().name == "config.jsonc"
    assert default_state_path().name == "state.json"
