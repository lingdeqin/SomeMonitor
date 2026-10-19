"""providers.build_providers 单元测试：列表式配置解析（vendor/visible/顺序）。"""
from __future__ import annotations

from app.providers import build_providers, providers_config_error
from app.providers.ark import ArkProvider
from app.providers.glm import GlmProvider
from app.providers.kimi import KimiProvider


def test_only_listed_vendors_are_built():
    config = {
        "providers": [
            {"vendor": "ark", "visible": True, "accounts": []},
            {"vendor": "glm", "visible": True, "accounts": []},
        ]
    }
    providers = build_providers(config, env={})
    assert [p.vendor_id for p in providers] == ["ark", "glm"]


def test_list_order_is_preserved():
    config = {
        "providers": [
            {"vendor": "kimi", "visible": True, "accounts": []},
            {"vendor": "ark", "visible": True, "accounts": []},
        ]
    }
    providers = build_providers(config, env={})
    assert [p.vendor_id for p in providers] == ["kimi", "ark"]


def test_visible_false_skips_provider():
    config = {"providers": [{"vendor": "kimi", "visible": False, "accounts": []}]}
    assert build_providers(config, env={}) == []


def test_missing_visible_defaults_to_shown():
    config = {"providers": [{"vendor": "kimi", "accounts": []}]}
    providers = build_providers(config, env={})
    assert [p.vendor_id for p in providers] == ["kimi"]


def test_unknown_vendor_is_skipped_with_hint(capsys):
    config = {
        "providers": [
            {"vendor": "not-a-vendor", "visible": True},
            {"vendor": "glm", "visible": True, "accounts": []},
        ]
    }
    providers = build_providers(config, env={})
    assert [p.vendor_id for p in providers] == ["glm"]
    assert "忽略未知的厂商配置项" in capsys.readouterr().out


def test_provider_receives_its_own_vendor_view():
    config = {
        "providers": [
            {"vendor": "ark", "visible": True, "transport": "openapi", "accounts": []}
        ]
    }
    provider = build_providers(config, env={})[0]
    assert isinstance(provider, ArkProvider)
    assert provider.provider_config() == {
        "vendor": "ark",
        "visible": True,
        "transport": "openapi",
        "accounts": [],
    }
    assert provider.transport({}) == "openapi"


def test_legacy_dict_providers_returns_empty_and_hint():
    config = {"providers": {"ark": {"transport": "auto"}, "kimi": {"accounts": []}}}
    assert build_providers(config, env={}) == []
    error = providers_config_error(config)
    assert error is not None
    assert "数组" in error
    assert "vendor" in error


def test_list_providers_has_no_config_error():
    config = {"providers": [{"vendor": "glm", "visible": True, "accounts": []}]}
    assert providers_config_error(config) is None


def test_provider_types_match_vendors():
    config = {
        "providers": [
            {"vendor": "glm", "visible": True, "accounts": []},
            {"vendor": "kimi", "visible": True, "accounts": []},
        ]
    }
    providers = build_providers(config, env={})
    assert isinstance(providers[0], GlmProvider)
    assert isinstance(providers[1], KimiProvider)
