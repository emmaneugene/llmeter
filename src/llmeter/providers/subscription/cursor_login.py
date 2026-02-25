"""Cursor interactive login — cookie paste flow."""

from __future__ import annotations

import asyncio
import sys

import aiohttp

from ... import auth
from .base import LoginProvider
from .cursor import load_credentials, save_credentials

_VALID_COOKIE_NAMES = {
    "WorkosCursorSessionToken",
    "__Secure-next-auth.session-token",
    "next-auth.session-token",
}


class CursorLogin(LoginProvider):
    """Cookie-paste login flow for Cursor."""

    @property
    def provider_id(self) -> str:
        return "cursor"

    def interactive_login(self) -> dict:
        """Prompt the user to paste a Cursor session cookie and persist it."""
        existing = load_credentials()
        if existing:
            email = existing.get("email", "unknown")
            print(f"Cursor credentials already stored (email: {email}).")
            try:
                answer = input("Replace them? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                raise RuntimeError("Login cancelled.")
            if answer not in ("y", "yes"):
                raise RuntimeError("Login cancelled.")

        print()
        print("To get your Cursor session cookie:")
        print()
        print("  1. Open https://cursor.com/dashboard in your browser")
        print("  2. Open DevTools (F12) → Network tab → refresh the page")
        print("  3. Click any request to cursor.com")
        print("  4. Find the Cookie header and copy its value")
        print()
        print("The cookie should contain 'WorkosCursorSessionToken' or")
        print("'__Secure-next-auth.session-token'.")
        print()

        try:
            cookie = input("Cookie: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            raise RuntimeError("Login cancelled.")

        if not cookie:
            raise RuntimeError("No cookie provided.")

        # Strip "Cookie: " prefix if user copied the whole header
        if cookie.lower().startswith("cookie:"):
            cookie = cookie[7:].strip()

        # Basic validation
        if not any(name in cookie for name in _VALID_COOKIE_NAMES):
            print(
                "⚠ Warning: Cookie does not contain a known Cursor session token.",
                file=sys.stderr,
            )
            print(
                "  Expected one of: " + ", ".join(sorted(_VALID_COOKIE_NAMES)),
                file=sys.stderr,
            )
            try:
                answer = input("Save anyway? [y/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                print()
                raise RuntimeError("Login cancelled.")
            if answer not in ("y", "yes"):
                raise RuntimeError("Login cancelled.")

        save_credentials(cookie)
        print(f"✓ Cursor cookie saved to {auth._auth_path()}")

        # Best-effort verification — fetch email from /api/auth/me
        try:
            email = asyncio.run(_verify_cookie(cookie))
            if email:
                save_credentials(cookie, email=email)
                print(f"✓ Verified — logged in as {email}")
            else:
                print("⚠ Could not verify cookie (will try on next fetch).")
        except Exception:
            print("⚠ Could not verify cookie (will try on next fetch).")

        return load_credentials() or {"type": "cookie", "cookie": cookie}


async def _verify_cookie(cookie: str, timeout: float = 10.0) -> str | None:
    """Fetch user email from /api/auth/me to verify the cookie."""
    headers = {"Cookie": cookie, "Accept": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://cursor.com/api/auth/me",
            headers=headers,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 200:
                data = await resp.json()
                return data.get("email")
    return None


# Module-level singleton — __main__.py imports this directly.
interactive_login = CursorLogin().interactive_login
