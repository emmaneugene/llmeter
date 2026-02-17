"""GitHub Device Flow OAuth for GitHub Copilot usage tracking.

Uses the same device flow as VS Code's Copilot extension.
The GitHub OAuth token (with ``read:user`` scope) is used to query the
internal Copilot usage API.

Credentials are stored in the unified ~/.config/llmeter/auth.json
under the key ``"github-copilot"``.

**Important:** GitHub's Device Flow returns a long-lived access token
with *no refresh token and no expiry*.  The token remains valid until
the user revokes it in their GitHub settings.  There is no refresh
mechanism — if the token stops working, the user must re-authenticate
with ``llmeter --login copilot``.
"""

from __future__ import annotations

import time
from typing import Optional

import aiohttp

from .. import auth
from .helpers import http_debug_log

# ── OAuth constants ────────────────────────────────────────
# VS Code's Copilot extension client ID (public, embedded in extension).
CLIENT_ID = "Iv1.b507a08c87ecfe98"
SCOPES = "read:user"

DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"

PROVIDER_ID = "github-copilot"


# ── Credential persistence ────────────────────────────────


def load_credentials() -> Optional[dict]:
    """Load Copilot OAuth credentials from the unified auth store."""
    creds = auth.load_provider(PROVIDER_ID)
    if creds and creds.get("access"):
        return creds
    return None


def save_credentials(creds: dict) -> None:
    """Persist credentials to the unified auth store."""
    auth.save_provider(PROVIDER_ID, creds)


def clear_credentials() -> None:
    """Remove stored credentials."""
    auth.clear_provider(PROVIDER_ID)


# ── Device Flow (interactive login) ───────────────────────


def interactive_login() -> dict:
    """Run the GitHub Device Flow interactively.

    1. Request a device code from GitHub.
    2. Display the user code and open the verification URL.
    3. Poll for the access token.
    4. Save and return credentials.
    """
    import asyncio
    import webbrowser

    try:
        device_resp = asyncio.run(_request_device_code())
    except Exception as e:
        raise RuntimeError(f"Failed to request device code: {e}") from e

    user_code = device_resp["user_code"]
    verification_uri = device_resp["verification_uri"]
    device_code = device_resp["device_code"]
    interval = device_resp.get("interval", 5)

    print()
    print("GitHub Copilot Login — Device Flow")
    print("───────────────────────────────────")
    print(f"  Your code: {user_code}")
    print(f"  Visit:     {verification_uri}")
    print()
    print("Opening browser…")
    print()

    webbrowser.open(verification_uri)

    print("Waiting for authorization (press Ctrl-C to cancel)…")
    try:
        token = asyncio.run(_poll_for_token(device_code, interval))
    except Exception as e:
        raise RuntimeError(f"Device flow failed: {e}") from e

    # GitHub device flow tokens are long-lived with no expiry and no
    # refresh token.  The token is valid until the user revokes it
    # in their GitHub settings.
    creds = {
        "type": "oauth",
        "access": token,
    }
    save_credentials(creds)
    print(f"✓ GitHub Copilot credentials saved to {auth._auth_path()}")
    return creds


# ── HTTP helpers ───────────────────────────────────────────


async def _request_device_code(timeout: float = 30.0) -> dict:
    """POST to GitHub's device/code endpoint."""
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = f"client_id={CLIENT_ID}&scope={SCOPES}"

    http_debug_log(
        "copilot-oauth",
        "device_code_request",
        method="POST",
        url=DEVICE_CODE_URL,
    )

    async with aiohttp.ClientSession() as session:
        async with session.post(
            DEVICE_CODE_URL,
            data=body,
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            http_debug_log(
                "copilot-oauth",
                "device_code_response",
                method="POST",
                url=DEVICE_CODE_URL,
                status=resp.status,
            )
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {text[:300]}")
            return await resp.json()


async def _poll_for_token(device_code: str, interval: int, timeout: float = 300.0) -> str:
    """Poll GitHub for the access token until authorized or expired."""
    import asyncio

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = (
        f"client_id={CLIENT_ID}"
        f"&device_code={device_code}"
        f"&grant_type=urn:ietf:params:oauth:grant-type:device_code"
    )

    deadline = time.monotonic() + timeout

    async with aiohttp.ClientSession() as session:
        while time.monotonic() < deadline:
            await asyncio.sleep(interval)

            http_debug_log(
                "copilot-oauth",
                "poll_request",
                method="POST",
                url=ACCESS_TOKEN_URL,
            )

            async with session.post(
                ACCESS_TOKEN_URL,
                data=body,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

            http_debug_log(
                "copilot-oauth",
                "poll_response",
                method="POST",
                url=ACCESS_TOKEN_URL,
                status=resp.status,
            )

            error = data.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                interval = min(interval + 5, 30)
                continue
            if error == "expired_token":
                raise RuntimeError("Device code expired — please try again.")
            if error:
                desc = data.get("error_description", error)
                raise RuntimeError(f"GitHub OAuth error: {desc}")

            access_token = data.get("access_token")
            if access_token:
                return access_token

    raise RuntimeError("Timed out waiting for authorization.")


# ── High-level: get a valid access token ───────────────────


async def get_valid_access_token(timeout: float = 30.0) -> Optional[str]:
    """Load credentials and return the access token, or None.

    GitHub OAuth tokens obtained via the device flow are long-lived
    and don't have a refresh mechanism — if the token is revoked,
    the user must re-authenticate.
    """
    creds = load_credentials()
    if creds is None:
        return None
    return creds.get("access")
