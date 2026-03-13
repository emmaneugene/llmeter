"""opencode.ai Zen provider — tracks balance and monthly spend.

Config:
  { "id": "opencode-zen", "monthly_budget": 50.0 }

Run `llmeter --login opencode-zen` or set OPENCODE_AUTH_COOKIE env var to supply
the auth cookie. The cookie is the HttpOnly ``auth`` value from opencode.ai —
extract it from DevTools → Application → Cookies → opencode.ai → ``auth``.

Data is scraped from the authenticated workspace page, which embeds billing and
identity data in the SolidStart hydration payload. No separate JSON API
endpoint is required.

Cost unit: all raw cost integers on the page are in units of 1e-8 USD.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from ...models import (
    CostInfo,
    CreditsInfo,
    PROVIDERS,
    ProviderIdentity,
    ProviderResult,
    RateWindow,
)
from ..helpers import DEFAULT_USER_AGENT, http_debug_log
from .base import ApiProvider

PROVIDER_KEY = "opencode-zen"
WORKSPACE_ENTRY_URL = "https://opencode.ai/zen"
GO_DISCOVERY_URL = "https://opencode.ai/go"
COST_UNIT = 1e8  # divide raw int by this to get USD

# ── Regex patterns for the JS hydration payload ────────────────────────────

_RE_WORKSPACE_URL = re.compile(
    r'(?P<url>(?:https://opencode\.ai)?/workspace/[^/"\'\s<>]+(?:/go)?)'
)
_RE_BALANCE = re.compile(r"balance:(\d+)")
_RE_MONTHLY_USAGE = re.compile(r"monthlyUsage:(\d+)")
_RE_MONTHLY_LIMIT = re.compile(r"monthlyLimit:(\d+)")
_RE_EMAIL = re.compile(r'"([^"@\s]{1,64}@[^"@\s]{1,128})"')
_RE_HYDRATION_REF = re.compile(r'\(\$R\[(?P<ref>\d+)\]=\{p:0,s:0,f:0\}\)')


# ── Provider class ─────────────────────────────────────────────────────────


class OpencodeProvider(ApiProvider):
    """Fetches opencode.ai Zen balance and monthly spend."""

    @property
    def provider_id(self) -> str:
        return PROVIDER_KEY

    @property
    def no_api_key_error(self) -> str:
        return (
            "opencode.ai auth cookie not configured. "
            "Set OPENCODE_AUTH_COOKIE env var or run `llmeter --login opencode-zen`."
        )

    def resolve_api_key(self, settings: dict) -> Optional[str]:
        """Return the auth cookie value from auth.json or env, or None."""
        from ... import auth as _auth

        key = (
            _auth.load_api_key(self.provider_id)
            or os.environ.get("OPENCODE_AUTH_COOKIE")
            or ""
        )
        return _normalize_cookie(key)

    async def _fetch(
        self,
        api_key: str,
        timeout: float,
        settings: dict,
    ) -> ProviderResult:
        result = PROVIDERS[PROVIDER_KEY].to_result(source="api")
        monthly_budget_override = _parse_monthly_budget_override(settings)

        headers = {
            "Cookie": f"auth={api_key}",
            "Accept": "text/html",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        try:
            async with aiohttp.ClientSession() as session:
                workspace_url, workspace_html = await _discover_workspace_page(
                    session,
                    headers,
                    timeout,
                )
                if workspace_html is None:
                    _, workspace_html = await _fetch_html(
                        session,
                        workspace_url,
                        headers,
                        timeout,
                        label="workspace_page",
                    )
        except RuntimeError as e:
            result.error = str(e)
            return result
        except aiohttp.ClientError as e:
            result.error = f"opencode.ai request failed: {e or type(e).__name__}"
            return result

        _parse_html(
            workspace_html,
            result,
            monthly_budget_override=monthly_budget_override,
        )
        result.updated_at = datetime.now(timezone.utc)
        return result


# ── Fetch helpers ──────────────────────────────────────────────────────────


async def _discover_workspace_page(
    session: aiohttp.ClientSession,
    headers: dict[str, str],
    timeout: float,
) -> tuple[str, str | None]:
    """Resolve the authenticated workspace root URL for OpenCode Zen."""
    for url, label in (
        (WORKSPACE_ENTRY_URL, "zen_entry"),
        (GO_DISCOVERY_URL, "go_entry"),
    ):
        final_url, html = await _fetch_html(
            session,
            url,
            headers,
            timeout,
            label=label,
        )

        normalized_final = _normalize_workspace_url(final_url)
        if normalized_final:
            if _is_workspace_root_url(final_url) and _has_billing_payload(html):
                return normalized_final, html
            return normalized_final, None

        workspace_url = _extract_workspace_url(html)
        if workspace_url:
            return workspace_url, None

    raise RuntimeError(
        "Could not find the OpenCode workspace page. "
        "Make sure the auth cookie is valid and the account has access to OpenCode."
    )


async def _fetch_html(
    session: aiohttp.ClientSession,
    url: str,
    headers: dict[str, str],
    timeout: float,
    *,
    label: str,
) -> tuple[str, str]:
    """Fetch one HTML page with standard OpenCode error handling."""
    http_debug_log(
        PROVIDER_KEY,
        f"{label}_request",
        method="GET",
        url=url,
        headers={"Cookie": "auth=<redacted>"},
    )

    async with session.get(
        url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=timeout),
        allow_redirects=True,
    ) as resp:
        http_debug_log(
            PROVIDER_KEY,
            f"{label}_response",
            method="GET",
            url=str(resp.url),
            status=resp.status,
        )
        if resp.status in (401, 403):
            raise RuntimeError(
                "opencode.ai session expired or invalid. "
                "Run `llmeter --login opencode-zen` to update the auth cookie."
            )
        if resp.status != 200:
            raise RuntimeError(f"opencode.ai returned HTTP {resp.status}")
        return (str(resp.url), await resp.text())


# ── HTML / JS hydration parsing ────────────────────────────────────────────


def _parse_html(
    html: str,
    result: ProviderResult,
    monthly_budget_override: float | None = None,
) -> None:
    """Extract billing data from the OpenCode workspace hydration payload."""
    billing_body = _extract_workspace_billing_body(html) or html

    balance_usd = _extract_int(billing_body, _RE_BALANCE) / COST_UNIT
    monthly_usage = _extract_int(billing_body, _RE_MONTHLY_USAGE) / COST_UNIT
    platform_monthly_limit = _extract_int(billing_body, _RE_MONTHLY_LIMIT)

    monthly_limit = monthly_budget_override
    if monthly_limit is None:
        monthly_limit = float(platform_monthly_limit)

    if monthly_limit > 0:
        spend_pct = min(100.0, (monthly_usage / monthly_limit) * 100.0)
        result.primary = RateWindow(used_percent=spend_pct)
        result.primary_label = f"${monthly_usage:.2f} / ${monthly_limit:.0f}"
    else:
        result.primary = RateWindow(used_percent=0.0)
        result.primary_label = f"${monthly_usage:.2f} this month"

    if balance_usd > 0:
        result.credits = CreditsInfo(remaining=balance_usd)

    result.cost = CostInfo(
        used=round(monthly_usage, 4),
        limit=float(monthly_limit),
        currency="USD",
        period="Monthly",
    )

    email = _extract_workspace_email(html)
    if email:
        result.identity = ProviderIdentity(account_email=email)


def _extract_workspace_billing_body(html: str) -> str | None:
    """Return the scoped billing hydration object body, if present."""
    ref = _find_hydration_ref(html, "billing.get")
    if ref is None:
        return None

    assignment = re.search(rf'\$R\[\d+\]\(\$R\[{ref}\],', html)
    if not assignment:
        return None

    obj_start = html.find("{", assignment.end())
    if obj_start == -1:
        return None

    return _extract_braced_object(html, obj_start)


def _extract_workspace_email(html: str) -> str | None:
    """Extract the workspace-scoped user email from the hydration payload."""
    ref = _find_hydration_ref(html, "userEmail")
    if ref is not None:
        match = re.search(
            rf'\$R\[\d+\]\(\$R\[{ref}\],"(?P<email>(?:[^"\\]|\\.)+)"\)',
            html,
        )
        if match:
            return match.group("email")

    email_match = _RE_EMAIL.search(html)
    return email_match.group(1) if email_match else None


def _find_hydration_ref(html: str, key: str) -> str | None:
    """Find the SolidStart `$R[...]` ref bound to a hydration cache key."""
    pos = html.find(key)
    if pos == -1:
        return None

    window = html[pos : pos + 2000]
    match = _RE_HYDRATION_REF.search(window)
    return match.group("ref") if match else None


def _extract_braced_object(text: str, start: int) -> str | None:
    """Extract the balanced object body starting at *start* (`{`)."""
    if start < 0 or start >= len(text) or text[start] != "{":
        return None

    depth = 0
    quote: str | None = None
    escaped = False

    for idx in range(start, len(text)):
        ch = text[idx]

        if quote is not None:
            if escaped:
                escaped = False
                continue
            if ch == "\\":
                escaped = True
                continue
            if ch == quote:
                quote = None
            continue

        if ch in {'"', "'"}:
            quote = ch
            continue

        if ch == "{":
            depth += 1
            continue

        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1 : idx]

    return None


def _normalize_cookie(raw: str | None) -> str | None:
    """Normalize a pasted auth cookie value or Cookie header."""
    if not raw:
        return None

    cookie = raw.strip()
    if not cookie:
        return None

    if cookie.lower().startswith("cookie:"):
        cookie = cookie[7:].strip()

    match = re.search(r"(?:^|;\s*)auth=([^;]+)", cookie)
    if match:
        cookie = match.group(1).strip()

    return cookie or None


def _normalize_workspace_url(url: str) -> str | None:
    """Normalize any OpenCode workspace root / Go URL to the Zen workspace root."""
    match = _RE_WORKSPACE_URL.search(url)
    if not match:
        return None

    workspace_url = match.group("url")
    if workspace_url.startswith("/"):
        workspace_url = f"https://opencode.ai{workspace_url}"
    if workspace_url.endswith("/go"):
        workspace_url = workspace_url[:-3]
    return workspace_url.rstrip("/")


def _extract_workspace_url(text: str) -> str | None:
    """Extract a workspace root URL from HTML or a final URL."""
    return _normalize_workspace_url(text)


def _is_workspace_root_url(url: str) -> bool:
    """Return True when *url* already points at the Zen workspace root."""
    normalized = _normalize_workspace_url(url)
    return normalized is not None and normalized.rstrip("/") == url.rstrip("/")


def _has_billing_payload(html: str) -> bool:
    """Return True when the page includes the workspace billing hydration data."""
    return "billing.get" in html and "monthlyUsage" in html and "balance:" in html


def _parse_monthly_budget_override(settings: dict) -> float | None:
    """Return a validated monthly budget override, or None if not provided."""
    if "monthly_budget" not in settings:
        return None

    try:
        value = float(settings.get("monthly_budget") or 0.0)
    except (TypeError, ValueError):
        return None

    return value if value > 0 else None


def _extract_int(html: str, pattern: re.Pattern[str]) -> int:
    match = pattern.search(html)
    return int(match.group(1)) if match else 0


# Module-level singleton — used by backend.py and importable as a callable.
fetch_opencode_api = OpencodeProvider()
