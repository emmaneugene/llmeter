"""OpenRouter provider — tracks spend and credits via the OpenRouter API.

Config:
  { "id": "openrouter", "monthly_budget": 20.0 }

Run `llmeter --login openrouter` or set OPENROUTER_API_KEY env var.

API endpoints (Bearer key auth):
- GET https://openrouter.ai/api/v1/key     — key usage and spend limit
- GET https://openrouter.ai/api/v1/credits — purchased credits and lifetime usage

A key-level spend limit, when set, is the primary bar (it self-tracks its
reset period via limit_remaining). Without a limit, monthly_budget is used.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from ...models import (
    CreditsInfo,
    CostInfo,
    PROVIDERS,
    ProviderResult,
    RateWindow,
)
from ..helpers import http_get
from .base import ApiProvider

PROVIDER_KEY = "openrouter"

KEY_URL = "https://openrouter.ai/api/v1/key"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"


class OpenRouterProvider(ApiProvider):
    """Fetches OpenRouter key spend and account credits."""

    @property
    def provider_id(self) -> str:
        return PROVIDER_KEY

    @property
    def no_api_key_error(self) -> str:
        return (
            "OpenRouter API key not configured. "
            "Set OPENROUTER_API_KEY env var or run `llmeter --login openrouter`."
        )

    def resolve_api_key(self, settings: dict) -> Optional[str]:
        from ... import auth as _auth
        key = (
            _auth.load_api_key(self.provider_id)
            or os.environ.get("OPENROUTER_API_KEY")
            or ""
        ).strip()
        return key or None

    async def _fetch(
        self,
        api_key: str,
        timeout: float,
        settings: dict,
    ) -> ProviderResult:
        result = PROVIDERS[PROVIDER_KEY].to_result(source="api")
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        }

        try:
            async with aiohttp.ClientSession() as session:
                key_data = await http_get(
                    PROVIDER_KEY, KEY_URL, headers, timeout,
                    label="key", session=session,
                    errors={
                        401: "OpenRouter rejected the API key (401). Check the key and re-run `llmeter --login openrouter`.",
                        403: "OpenRouter API key forbidden (403).",
                    },
                )

                credits_data = None
                try:
                    credits_data = await http_get(
                        PROVIDER_KEY, CREDITS_URL, headers, timeout,
                        label="credits", session=session,
                    )
                except Exception:
                    pass
        except RuntimeError as e:
            result.error = str(e)
            return result
        except Exception as e:
            result.error = f"OpenRouter API error: {e or type(e).__name__}"
            return result

        _parse_response(key_data, credits_data, settings, result)
        result.updated_at = datetime.now(timezone.utc)
        return result


def _parse_response(
    key_data: dict,
    credits_data: dict | None,
    settings: dict,
    result: ProviderResult,
) -> None:
    key = key_data.get("data") or {}
    limit = _to_float(key.get("limit")) or 0.0
    limit_remaining = _to_float(key.get("limit_remaining"))
    usage = _to_float(key.get("usage")) or 0.0
    monthly = key.get("usage_monthly")
    spent = usage if monthly is None else (_to_float(monthly) or 0.0)

    if limit > 0:
        if limit_remaining is not None:
            spent_against_limit = max(0.0, limit - limit_remaining)
        else:
            spent_against_limit = usage
        pct = min(100.0, (spent_against_limit / limit) * 100.0)
        result.primary = RateWindow(used_percent=pct)
        result.primary_label = f"${spent_against_limit:,.2f} / ${limit:,.2f}"
        result.cost = CostInfo(
            used=round(spent_against_limit, 4),
            limit=limit,
            currency="USD",
            period="Monthly",
        )
    else:
        budget = _parse_monthly_budget(settings)
        if budget > 0:
            pct = min(100.0, (spent / budget) * 100.0)
            result.primary = RateWindow(used_percent=pct)
            result.primary_label = f"${spent:,.2f} / ${budget:,.2f}"
            result.cost = CostInfo(
                used=round(spent, 4),
                limit=budget,
                currency="USD",
                period="Monthly",
            )
        else:
            result.cost = CostInfo(
                used=round(spent, 4),
                limit=0.0,
                currency="USD",
                period="Monthly",
            )

    credits = (credits_data or {}).get("data") or {}
    total_credits = _to_float(credits.get("total_credits"))
    total_usage = _to_float(credits.get("total_usage"))
    if total_credits is not None and total_usage is not None:
        remaining = round(total_credits - total_usage, 2)
        if remaining > 0:
            result.credits = CreditsInfo(remaining=remaining)


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_monthly_budget(settings: dict) -> float:
    try:
        value = float(settings.get("monthly_budget", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


# Module-level singleton — used by backend.py and importable as a callable.
fetch_openrouter = OpenRouterProvider()
