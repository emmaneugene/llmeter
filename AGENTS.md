# Overview

**llmeter** is a terminal dashboard for monitoring AI coding assistant usage limits and API spend.

## Tech Stack

- **Language**: Python 3.11+
- **Build system**: Hatchling (`pyproject.toml`)
- **TUI framework**: [Textual](https://textual.textualize.io/) [Rich](https://github.com/Textualize/rich)
- **HTTP library**: [aiohttp](https://docs.aiohttp.org/)
- **Testing**: pytest + pytest-asyncio + aioresponses

## Repository Layout

```
src/llmeter/
├── __main__.py          # CLI entry point
├── app.py               # Main Textual App (dashboard, keybindings, themes)
├── app.tcss             # Textual CSS styles
├── backend.py           # Orchestrates provider fetches
├── config.py            # JSON config (~/.config/llmeter/settings.json)
├── auth.py              # Unified credential store (~/.config/llmeter/auth.json)
├── models.py            # Data models
├── providers/
│   ├── helpers.py       # Shared HTTP utilities (http_get, http_post, debug log)
│   ├── subscription/    # OAuth / cookie-based providers
│   │   ├── base.py      # SubscriptionProvider + LoginProvider ABCs
│   │   └── ...
│   └── api/             # API-key billing providers
│       ├── base.py      # ApiProvider ABC
│       └── ...
└── widgets/
    ├── provider_card.py # Dashboard card widget
    └── usage_bar.py     # Color-coded usage bar widget
```

## Key Conventions

### Code Style

- Use `from __future__ import annotations` in all modules.
- Type hints everywhere; use `Optional` / `X | None` style from `typing`.
- Dataclasses for data models (`models.py`).
- All provider fetchers are callable class instances returning `ProviderResult`.

### Provider Architecture

Providers are split into two categories, each with its own base class:

- **`SubscriptionProvider`** (`subscription/base.py`) — OAuth / cookie auth. Subclasses implement `get_credentials(timeout)` and `_fetch(creds, timeout, settings)`. The base `__call__` handles the shared lifecycle: credential guard, delegation, exception wrapping.
- **`ApiProvider`** (`api/base.py`) — API-key billing. Subclasses implement `resolve_api_key(settings)` and `_fetch(api_key, timeout, settings)`.
- **`LoginProvider`** (`subscription/base.py`) — interactive setup flow. Subclasses implement `interactive_login() -> dict`. No shared runtime behaviour; the base exists to enforce the interface.

Each provider module (`<name>.py`) owns its full runtime path: OAuth constants, credential management (`load/save/clear`, token refresh, `get_valid_*`), the provider class, and a module-level callable singleton (`fetch_<name> = <Name>Provider()`).

Each login module (`<name>_login.py`) owns only the one-time setup machinery (PKCE helpers, callback servers, browser flow, device flow polling) and exposes a module-level `interactive_login = <Name>Login().interactive_login`.

Singletons are registered in `backend.py` via the `PROVIDER_FETCHERS` dict.

**To add a new subscription provider:**
1. Add a `ProviderMeta` entry to `models.py` `PROVIDERS`.
2. Create `providers/subscription/<name>.py` — implement `SubscriptionProvider`, include credential management.
3. Create `providers/subscription/<name>_login.py` — implement `LoginProvider` with the interactive flow.
4. Register `fetch_<name>` in `backend.py` `PROVIDER_FETCHERS`.
5. Add `_login_<name>` / `_logout_<name>` handlers in `__main__.py`.

### Configuration

- App config: `~/.config/llmeter/settings.json` — controls enabled providers, order, API keys, refresh interval.
- Auth store: `~/.config/llmeter/auth.json` — unified OAuth token storage for all providers.
- Config dir follows XDG conventions (`XDG_CONFIG_HOME`).

### Testing

- Tests use `tmp_path` and `monkeypatch` to isolate config/auth from the real filesystem.
- Mock HTTP calls with `aioresponses`.
- Run tests: `pytest` (or `uv run pytest`).
- Async test mode: `asyncio_mode = "auto"` (no need for `@pytest.mark.asyncio`).

### Building & Running

- Install dev deps: `uv sync --extra dev`
- Run locally: `uv run llmeter`
- Snapshot mode: `uv run llmeter --snapshot`
- Run tests: `uv run pytest`

## Important Notes

- OAuth tokens contain secrets — never log or commit `auth.json` contents.
- Provider API responses vary; always handle missing/unexpected fields gracefully with sensible defaults.
- All timestamps in `auth.json` are **milliseconds** since epoch.
