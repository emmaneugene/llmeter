"""Tests for the OpenCode Go provider."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from aioresponses import aioresponses

from llmeter import auth as _auth
from llmeter.models import PROVIDERS, ProviderResult
from llmeter.providers.subscription.opencode_go import (
    GO_ENTRY_URL,
    clear_credentials,
    fetch_opencode_go,
    load_credentials,
    save_credentials,
    _extract_workspace_url,
    _has_usage_payload,
    _parse_html,
)

WORKSPACE_URL = "https://opencode.ai/workspace/wrk_01KFPZDCPNV68QBCPF64RE9HNG/go"

ENTRY_HTML = f"""
<html>
  <body>
    <a href=\"{WORKSPACE_URL}\">Subscribe to Go</a>
  </body>
</html>
"""

WORKSPACE_HTML = """
<html><body><script>
$R[13]($R[4],"alice@example.com");
$R[13]($R[23],{mine:!0,useBalance:!1,
rollingUsage:$R[28]={status:"ok",resetInSec:18000,usagePercent:12.5},
weeklyUsage:$R[29]={status:"ok",resetInSec:212826,usagePercent:34},
monthlyUsage:$R[30]={status:"ok",resetInSec:2122287,usagePercent:56.75}
});
</script></body></html>
"""


class TestOpenCodeGoCredentials:
    def test_save_and_load_cookie_credentials(self, tmp_config_dir: Path) -> None:
        save_credentials("Fe26.2**cookie")
        creds = load_credentials()
        assert creds == {"type": "cookie", "cookie": "Fe26.2**cookie"}

    def test_load_falls_back_to_shared_opencode_cookie(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key("opencode", "Fe26.2**shared")
        creds = load_credentials()
        assert creds == {"type": "cookie", "cookie": "Fe26.2**shared"}

    def test_load_normalizes_cookie_header(self, tmp_config_dir: Path) -> None:
        save_credentials("Cookie: auth=Fe26.2**cookie; theme=dark")
        creds = load_credentials()
        assert creds == {"type": "cookie", "cookie": "Fe26.2**cookie"}

    def test_clear_credentials(self, tmp_config_dir: Path) -> None:
        save_credentials("Fe26.2**cookie")
        clear_credentials()
        assert load_credentials() is None


class TestOpenCodeGoFetch:
    async def test_fetch_with_own_stored_cookie(self, tmp_config_dir: Path) -> None:
        save_credentials("Fe26.2**valid")
        with aioresponses() as mocked:
            mocked.get(GO_ENTRY_URL, status=200, body=ENTRY_HTML)
            mocked.get(WORKSPACE_URL, status=200, body=WORKSPACE_HTML)
            result = await fetch_opencode_go(timeout=10.0)

        assert result.error is None
        assert result.source == "cookie"
        assert result.provider_id == "opencode-go"
        assert result.display_name == "OpenCode Go"
        assert result.primary is not None
        assert result.secondary is not None
        assert result.tertiary is not None
        assert result.updated_at is not None

    async def test_fetch_falls_back_to_shared_opencode_cookie(self, tmp_config_dir: Path) -> None:
        _auth.save_api_key("opencode", "Fe26.2**shared")
        with aioresponses() as mocked:
            mocked.get(GO_ENTRY_URL, status=200, body=ENTRY_HTML)
            mocked.get(WORKSPACE_URL, status=200, body=WORKSPACE_HTML)
            result = await fetch_opencode_go(timeout=10.0)

        assert result.error is None
        assert result.source == "cookie"

    async def test_fetch_without_credentials_returns_error(
        self,
        tmp_config_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("OPENCODE_AUTH_COOKIE", raising=False)
        result = await fetch_opencode_go(timeout=5.0)
        assert result.error is not None
        assert "auth cookie" in result.error.lower()

    async def test_fetch_returns_error_on_401(self, tmp_config_dir: Path) -> None:
        save_credentials("Fe26.2**expired")
        with aioresponses() as mocked:
            mocked.get(GO_ENTRY_URL, status=401)
            result = await fetch_opencode_go(timeout=5.0)

        assert result.error is not None
        assert "expired" in result.error.lower() or "invalid" in result.error.lower()

    async def test_fetch_returns_error_when_workspace_link_missing(self, tmp_config_dir: Path) -> None:
        save_credentials("Fe26.2**valid")
        with aioresponses() as mocked:
            mocked.get(GO_ENTRY_URL, status=200, body="<html></html>")
            result = await fetch_opencode_go(timeout=5.0)

        assert result.error is not None
        assert "workspace" in result.error.lower()


class TestOpenCodeGoParsing:
    def _result(self) -> ProviderResult:
        return PROVIDERS["opencode-go"].to_result()

    def test_parse_all_usage_windows(self) -> None:
        result = self._result()
        now = datetime(2026, 3, 13, 12, 0, 0, tzinfo=timezone.utc)
        _parse_html(WORKSPACE_HTML, result, now=now)

        assert result.primary is not None
        assert result.secondary is not None
        assert result.tertiary is not None
        assert result.primary.used_percent == pytest.approx(12.5)
        assert result.secondary.used_percent == pytest.approx(34.0)
        assert result.tertiary.used_percent == pytest.approx(56.75)
        assert result.primary.resets_at is not None
        assert result.identity is not None
        assert result.identity.account_email == "alice@example.com"

    def test_parse_all_usage_windows_sets_expected_reset_times(self) -> None:
        result = self._result()
        now = datetime(2026, 3, 13, 12, 0, 0, tzinfo=timezone.utc)
        _parse_html(WORKSPACE_HTML, result, now=now)

        assert result.primary is not None and result.primary.resets_at is not None
        assert result.secondary is not None and result.secondary.resets_at is not None
        assert result.tertiary is not None and result.tertiary.resets_at is not None
        assert (result.primary.resets_at - now).total_seconds() == 18_000
        assert (result.secondary.resets_at - now).total_seconds() == 212_826
        assert (result.tertiary.resets_at - now).total_seconds() == 2_122_287

    def test_parse_missing_fields_defaults_to_zero(self) -> None:
        result = self._result()
        _parse_html("<html></html>", result, now=datetime.now(timezone.utc))

        assert result.primary is not None
        assert result.secondary is not None
        assert result.tertiary is not None
        assert result.primary.used_percent == 0.0
        assert result.secondary.used_percent == 0.0
        assert result.tertiary.used_percent == 0.0
        assert result.identity is None

    def test_extract_workspace_url_helper(self) -> None:
        assert _extract_workspace_url(ENTRY_HTML) == WORKSPACE_URL
        assert _extract_workspace_url(WORKSPACE_URL) == WORKSPACE_URL
        assert _extract_workspace_url("<html></html>") is None

    def test_has_usage_payload_helper(self) -> None:
        assert _has_usage_payload(WORKSPACE_HTML) is True
        assert _has_usage_payload("<html></html>") is False


class TestOpenCodeGoProviderMeta:
    def test_provider_registered(self) -> None:
        assert "opencode-go" in PROVIDERS

    def test_provider_meta_fields(self) -> None:
        meta = PROVIDERS["opencode-go"]
        assert meta.id == "opencode-go"
        assert meta.name == "OpenCode Go"
        assert meta.primary_label == "Rolling"
        assert meta.secondary_label == "Weekly"
        assert meta.tertiary_label == "Monthly"

    def test_provider_in_fetchers(self) -> None:
        from llmeter.backend import ALL_PROVIDER_ORDER
        from llmeter.provider_registry import PROVIDER_FETCHERS

        assert "opencode-go" in PROVIDER_FETCHERS
        assert "opencode-go" in ALL_PROVIDER_ORDER
