"""Base class for subscription-based providers (OAuth / cookie auth)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ...models import PROVIDERS, ProviderResult


class SubscriptionProvider(ABC):
    """Base class for providers that authenticate via OAuth tokens or session cookies.

    Subclasses must implement:
    - ``provider_id`` – ID matching a key in ``models.PROVIDERS``
    - ``get_credentials(timeout)`` – return a token/dict, or ``None`` if unavailable
    - ``_fetch(creds, timeout, settings)`` – perform the actual HTTP fetch

    ``__call__`` handles the shared lifecycle:
    1. Resolve credentials → return an error result if missing
    2. Delegate to ``_fetch``
    3. Catch any unhandled exception → return an error result
    """

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Provider ID matching a key in ``models.PROVIDERS``."""
        ...

    @property
    def no_credentials_error(self) -> str:
        """Error message shown when no credentials are found."""
        return (
            f"No credentials found. "
            f"Run `llmeter --login {self.provider_id}` to authenticate."
        )

    @abstractmethod
    async def get_credentials(self, timeout: float) -> Any | None:
        """Return credentials (str token or dict), or ``None`` if unavailable."""
        ...

    @abstractmethod
    async def _fetch(
        self,
        creds: Any,
        timeout: float,
        settings: dict,
    ) -> ProviderResult:
        """Perform the provider-specific fetch using resolved credentials."""
        ...

    async def __call__(
        self,
        timeout: float = 30.0,
        settings: dict | None = None,
    ) -> ProviderResult:
        settings = settings or {}
        result = PROVIDERS[self.provider_id].to_result()

        creds = await self.get_credentials(timeout=timeout)
        if creds is None:
            result.error = self.no_credentials_error
            return result

        try:
            return await self._fetch(creds, timeout=timeout, settings=settings)
        except Exception as e:
            result.error = str(e)
            return result
