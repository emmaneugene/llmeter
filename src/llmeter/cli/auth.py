"""Login/logout dispatch for the llmeter CLI."""

from __future__ import annotations

import sys
from typing import Callable

from ..provider_registry import LOGIN_HANDLERS, LOGOUT_HANDLERS, PROVIDER_RUNTIMES

_SUBSCRIPTION_PROVIDERS = {
    provider_id
    for provider_id, runtime in PROVIDER_RUNTIMES.items()
    if runtime.auth_kind == "subscription"
}

_API_PROVIDERS = {
    provider_id
    for provider_id, runtime in PROVIDER_RUNTIMES.items()
    if runtime.auth_kind == "api"
}


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
