"""Login/logout dispatch for the llmeter CLI.

Subscription providers have interactive OAuth flows exposed via --login
and --logout.  API providers (anthropic-api, openai-api, opencode) also
support --login (prompts for the key/cookie and saves it to auth.json)
and --logout (removes the stored secret).
"""

from __future__ import annotations

import sys
from typing import Callable


# ── Helpers ────────────────────────────────────────────────


def _enable_and_login(provider_id: str, login_func) -> None:
    login_func()
    from ..config import enable_provider
    enable_provider(provider_id)


def _clear_credentials(label: str, load_func, clear_func) -> None:
    if load_func():
        clear_func()
        print(f"✓ Removed {label} credentials.")
    else:
        print(f"No {label} credentials stored.")


# ── Login handlers ─────────────────────────────────────────


def _login_claude() -> None:
    from ..providers.subscription.claude_login import interactive_login
    _enable_and_login("claude", interactive_login)


def _login_codex() -> None:
    from ..providers.subscription.codex_login import interactive_login
    _enable_and_login("codex", interactive_login)


def _login_gemini() -> None:
    from ..providers.subscription.gemini_login import interactive_login
    _enable_and_login("gemini", interactive_login)


def _login_copilot() -> None:
    from ..providers.subscription.copilot_login import interactive_login
    _enable_and_login("copilot", interactive_login)


def _login_cursor() -> None:
    from ..providers.subscription.cursor_login import interactive_login
    _enable_and_login("cursor", interactive_login)


def _login_openai_api() -> None:
    import getpass
    from .. import auth
    from ..config import enable_provider
    key = getpass.getpass("OpenAI Admin API key (sk-admin-...): ").strip()
    if not key:
        print("No key entered — aborted.", file=sys.stderr)
        sys.exit(1)
    auth.save_api_key("openai-api", key)
    enable_provider("openai-api")
    print("✓ OpenAI API key saved to auth.json.")


def _login_anthropic_api() -> None:
    import getpass
    from .. import auth
    from ..config import enable_provider
    key = getpass.getpass("Anthropic Admin API key (sk-ant-admin01-...): ").strip()
    if not key:
        print("No key entered — aborted.", file=sys.stderr)
        sys.exit(1)
    auth.save_api_key("anthropic-api", key)
    enable_provider("anthropic-api")
    print("✓ Anthropic API key saved to auth.json.")


def _login_opencode() -> None:
    import getpass
    from .. import auth
    from ..config import enable_provider
    key = getpass.getpass("opencode.ai auth cookie (Fe26.2**...): ").strip()
    if not key:
        print("No key entered — aborted.", file=sys.stderr)
        sys.exit(1)
    auth.save_api_key("opencode", key)
    enable_provider("opencode")
    print("✓ opencode.ai auth cookie saved to auth.json.")


# ── Logout handlers ────────────────────────────────────────


def _logout_claude() -> None:
    from ..providers.subscription.claude import clear_credentials, load_credentials
    _clear_credentials("Claude", load_credentials, clear_credentials)


def _logout_codex() -> None:
    from ..providers.subscription.codex import clear_credentials, load_credentials
    _clear_credentials("Codex", load_credentials, clear_credentials)


def _logout_gemini() -> None:
    from ..providers.subscription.gemini import clear_credentials, load_credentials
    _clear_credentials("Gemini", load_credentials, clear_credentials)


def _logout_copilot() -> None:
    from ..providers.subscription.copilot import clear_credentials, load_credentials
    _clear_credentials("Copilot", load_credentials, clear_credentials)


def _logout_cursor() -> None:
    from ..providers.subscription.cursor import clear_credentials, load_credentials
    _clear_credentials("Cursor", load_credentials, clear_credentials)


def _logout_openai_api() -> None:
    from .. import auth
    if auth.load_api_key("openai-api"):
        auth.clear_api_key("openai-api")
        print("✓ Removed OpenAI API key.")
    else:
        print("No OpenAI API key stored.")


def _logout_anthropic_api() -> None:
    from .. import auth
    if auth.load_api_key("anthropic-api"):
        auth.clear_api_key("anthropic-api")
        print("✓ Removed Anthropic API key.")
    else:
        print("No Anthropic API key stored.")


def _logout_opencode() -> None:
    from .. import auth
    if auth.load_api_key("opencode"):
        auth.clear_api_key("opencode")
        print("✓ Removed opencode.ai auth cookie.")
    else:
        print("No opencode.ai auth cookie stored.")


# ── Dispatch tables ────────────────────────────────────────

_SUBSCRIPTION_PROVIDERS = {"claude", "codex", "gemini", "copilot", "cursor"}
_API_PROVIDERS = {"openai-api", "anthropic-api", "opencode"}

LOGIN_HANDLERS: dict[str, Callable[[], None]] = {
    "claude":         _login_claude,
    "codex":          _login_codex,
    "gemini":         _login_gemini,
    "copilot":        _login_copilot,
    "cursor":         _login_cursor,
    "openai-api":     _login_openai_api,
    "anthropic-api":  _login_anthropic_api,
    "opencode":       _login_opencode,
}

LOGOUT_HANDLERS: dict[str, Callable[[], None]] = {
    "claude":         _logout_claude,
    "codex":          _logout_codex,
    "gemini":         _logout_gemini,
    "copilot":        _logout_copilot,
    "cursor":         _logout_cursor,
    "openai-api":     _logout_openai_api,
    "anthropic-api":  _logout_anthropic_api,
    "opencode":       _logout_opencode,
}

# ── Public dispatch ────────────────────────────────────────


def login_provider(provider: str) -> None:
    """Run the interactive login flow for *provider*.

    Exits with code 2 on unknown provider; raises RuntimeError on failure.
    """
    handler = LOGIN_HANDLERS.get(provider)
    if not handler:
        available = ", ".join(sorted(LOGIN_HANDLERS))
        print(
            f"Unknown provider for --login: {provider}. "
            f"Choose one of: {available}",
            file=sys.stderr,
        )
        sys.exit(2)
    handler()


def logout_provider(provider: str) -> None:
    """Clear stored credentials for *provider*.

    Exits with code 2 on unknown provider.
    """
    handler = LOGOUT_HANDLERS.get(provider)
    if not handler:
        available = ", ".join(sorted(LOGOUT_HANDLERS))
        print(
            f"Unknown provider for --logout: {provider}. "
            f"Choose one of: {available}",
            file=sys.stderr,
        )
        sys.exit(2)
    handler()
