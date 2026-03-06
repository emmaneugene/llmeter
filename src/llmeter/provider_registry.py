"""Central provider runtime registry.

Keeps fetch/login/logout wiring in one place so provider additions do not need
multiple hand-maintained dispatch tables.
"""

from __future__ import annotations

import getpass
import sys
from dataclasses import dataclass
from importlib import import_module
from typing import Awaitable, Callable, Literal

from .auth import clear_api_key, load_api_key, save_api_key
from .config import enable_provider
from .models import ProviderResult
from .providers.api.anthropic import fetch_anthropic_api
from .providers.api.openai import fetch_openai_api
from .providers.api.opencode import fetch_opencode_api
from .providers.subscription.claude import fetch_claude
from .providers.subscription.codex import fetch_codex
from .providers.subscription.copilot import fetch_copilot
from .providers.subscription.cursor import fetch_cursor
from .providers.subscription.gemini import fetch_gemini

FetchFunc = Callable[..., Awaitable[ProviderResult]]
AuthKind = Literal["subscription", "api"]


@dataclass(frozen=True)
class ProviderRuntime:
    """Runtime hooks for one provider."""

    fetcher: FetchFunc
    auth_kind: AuthKind
    login_handler: Callable[[], None]
    logout_handler: Callable[[], None]


def _load_attr(module_path: str, attr_name: str):
    module = import_module(module_path)
    return getattr(module, attr_name)


def _make_subscription_login(provider_id: str, module_path: str) -> Callable[[], None]:
    def handler() -> None:
        interactive_login = _load_attr(module_path, "interactive_login")
        interactive_login()
        enable_provider(provider_id)

    return handler


def _make_subscription_logout(label: str, module_path: str) -> Callable[[], None]:
    def handler() -> None:
        load_credentials = _load_attr(module_path, "load_credentials")
        clear_credentials = _load_attr(module_path, "clear_credentials")
        if load_credentials():
            clear_credentials()
            print(f"✓ Removed {label} credentials.")
        else:
            print(f"No {label} credentials stored.")

    return handler


def _make_api_login(provider_id: str, prompt: str, success_message: str) -> Callable[[], None]:
    def handler() -> None:
        secret = getpass.getpass(prompt).strip()
        if not secret:
            print("No key entered — aborted.", file=sys.stderr)
            sys.exit(1)
        save_api_key(provider_id, secret)
        enable_provider(provider_id)
        print(success_message)

    return handler


def _make_api_logout(
    provider_id: str,
    removed_message: str,
    missing_message: str,
) -> Callable[[], None]:
    def handler() -> None:
        if load_api_key(provider_id):
            clear_api_key(provider_id)
            print(removed_message)
        else:
            print(missing_message)

    return handler


PROVIDER_RUNTIMES: dict[str, ProviderRuntime] = {
    "claude": ProviderRuntime(
        fetcher=fetch_claude,
        auth_kind="subscription",
        login_handler=_make_subscription_login(
            "claude", "llmeter.providers.subscription.claude_login"
        ),
        logout_handler=_make_subscription_logout(
            "Claude", "llmeter.providers.subscription.claude"
        ),
    ),
    "codex": ProviderRuntime(
        fetcher=fetch_codex,
        auth_kind="subscription",
        login_handler=_make_subscription_login(
            "codex", "llmeter.providers.subscription.codex_login"
        ),
        logout_handler=_make_subscription_logout(
            "Codex", "llmeter.providers.subscription.codex"
        ),
    ),
    "gemini": ProviderRuntime(
        fetcher=fetch_gemini,
        auth_kind="subscription",
        login_handler=_make_subscription_login(
            "gemini", "llmeter.providers.subscription.gemini_login"
        ),
        logout_handler=_make_subscription_logout(
            "Gemini", "llmeter.providers.subscription.gemini"
        ),
    ),
    "copilot": ProviderRuntime(
        fetcher=fetch_copilot,
        auth_kind="subscription",
        login_handler=_make_subscription_login(
            "copilot", "llmeter.providers.subscription.copilot_login"
        ),
        logout_handler=_make_subscription_logout(
            "Copilot", "llmeter.providers.subscription.copilot"
        ),
    ),
    "cursor": ProviderRuntime(
        fetcher=fetch_cursor,
        auth_kind="subscription",
        login_handler=_make_subscription_login(
            "cursor", "llmeter.providers.subscription.cursor_login"
        ),
        logout_handler=_make_subscription_logout(
            "Cursor", "llmeter.providers.subscription.cursor"
        ),
    ),
    "openai-api": ProviderRuntime(
        fetcher=fetch_openai_api,
        auth_kind="api",
        login_handler=_make_api_login(
            "openai-api",
            "OpenAI Admin API key (sk-admin-...): ",
            "✓ OpenAI API key saved to auth.json.",
        ),
        logout_handler=_make_api_logout(
            "openai-api",
            "✓ Removed OpenAI API key.",
            "No OpenAI API key stored.",
        ),
    ),
    "anthropic-api": ProviderRuntime(
        fetcher=fetch_anthropic_api,
        auth_kind="api",
        login_handler=_make_api_login(
            "anthropic-api",
            "Anthropic Admin API key (sk-ant-admin01-...): ",
            "✓ Anthropic API key saved to auth.json.",
        ),
        logout_handler=_make_api_logout(
            "anthropic-api",
            "✓ Removed Anthropic API key.",
            "No Anthropic API key stored.",
        ),
    ),
    "opencode": ProviderRuntime(
        fetcher=fetch_opencode_api,
        auth_kind="api",
        login_handler=_make_api_login(
            "opencode",
            "opencode.ai auth cookie (Fe26.2**...): ",
            "✓ opencode.ai auth cookie saved to auth.json.",
        ),
        logout_handler=_make_api_logout(
            "opencode",
            "✓ Removed opencode.ai auth cookie.",
            "No opencode.ai auth cookie stored.",
        ),
    ),
}

PROVIDER_FETCHERS: dict[str, FetchFunc] = {
    provider_id: runtime.fetcher
    for provider_id, runtime in PROVIDER_RUNTIMES.items()
}

LOGIN_HANDLERS: dict[str, Callable[[], None]] = {
    provider_id: runtime.login_handler
    for provider_id, runtime in PROVIDER_RUNTIMES.items()
}

LOGOUT_HANDLERS: dict[str, Callable[[], None]] = {
    provider_id: runtime.logout_handler
    for provider_id, runtime in PROVIDER_RUNTIMES.items()
}
