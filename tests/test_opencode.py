"""Tests for the OpenCode Zen provider.

Covers:
1. API key resolution
2. Fetch lifecycle (workspace discovery + mocked HTML responses)
3. HTML / hydration parsing
4. Provider metadata
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aioresponses import aioresponses

from llmeter import auth as _auth
from llmeter.models import PROVIDERS, ProviderResult
from llmeter.providers.api.opencode import (
    GO_DISCOVERY_URL,
    PROVIDER_KEY,
    WORKSPACE_ENTRY_URL,
    fetch_opencode_api,
    _extract_int,
    _extract_workspace_billing_body,
    _extract_workspace_url,
    _normalize_cookie,
    _parse_html,
    _parse_monthly_budget_override,
)

WORKSPACE_URL = "https://opencode.ai/workspace/wrk_01KFPZDCPNV68QBCPF64RE9HNG"
GO_WORKSPACE_URL = f"{WORKSPACE_URL}/go"

ZEN_ENTRY_HTML = "<html><body><h1>OpenCode Zen</h1></body></html>"
GO_ENTRY_HTML = f'<html><body><a href="{GO_WORKSPACE_URL}">Subscribe to Go</a></body></html>'


def _make_workspace_html(
    balance: int = 1_708_723_204,        # → $17.09
    monthly_usage: int = 379_059_776,    # → $3.79
    monthly_limit: int = 20,             # → $20
    email: str = "user@example.com",
    include_noise: bool = False,
) -> str:
    """Build a realistic OpenCode workspace hydration snippet."""
    noise = (
        'balance:999999999,monthlyUsage:555555555,monthlyLimit:999,'
        if include_noise
        else ""
    )
    return (
        f'<html><head></head><body><script>'
        f'_$HY.r["userEmail[\\"wrk_01KFPZDCPNV68QBCPF64RE9HNG\\"]"]=$R[3]=$R[2]($R[4]={{p:0,s:0,f:0}});'
        f'_$HY.r["billing.get[\\"wrk_01KFPZDCPNV68QBCPF64RE9HNG\\"]"]=$R[21]=$R[2]($R[22]={{p:0,s:0,f:0}});'
        f'$R[16]($R[4],"{email}");'
        f'{noise}'
        f'$R[16]($R[22],$R[81]={{customerID:"cus_x",'
        f'balance:{balance},'
        f'reload:!0,'
        f'monthlyLimit:{monthly_limit},'
        f'monthlyUsage:{monthly_usage},'
        f'lite:$R[83]={{}},'
        f'reloadError:null}});'
        f'</script></body></html>'
    )


SAMPLE_HTML = _make_workspace_html()
LEGACY_HTML = (
    '<html><body><script>'
    '$R[40]($R[16]={customerID:"cus_x",balance:1708723204,monthlyUsage:379059776,monthlyLimit:20});'
    '$R[40]($R[1],"legacy@example.com");'
    '</script></body></html>'
)


class TestOpencodeApiKeyResolution:
    """resolve_api_key should check auth.json then env var."""

    def test_resolves_from_auth_json(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**from_auth")
        key = fetch_opencode_api.resolve_api_key({})
        assert key == "Fe26.2**from_auth"

    def test_resolves_from_env(
        self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENCODE_AUTH_COOKIE", "Fe26.2**from_env")
        key = fetch_opencode_api.resolve_api_key({})
        assert key == "Fe26.2**from_env"

    def test_auth_json_takes_priority_over_env(
        self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**from_auth")
        monkeypatch.setenv("OPENCODE_AUTH_COOKIE", "Fe26.2**from_env")
        key = fetch_opencode_api.resolve_api_key({})
        assert key == "Fe26.2**from_auth"

    def test_returns_none_when_missing(
        self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("OPENCODE_AUTH_COOKIE", raising=False)
        key = fetch_opencode_api.resolve_api_key({})
        assert key is None

    def test_strips_whitespace(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key(PROVIDER_KEY, "  Fe26.2**trimmed  ")
        key = fetch_opencode_api.resolve_api_key({})
        assert key == "Fe26.2**trimmed"

    def test_accepts_full_cookie_header(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Cookie: auth=Fe26.2**header; theme=dark")
        key = fetch_opencode_api.resolve_api_key({})
        assert key == "Fe26.2**header"


class TestOpencodeFetch:
    """Test the full fetch path with mocked HTTP."""

    async def test_fetch_with_valid_cookie_from_auth_json(
        self, tmp_config_dir: Path,
    ) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**valid")
        with aioresponses() as mocked:
            mocked.get(WORKSPACE_ENTRY_URL, status=200, body=ZEN_ENTRY_HTML)
            mocked.get(GO_DISCOVERY_URL, status=200, body=GO_ENTRY_HTML)
            mocked.get(WORKSPACE_URL, status=200, body=SAMPLE_HTML)
            result = await fetch_opencode_api(timeout=10.0)

        assert result.error is None
        assert result.source == "api"
        assert result.primary is not None
        assert result.updated_at is not None

    async def test_fetch_with_valid_cookie_from_env(
        self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("OPENCODE_AUTH_COOKIE", "Fe26.2**from_env")

        with aioresponses() as mocked:
            mocked.get(WORKSPACE_ENTRY_URL, status=200, body=ZEN_ENTRY_HTML)
            mocked.get(GO_DISCOVERY_URL, status=200, body=GO_ENTRY_HTML)
            mocked.get(WORKSPACE_URL, status=200, body=SAMPLE_HTML)
            result = await fetch_opencode_api(timeout=10.0)

        assert result.error is None
        assert result.source == "api"

    async def test_fetch_without_key_returns_error(
        self, tmp_config_dir: Path, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("OPENCODE_AUTH_COOKIE", raising=False)
        result = await fetch_opencode_api(timeout=5.0)
        assert result.error is not None
        assert "OPENCODE_AUTH_COOKIE" in result.error

    async def test_fetch_returns_error_on_401(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**expired")
        with aioresponses() as mocked:
            mocked.get(WORKSPACE_ENTRY_URL, status=401)
            result = await fetch_opencode_api(timeout=5.0)

        assert result.error is not None
        assert "expired" in result.error.lower() or "invalid" in result.error.lower()

    async def test_fetch_returns_error_on_403(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**forbidden")
        with aioresponses() as mocked:
            mocked.get(WORKSPACE_ENTRY_URL, status=403)
            result = await fetch_opencode_api(timeout=5.0)

        assert result.error is not None

    async def test_fetch_returns_error_on_500(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**valid")
        with aioresponses() as mocked:
            mocked.get(WORKSPACE_ENTRY_URL, status=500)
            result = await fetch_opencode_api(timeout=5.0)

        assert result.error is not None
        assert "500" in result.error

    async def test_fetch_provider_id_and_meta(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**valid")
        with aioresponses() as mocked:
            mocked.get(WORKSPACE_ENTRY_URL, status=200, body=ZEN_ENTRY_HTML)
            mocked.get(GO_DISCOVERY_URL, status=200, body=GO_ENTRY_HTML)
            mocked.get(WORKSPACE_URL, status=200, body=SAMPLE_HTML)
            result = await fetch_opencode_api(timeout=10.0)

        assert result.provider_id == PROVIDER_KEY
        assert result.display_name == "OpenCode Zen API"

    async def test_fetch_uses_monthly_budget_override_when_provided(
        self, tmp_config_dir: Path,
    ) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**valid")
        with aioresponses() as mocked:
            mocked.get(WORKSPACE_ENTRY_URL, status=200, body=ZEN_ENTRY_HTML)
            mocked.get(GO_DISCOVERY_URL, status=200, body=GO_ENTRY_HTML)
            mocked.get(WORKSPACE_URL, status=200, body=SAMPLE_HTML)
            result = await fetch_opencode_api(
                timeout=10.0,
                settings={"monthly_budget": "10"},
            )

        assert result.primary is not None
        assert result.primary.used_percent == pytest.approx(3.79059776 / 10.0 * 100, rel=1e-4)
        assert result.cost is not None
        assert result.cost.limit == 10.0

    async def test_fetch_returns_error_when_workspace_cannot_be_found(
        self, tmp_config_dir: Path,
    ) -> None:
        _auth.save_api_key(PROVIDER_KEY, "Fe26.2**valid")
        with aioresponses() as mocked:
            mocked.get(WORKSPACE_ENTRY_URL, status=200, body=ZEN_ENTRY_HTML)
            mocked.get(GO_DISCOVERY_URL, status=200, body="<html><body>No workspace</body></html>")
            result = await fetch_opencode_api(timeout=5.0)

        assert result.error is not None
        assert "workspace" in result.error.lower()


class TestOpencodeHTMLParsing:
    """Test _parse_html with synthetic HTML stubs."""

    def _result(self) -> ProviderResult:
        return PROVIDERS[PROVIDER_KEY].to_result()

    def test_parse_balance(self) -> None:
        result = self._result()
        _parse_html(_make_workspace_html(balance=1_000_000_000), result)  # → $10.00
        assert result.credits is not None
        assert result.credits.remaining == pytest.approx(10.0)

    def test_parse_monthly_spend_with_limit(self) -> None:
        result = self._result()
        _parse_html(SAMPLE_HTML, result)

        assert result.primary is not None
        pct = result.primary.used_percent
        assert pct == pytest.approx(3.79059776 / 20.0 * 100, rel=1e-4)

    def test_parse_scoped_billing_ignores_unrelated_global_fields(self) -> None:
        result = self._result()
        noisy_html = _make_workspace_html(include_noise=True)
        _parse_html(noisy_html, result)

        assert result.cost is not None
        assert result.cost.used == pytest.approx(3.79, rel=1e-3)
        assert result.cost.limit == 20.0

    def test_parse_primary_label_with_limit(self) -> None:
        result = self._result()
        _parse_html(SAMPLE_HTML, result)
        assert "$" in result.primary_label
        assert "20" in result.primary_label

    def test_parse_primary_label_without_limit(self) -> None:
        result = self._result()
        _parse_html(_make_workspace_html(monthly_limit=0), result)
        assert result.primary is not None
        assert result.primary.used_percent == 0.0
        assert "this month" in result.primary_label

    def test_parse_monthly_budget_override_replaces_platform_limit(self) -> None:
        result = self._result()
        _parse_html(SAMPLE_HTML, result, monthly_budget_override=10.0)

        assert result.primary is not None
        assert result.primary.used_percent == pytest.approx(3.79059776 / 10.0 * 100, rel=1e-4)
        assert result.cost is not None
        assert result.cost.limit == 10.0

    def test_parse_cost_info(self) -> None:
        result = self._result()
        _parse_html(SAMPLE_HTML, result)

        assert result.cost is not None
        assert result.cost.used == pytest.approx(3.79, rel=1e-3)
        assert result.cost.limit == 20.0
        assert result.cost.currency == "USD"
        assert result.cost.period == "Monthly"

    def test_parse_identity_email(self) -> None:
        result = self._result()
        _parse_html(_make_workspace_html(email="alice@example.com"), result)

        assert result.identity is not None
        assert result.identity.account_email == "alice@example.com"

    def test_parse_legacy_fallback(self) -> None:
        result = self._result()
        _parse_html(LEGACY_HTML, result)

        assert result.cost is not None
        assert result.cost.used == pytest.approx(3.79, rel=1e-3)
        assert result.identity is not None
        assert result.identity.account_email == "legacy@example.com"

    def test_parse_no_credits_when_balance_zero(self) -> None:
        result = self._result()
        _parse_html(_make_workspace_html(balance=0), result)
        assert result.credits is None

    def test_parse_spend_capped_at_100_pct(self) -> None:
        result = self._result()
        _parse_html(_make_workspace_html(monthly_usage=3_000_000_000, monthly_limit=20), result)
        assert result.primary is not None
        assert result.primary.used_percent == 100.0

    def test_parse_missing_fields_defaults_to_zero(self) -> None:
        result = self._result()
        _parse_html("<html></html>", result)

        assert result.primary is not None
        assert result.primary.used_percent == 0.0
        assert result.credits is None
        assert result.identity is None

    def test_extract_workspace_billing_body_helper(self) -> None:
        body = _extract_workspace_billing_body(SAMPLE_HTML)
        assert body is not None
        assert "balance:1708723204" in body
        assert "monthlyUsage:379059776" in body

    def test_extract_workspace_url_helper(self) -> None:
        assert _extract_workspace_url(GO_ENTRY_HTML) == WORKSPACE_URL
        assert _extract_workspace_url(GO_WORKSPACE_URL) == WORKSPACE_URL
        assert _extract_workspace_url("<html></html>") is None

    def test_extract_int_helper(self) -> None:
        import re

        pattern = re.compile(r"val:(\d+)")
        assert _extract_int("val:42", pattern) == 42
        assert _extract_int("nothing", pattern) == 0

    def test_normalize_cookie_helper(self) -> None:
        assert _normalize_cookie("Fe26.2**plain") == "Fe26.2**plain"
        assert _normalize_cookie("Cookie: auth=Fe26.2**header; theme=dark") == "Fe26.2**header"
        assert _normalize_cookie(None) is None


class TestOpencodeBudgetOverrideParsing:
    def test_parse_monthly_budget_override_missing(self) -> None:
        assert _parse_monthly_budget_override({}) is None

    def test_parse_monthly_budget_override_accepts_number_or_string(self) -> None:
        assert _parse_monthly_budget_override({"monthly_budget": 20}) == 20.0
        assert _parse_monthly_budget_override({"monthly_budget": "20"}) == 20.0

    def test_parse_monthly_budget_override_ignores_invalid_or_non_positive(self) -> None:
        assert _parse_monthly_budget_override({"monthly_budget": "abc"}) is None
        assert _parse_monthly_budget_override({"monthly_budget": 0}) is None
        assert _parse_monthly_budget_override({"monthly_budget": -5}) is None


class TestOpencodeProviderMeta:
    """Sanity-check the ProviderMeta registration."""

    def test_provider_registered(self) -> None:
        assert PROVIDER_KEY in PROVIDERS

    def test_provider_meta_fields(self) -> None:
        meta = PROVIDERS[PROVIDER_KEY]
        assert meta.id == PROVIDER_KEY
        assert meta.name == "OpenCode Zen API"
        assert meta.icon
        assert meta.color.startswith("#")
        assert not meta.default_enabled

    def test_provider_in_fetchers(self) -> None:
        from llmeter.backend import PROVIDER_FETCHERS

        assert PROVIDER_KEY in PROVIDER_FETCHERS

    def test_provider_in_order(self) -> None:
        from llmeter.backend import ALL_PROVIDER_ORDER

        assert PROVIDER_KEY in ALL_PROVIDER_ORDER

    def test_no_login_handler(self) -> None:
        """OpenCode Zen must not have a dedicated login module."""
        import importlib.util

        spec = importlib.util.find_spec("llmeter.providers.api.opencode_login")
        assert spec is None
