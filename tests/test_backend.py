"""Tests for backend fetch orchestration."""

from __future__ import annotations

from llmeter import backend
from llmeter.models import PROVIDERS


def test_provider_fetchers_matches_providers_registry() -> None:
    """PROVIDER_FETCHERS and PROVIDERS must stay in sync.

    config.py validates provider IDs against PROVIDERS (to avoid a circular
    import with backend).  This test ensures that every entry in PROVIDERS
    has a corresponding fetcher, so the two registries never drift apart.
    """
    assert backend.PROVIDER_FETCHERS.keys() == PROVIDERS.keys(), (
        f"Mismatch — in PROVIDERS but not PROVIDER_FETCHERS: "
        f"{PROVIDERS.keys() - backend.PROVIDER_FETCHERS.keys()}\n"
        f"In PROVIDER_FETCHERS but not PROVIDERS: "
        f"{backend.PROVIDER_FETCHERS.keys() - PROVIDERS.keys()}"
    )


async def test_fetch_all_respects_explicit_empty_provider_list() -> None:
    results = await backend.fetch_all(provider_ids=[])
    assert results == []


async def test_fetch_one_returns_unknown_provider_error() -> None:
    result = await backend.fetch_one("does-not-exist")

    assert result.provider_id == "does-not-exist"
    assert result.error == "Unknown provider: does-not-exist"


async def test_fetch_all_isolates_provider_errors(
    monkeypatch,
) -> None:
    async def ok_fetcher(*, timeout: float, settings: dict | None = None):
        return backend.PROVIDERS["codex"].to_result(source="test")

    async def bad_fetcher(*, timeout: float, settings: dict | None = None):
        raise RuntimeError("boom")

    monkeypatch.setitem(backend.PROVIDER_FETCHERS, "codex", ok_fetcher)
    monkeypatch.setitem(backend.PROVIDER_FETCHERS, "claude", bad_fetcher)

    results = await backend.fetch_all(provider_ids=["codex", "claude"])

    by_id = {r.provider_id: r for r in results}
    assert by_id["codex"].error is None
    assert by_id["claude"].error == "boom"
