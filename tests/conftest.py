"""Shared fixtures for llmeter tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Generator

import pytest


@pytest.fixture(autouse=True)
def reset_claude_singleton_state() -> Generator[None, None, None]:
    """Reset Claude provider singleton cache state between tests."""
    from llmeter.providers.subscription.claude import fetch_claude

    fetch_claude._cached_identity = None
    fetch_claude._identity_token = None
    yield
    fetch_claude._cached_identity = None
    fetch_claude._identity_token = None


@pytest.fixture()
def tmp_config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect XDG_CONFIG_HOME to a temp directory so auth.json is isolated."""
    config_home = tmp_path / "config"
    config_home.mkdir()
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_home))
    return config_home / "llmeter"


@pytest.fixture()
def auth_path(tmp_config_dir: Path) -> Path:
    """Return the auth.json path inside the temp config dir."""
    return tmp_config_dir / "auth.json"


def write_auth(auth_path: Path, data: dict) -> None:
    """Write auth.json data for testing."""
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    auth_path.write_text(json.dumps(data, indent=2))
