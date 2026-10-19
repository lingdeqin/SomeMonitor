"""providers.build_providers 单元测试：列表式配置解析（vendor/visible/顺序）。"""
from __future__ import annotations

from app.model import ProviderStatus
from app.providers import build_providers, providers_config_error
from app.providers.ark import ArkProvider
from app.providers.deepseek import DeepSeekProvider
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


def test_deepseek_provider_built_with_data_dir(tmp_path):
    config = {"providers": [{"vendor": "deepseek", "visible": True, "accounts": []}]}
    providers = build_providers(config, env={}, data_dir=tmp_path)
    assert [p.vendor_id for p in providers] == ["deepseek"]
    assert isinstance(providers[0], DeepSeekProvider)
    assert providers[0]._ledger._path == tmp_path / "deepseek_ledger.json"


def test_deepseek_without_data_dir_keeps_ledger_in_memory():
    config = {"providers": [{"vendor": "deepseek", "visible": True, "accounts": []}]}
    provider = build_providers(config, env={})[0]
    assert provider._ledger._path is None


def test_deepseek_visible_false_skipped():
    config = {"providers": [{"vendor": "deepseek", "visible": False, "accounts": []}]}
    assert build_providers(config, env={}) == []


def test_deepseek_unconfigured_without_credential():
    config = {"providers": [{"vendor": "deepseek", "visible": True, "accounts": []}]}
    provider = build_providers(config, env={})[0]
    snapshots = provider.fetch_all()
    assert snapshots[0].vendor == "deepseek"
    assert snapshots[0].status == ProviderStatus.UNCONFIGURED
