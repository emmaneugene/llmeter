"""OpenCode Go provider — tracks rolling, weekly, and monthly usage.

Run `llmeter --login opencode-go` or `llmeter --login opencode` to supply the
opencode.ai `auth` cookie. The cookie is the HttpOnly `auth` value from
opencode.ai — extract it from DevTools → Application → Cookies → opencode.ai →
`auth`.

The provider fetches the public Go entry page first to discover the workspace-
specific Go URL for the authenticated user, then scrapes the server-rendered Go
workspace page hydration payload for the three usage windows.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp

from ... import auth
from ...models import PROVIDERS, ProviderIdentity, ProviderResult, RateWindow
from ..helpers import DEFAULT_USER_AGENT, http_debug_log
from .base import SubscriptionProvider

PROVIDER_KEY = "opencode-go"
_SHARED_PROVIDER_KEY = "opencode"
GO_ENTRY_URL = "https://opencode.ai/go"

_RE_WORKSPACE_GO_URL = re.compile(
    r'(?P<url>(?:https://opencode\.ai)?/workspace/[^"\'\s<>]+/go)'
)
_RE_EMAIL = re.compile(r'"([^"@\s]{1,64}@[^"@\s]{1,128})"')
_RE_RESET_IN_SEC = re.compile(r"resetInSec:(\d+)")
_RE_USAGE_PERCENT = re.compile(r"usagePercent:(\d+(?:\.\d+)?)")
_RE_USAGE_BLOCKS: dict[str, re.Pattern[str]] = {
    "rolling": re.compile(r"rollingUsage:(?:\$R\[\d+\]=)?\{(?P<body>[^}]*)\}"),
    "weekly": re.compile(r"weeklyUsage:(?:\$R\[\d+\]=)?\{(?P<body>[^}]*)\}"),
    "monthly": re.compile(r"monthlyUsage:(?:\$R\[\d+\]=)?\{(?P<body>[^}]*)\}"),
}


def _normalize_cookie(raw: str | None) -> str | None:
    """Normalize an auth cookie value or header into the bare cookie value."""
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


# ── Credential management ────────────────────────────────────────────────


def load_credentials() -> Optional[dict]:
    """Load stored OpenCode Go credentials, falling back to shared OpenCode auth."""
    stored = auth.load_provider(PROVIDER_KEY)
    if stored and stored.get("cookie"):
        cookie = _normalize_cookie(str(stored.get("cookie")))
        if cookie:
            return {"type": "cookie", "cookie": cookie}

    cookie = (
        _normalize_cookie(auth.load_api_key(PROVIDER_KEY))
        or _normalize_cookie(auth.load_api_key(_SHARED_PROVIDER_KEY))
        or _normalize_cookie(os.environ.get("OPENCODE_AUTH_COOKIE"))
    )
    if not cookie:
        return None

    return {"type": "cookie", "cookie": cookie}


def save_credentials(cookie: str) -> None:
    """Persist an OpenCode Go auth cookie."""
    normalized = _normalize_cookie(cookie)
    if not normalized:
        raise ValueError("No auth cookie provided.")
    auth.save_provider(PROVIDER_KEY, {"type": "cookie", "cookie": normalized})


def clear_credentials() -> None:
    """Remove stored OpenCode Go credentials."""
    auth.clear_provider(PROVIDER_KEY)


# ── Provider class ───────────────────────────────────────────────────────


class OpencodeGoProvider(SubscriptionProvider):
    """Fetches OpenCode Go usage via the workspace page hydration payload."""

    @property
    def provider_id(self) -> str:
        return PROVIDER_KEY

    @property
    def no_credentials_error(self) -> str:
        return (
            "OpenCode Go auth cookie not configured. "
            "Run `llmeter --login opencode-go`, `llmeter --login opencode`, "
            "or set OPENCODE_AUTH_COOKIE."
        )

    async def get_credentials(self, timeout: float) -> Optional[dict]:
        return load_credentials()

    async def _fetch(
        self,
        creds: dict,
        timeout: float,
        settings: dict,
    ) -> ProviderResult:
        del settings  # unused for this provider

        result = PROVIDERS[PROVIDER_KEY].to_result()
        cookie = creds["cookie"]
        headers = {
            "Cookie": f"auth={cookie}",
            "Accept": "text/html",
            "User-Agent": DEFAULT_USER_AGENT,
        }

        try:
            async with aiohttp.ClientSession() as session:
                entry_final_url, entry_html = await _fetch_html(
                    session,
                    GO_ENTRY_URL,
                    headers,
                    timeout,
                    label="entry_page",
                )

                workspace_html = entry_html
                if not _has_usage_payload(workspace_html):
                    workspace_url = (
                        _extract_workspace_url(entry_final_url)
                        or _extract_workspace_url(entry_html)
                    )
                    if not workspace_url:
                        result.error = (
                            "Could not find the OpenCode Go workspace page. "
                            "Make sure the auth cookie is valid and the account has access to Go."
                        )
                        return result

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
            result.error = f"OpenCode Go request failed: {e or type(e).__name__}"
            return result

        if not _has_usage_payload(workspace_html):
            result.error = (
                "Could not locate OpenCode Go usage data on the workspace page."
            )
            return result

        _parse_html(workspace_html, result)
        result.source = "cookie"
        result.updated_at = datetime.now(timezone.utc)
        return result


# ── HTML / JS hydration parsing ──────────────────────────────────────────


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
                "OpenCode session expired or invalid. "
                "Run `llmeter --login opencode-go` or `llmeter --login opencode` "
                "to update the auth cookie."
            )
        if resp.status != 200:
            raise RuntimeError(f"OpenCode Go returned HTTP {resp.status}")
        return (str(resp.url), await resp.text())


def _extract_workspace_url(text: str) -> str | None:
    """Extract the authenticated workspace Go URL from HTML or a final URL."""
    match = _RE_WORKSPACE_GO_URL.search(text)
    if not match:
        return None

    url = match.group("url")
    if url.startswith("http"):
        return url
    return f"https://opencode.ai{url}"


def _has_usage_payload(html: str) -> bool:
    """Return True when the page includes the Go usage hydration payload."""
    return all(key in html for key in ("rollingUsage", "weeklyUsage", "monthlyUsage"))


def _parse_html(
    html: str,
    result: ProviderResult,
    *,
    now: datetime | None = None,
) -> None:
    """Extract rolling / weekly / monthly usage windows from the hydration payload."""
    timestamp = now or datetime.now(timezone.utc)

    result.primary = _parse_window(html, "rolling", now=timestamp)
    result.secondary = _parse_window(html, "weekly", now=timestamp)
    result.tertiary = _parse_window(html, "monthly", now=timestamp)

    email_match = _RE_EMAIL.search(html)
    if email_match:
        result.identity = ProviderIdentity(account_email=email_match.group(1))


def _parse_window(html: str, name: str, *, now: datetime) -> RateWindow:
    """Parse one usage window from the page hydration payload."""
    block = _RE_USAGE_BLOCKS[name].search(html)
    if not block:
        return RateWindow(used_percent=0.0)

    body = block.group("body")
    reset_secs = _extract_int(body, _RE_RESET_IN_SEC)
    used_percent = _extract_float(body, _RE_USAGE_PERCENT)
    resets_at = now + timedelta(seconds=reset_secs) if reset_secs > 0 else None
    return RateWindow(used_percent=used_percent, resets_at=resets_at)


def _extract_int(text: str, pattern: re.Pattern[str]) -> int:
    """Extract an integer using *pattern*, defaulting to 0 when missing."""
    match = pattern.search(text)
    return int(match.group(1)) if match else 0


def _extract_float(text: str, pattern: re.Pattern[str]) -> float:
    """Extract a float using *pattern*, defaulting to 0 when missing."""
    match = pattern.search(text)
    return float(match.group(1)) if match else 0.0


# Module-level singleton — used by backend.py and importable as a callable.
fetch_opencode_go = OpencodeGoProvider()
