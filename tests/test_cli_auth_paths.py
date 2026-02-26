"""CLI auth command import path regression tests."""

from __future__ import annotations

import sys

import pytest

from llmeter import __main__ as cli
from llmeter.cli.auth import (
    LOGIN_HANDLERS,
    LOGOUT_HANDLERS,
    _SUBSCRIPTION_PROVIDERS,
    _API_PROVIDERS,
)

_ALL_PROVIDERS = _SUBSCRIPTION_PROVIDERS | _API_PROVIDERS


def test_login_handlers_cover_all_providers() -> None:
    """Every known provider must have a --login handler."""
    assert LOGIN_HANDLERS.keys() == _ALL_PROVIDERS, (
        f"LOGIN_HANDLERS missing: {_ALL_PROVIDERS - LOGIN_HANDLERS.keys()}"
    )


def test_logout_handlers_cover_all_providers() -> None:
    """Every known provider must have a --logout handler."""
    assert LOGOUT_HANDLERS.keys() == _ALL_PROVIDERS, (
        f"LOGOUT_HANDLERS missing: {_ALL_PROVIDERS - LOGOUT_HANDLERS.keys()}"
    )


@pytest.mark.parametrize(
    ("provider", "label"),
    [
        ("claude", "Claude"),
        ("codex", "Codex"),
        ("gemini", "Gemini"),
        ("copilot", "Copilot"),
        ("cursor", "Cursor"),
    ],
)
def test_logout_commands_import_moved_auth_modules(
    tmp_config_dir,  # noqa: ARG001 - ensures isolated XDG config home
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    provider: str,
    label: str,
) -> None:
    """`--logout` should resolve auth imports from providers.subscription.* modules."""
    monkeypatch.setattr(sys, "argv", ["llmeter", "--logout", provider])

    cli.main()

    out = capsys.readouterr().out
    assert f"No {label} credentials stored." in out
