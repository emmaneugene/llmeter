"""Tests for the unified auth.json credential store."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from llmeter import auth


class TestLoadSave:
    """Credential persistence tests."""

    def test_load_empty_returns_empty(self, tmp_config_dir: Path) -> None:
        assert auth.load_all() == {}

    def test_save_and_load_provider(self, tmp_config_dir: Path) -> None:
        creds = {"type": "oauth", "access": "tok", "refresh": "ref", "expires": 9999999999999}
        auth.save_provider("anthropic", creds)

        loaded = auth.load_provider("anthropic")
        assert loaded is not None
        assert loaded["access"] == "tok"
        assert loaded["refresh"] == "ref"

    def test_save_multiple_providers(self, tmp_config_dir: Path) -> None:
        auth.save_provider("anthropic", {"type": "oauth", "access": "a1", "refresh": "r1", "expires": 0})
        auth.save_provider("openai-codex", {"type": "oauth", "access": "a2", "refresh": "r2", "expires": 0, "accountId": "x"})

        all_data = auth.load_all()
        assert "anthropic" in all_data
        assert "openai-codex" in all_data
        assert all_data["anthropic"]["access"] == "a1"
        assert all_data["openai-codex"]["access"] == "a2"

    def test_clear_provider(self, tmp_config_dir: Path) -> None:
        auth.save_provider("anthropic", {"type": "oauth", "access": "tok", "refresh": "ref", "expires": 0})
        auth.clear_provider("anthropic")
        assert auth.load_provider("anthropic") is None

    def test_clear_nonexistent_is_noop(self, tmp_config_dir: Path) -> None:
        auth.clear_provider("nonexistent")  # should not raise

    def test_load_provider_returns_none_for_missing(self, tmp_config_dir: Path) -> None:
        assert auth.load_provider("nonexistent") is None

    def test_load_provider_rejects_non_oauth(self, tmp_config_dir: Path, auth_path: Path) -> None:
        auth_path.parent.mkdir(parents=True, exist_ok=True)
        auth_path.write_text(json.dumps({"anthropic": {"type": "api-key", "key": "sk-..."}}))
        assert auth.load_provider("anthropic") is None

    def test_file_permissions(self, tmp_config_dir: Path) -> None:
        auth.save_provider("test", {"type": "oauth", "access": "x", "refresh": "y", "expires": 0})
        path = auth._auth_path()
        assert path.exists()
        mode = path.stat().st_mode & 0o777
        assert mode == 0o600


class TestExpiry:
    """Token expiry checks."""

    def test_expired_token(self) -> None:
        creds = {"expires": 0}
        assert auth.is_expired(creds) is True

    def test_future_token_not_expired(self) -> None:
        creds = {"expires": int(time.time() * 1000) + 3600_000}
        assert auth.is_expired(creds) is False

    def test_missing_expires_treated_as_expired(self) -> None:
        creds = {}
        assert auth.is_expired(creds) is True
