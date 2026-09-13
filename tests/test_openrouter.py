"""Tests for the OpenRouter provider.

Covers:
1. Key-limit-based spend bar (limit_remaining drives the reset period)
2. monthly_budget fallback when no key limit is set
3. Credits enrichment and its failure tolerance
4. Auth errors
"""

from __future__ import annotations

from pathlib import Path

import pytest
from aioresponses import aioresponses

from llmeter.providers.api.openrouter import (
    KEY_URL,
    CREDITS_URL,
    fetch_openrouter,
)

SAMPLE_KEY_WITH_LIMIT = {
    "data": {
        "label": "sk-or-v1-730...c1e",
        "limit": 20,
        "limit_reset": "monthly",
        "limit_remaining": 19.939122,
        "usage": 0.442858649,
        "usage_daily": 0,
        "usage_weekly": 0,
        "usage_monthly": 0.060878,
    },
}

SAMPLE_KEY_NO_LIMIT = {
    "data": {
        "label": "sk-or-v1-730...c1e",
        "limit": None,
        "limit_remaining": None,
        "usage": 0.442858649,
        "usage_monthly": 0.060878,
    },
}

SAMPLE_CREDITS = {
    "data": {
        "total_credits": 20.16,
        "total_usage": 0.598593849,
    },
}


class TestOpenRouterKeyLimit:
    async def test_key_limit_bar(self, tmp_config_dir: Path) -> None:
        with aioresponses() as mocked:
            mocked.get(KEY_URL, payload=SAMPLE_KEY_WITH_LIMIT)
            mocked.get(CREDITS_URL, payload=SAMPLE_CREDITS)

            result = await fetch_openrouter(timeout=5.0)

        assert result.error is None
        assert result.source == "api"
        spent = 20.0 - 19.939122
        assert result.primary.used_percent == pytest.approx(spent / 20.0 * 100.0)
        assert result.primary_label == f"${spent:,.2f} / ${20.0:,.2f}"
        assert result.cost.used == pytest.approx(spent, abs=1e-4)
        assert result.cost.limit == 20.0
        assert result.credits.remaining == pytest.approx(19.56)

    async def test_key_limit_without_remaining_uses_usage(self, tmp_config_dir: Path) -> None:
        data = {
            "data": {
                "limit": 20,
                "limit_remaining": None,
                "usage": 5.0,
                "usage_monthly": 2.0,
            },
        }
        with aioresponses() as mocked:
            mocked.get(KEY_URL, payload=data)

            result = await fetch_openrouter(timeout=5.0)

        assert result.primary.used_percent == pytest.approx(25.0)
        assert result.primary_label == "$5.00 / $20.00"

    async def test_key_limit_without_credits_endpoint(self, tmp_config_dir: Path) -> None:
        """Credits endpoint failure should not break the spend fetch."""
        with aioresponses() as mocked:
            mocked.get(KEY_URL, payload=SAMPLE_KEY_WITH_LIMIT)
            mocked.get(CREDITS_URL, status=500)

            result = await fetch_openrouter(timeout=5.0)

        assert result.error is None
        assert result.primary is not None
        assert result.credits is None


class TestOpenRouterBudget:
    async def test_monthly_budget_fallback(self, tmp_config_dir: Path) -> None:
        with aioresponses() as mocked:
            mocked.get(KEY_URL, payload=SAMPLE_KEY_NO_LIMIT)

            result = await fetch_openrouter(
                timeout=5.0, settings={"monthly_budget": 10.0}
            )

        assert result.primary.used_percent == pytest.approx(0.60878)
        assert result.primary_label == "$0.06 / $10.00"
        assert result.cost.limit == 10.0

    async def test_no_limit_no_budget_cost_only(self, tmp_config_dir: Path) -> None:
        with aioresponses() as mocked:
            mocked.get(KEY_URL, payload=SAMPLE_KEY_NO_LIMIT)

            result = await fetch_openrouter(timeout=5.0)

        assert result.primary is None
        assert result.cost.used == pytest.approx(0.0609)
        assert result.cost.limit == 0.0


class TestOpenRouterAuth:
    async def test_fetch_without_key(self, tmp_config_dir: Path, monkeypatch) -> None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        result = await fetch_openrouter(timeout=5.0)
        assert "OpenRouter API key not configured" in result.error

    async def test_fetch_clears_on_401(self, tmp_config_dir: Path) -> None:
        with aioresponses() as mocked:
            mocked.get(KEY_URL, status=401)

            result = await fetch_openrouter(timeout=5.0)

        assert result.error is not None
        assert "401" in result.error
