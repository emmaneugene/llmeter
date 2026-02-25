"""Copilot interactive login — GitHub Device Flow."""

from __future__ import annotations

import asyncio
import time
import webbrowser

import aiohttp

from ... import auth
from ..helpers import http_debug_log
from .base import LoginProvider
from .copilot import save_credentials

CLIENT_ID = "Iv1.b507a08c87ecfe98"
SCOPES = "read:user"
DEVICE_CODE_URL = "https://github.com/login/device/code"
ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"


class CopilotLogin(LoginProvider):
    """GitHub Device Flow login for Copilot."""

    @property
    def provider_id(self) -> str:
        return "copilot"

    def interactive_login(self) -> dict:
        """Run the GitHub Device Flow and persist the resulting token."""
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
            raise RuntimeError(f"Device flow failed: {e or type(e).__name__}") from e

        creds = {"type": "oauth", "access": token}
        save_credentials(creds)
        print(f"✓ GitHub Copilot credentials saved to {auth._auth_path()}")
        return creds


async def _request_device_code(timeout: float = 30.0) -> dict:
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    body = f"client_id={CLIENT_ID}&scope={SCOPES}"
    http_debug_log("copilot-oauth", "device_code_request", method="POST", url=DEVICE_CODE_URL)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            DEVICE_CODE_URL, data=body, headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            http_debug_log(
                "copilot-oauth", "device_code_response",
                method="POST", url=DEVICE_CODE_URL, status=resp.status,
            )
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {text[:300]}")
            return await resp.json()


async def _poll_for_token(device_code: str, interval: int, timeout: float = 300.0) -> str:
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
            http_debug_log("copilot-oauth", "poll_request", method="POST", url=ACCESS_TOKEN_URL)
            async with session.post(
                ACCESS_TOKEN_URL, data=body, headers=headers,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()
            http_debug_log(
                "copilot-oauth", "poll_response",
                method="POST", url=ACCESS_TOKEN_URL, status=resp.status,
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


# Module-level singleton — __main__.py imports this directly.
interactive_login = CopilotLogin().interactive_login
