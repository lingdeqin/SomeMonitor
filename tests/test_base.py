"""providers.base 单元测试：凭证三级解析链与错误隔离。"""
from __future__ import annotations

from app.model import ProviderStatus, QuotaSnapshot
from app.providers.base import BaseProvider


class FakeProvider(BaseProvider):
    vendor_id = "fake"
    display_name = "Fake"
    env_names = ("FAKE_API_KEY",)

    def __init__(self, config, env=None, cli_value=None, fail_labels=(), **kwargs):
        super().__init__(config, env=env, **kwargs)
        self.cli_value = cli_value
        self.fail_labels = set(fail_labels)

    def discover_cli(self):
        return self.cli_value

    def fetch_account(self, account, credential):
        if self.account_label(account) in self.fail_labels:
            raise RuntimeError("boom")
        return [
            QuotaSnapshot(
                vendor=self.vendor_id, account_label=self.account_label(account)
            )
        ]


def _provider(env=None, cli_value=None, fail_labels=(), config=None):
    return FakeProvider(config or {"providers": {}}, env=env, cli_value=cli_value,
                        fail_labels=fail_labels)


def test_credential_priority_explicit_over_env_over_cli():
    provider = _provider(env={"FAKE_API_KEY": "from-env"}, cli_value="from-cli")
    assert provider.resolve_credential({"api_key": "from-config"}) == "from-config"


def test_credential_env_when_no_explicit():
    provider = _provider(env={"FAKE_API_KEY": "from-env"}, cli_value="from-cli")
    assert provider.resolve_credential({}) == "from-env"


def test_credential_cli_discovery_fallback():
    provider = _provider(env={}, cli_value="from-cli")
    assert provider.resolve_credential({}) == "from-cli"


def test_credential_all_miss_returns_unconfigured():
    provider = _provider(env={}, cli_value=None)
    snapshots = provider.fetch_all()
    assert len(snapshots) == 1
    assert snapshots[0].status == ProviderStatus.UNCONFIGURED
    assert snapshots[0].fetched_at is not None


def test_fetch_all_isolates_account_failures():
    config = {
        "providers": {
            "fake": {"accounts": [{"label": "好"}, {"label": "坏"}]}
        }
    }
    provider = _provider(env={"FAKE_API_KEY": "k"}, fail_labels={"坏"}, config=config)
    snapshots = provider.fetch_all()
    assert len(snapshots) == 2
    statuses = {s.account_label: s.status for s in snapshots}
    assert statuses["好"] == ProviderStatus.OK
    assert statuses["坏"] == ProviderStatus.ERROR
    assert snapshots[1].error == "boom"


def test_empty_accounts_yields_implicit_default_account():
    provider = _provider(env={"FAKE_API_KEY": "k"},
                         config={"providers": {"fake": {"accounts": []}}})
    assert provider.accounts() == [{}]
    assert provider.account_label({}) == "默认"


def test_accounts_labels_read_from_config():
    provider = _provider(config={"providers": {"fake": {"accounts": [{"label": "主号"}]}}})
    accounts = provider.accounts()
    assert provider.account_label(accounts[0]) == "主号"
