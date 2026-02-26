# llmeter

A CLI tool to monitor your LLM subscription and API limits.

![llmeter demo](docs/demo.png)

## Overview

AI-assisted coding is here to stay, and at some point you'll probably be trying to manage your usage on some paid subscriptions. `llmeter` helps you do that without leaving the comfort of the CLI.

## Features

There are a bunch of tools out there that do similar things, but I found that they were either too complex and invasive, or lacking in features. Here's what `llmeter` does:

- **Usage tracking for subscription and API providers**
  - For subscriptions (e.g. Claude, Codex, Cursor), quota follows their respective usage reporting format
  - For API providers (e.g. Anthropic, OpenAI, OpenCode Zen), the quota is spend for the current month with optional budget settings
- **Self-contained** — Login once with OAuth or manually enter cookies/API keys. No dependencies on other having apps running or scraping from local storage. You know exactly how secrets are being fetched and stored.
- **Simple state** — All the state the app needs is persisted at `~/.config/llmeter`
- **Interactive and static usage** — View as an auto-refreshing TUI, or just get a one-time snapshot. Supports JSON output for programmability.

## Supported Providers

### Subscription-based

| Provider | ID | How it works | Auth |
|----------|----|-------------|------|
| **OpenAI ChatGPT** | `codex` | OAuth | `llmeter --login codex` |
| **Anthropic Claude** | `claude` | OAuth | `llmeter --login claude` |
| **Google Gemini** | `gemini` | OAuth | `llmeter --login gemini` |
| **GitHub Copilot** | `copilot` | OAuth (Device Flow) | `llmeter --login copilot` |
| **Cursor** | `cursor` | Cookie | `llmeter --login cursor` |

### API usage

| Provider | ID | How it works | Auth |
|----------|----|-------------|------|
| **OpenAI API** | `openai-api` | `GET /v1/organization/costs` | Admin API key |
| **Anthropic API** | `anthropic-api` | `GET /v1/organizations/cost_report` | Admin API key |
| **Opencode Zen** | `opencode` | Scrapes workspace page | Auth cookie |

> Note: Anthropic API spend data can lag behind real-time usage.

For more information on how usage data is fetched and parsed, see the [docs](./docs/).

## Prerequisites

- Python 3.11+

## Install

### For global usage

Install with `uv`:

```bash
# Install
uv tool install git+https://github.com/emmaneugene/llmeter
# Upgrade
uv tool upgrade llmeter
# Uninstall
uv tool uninstall llmeter
```

Or `pipx`:

```bash
# Install
pipx install git+https://github.com/emmaneugene/llmeter
# Upgrade
pipx upgrade llmeter
# Uninstall
pipx uninstall llmeter
```

Or plain `pip`:

```bash
# Install
pip install git+https://github.com/emmaneugene/llmeter
# Upgrade
pip install --upgrade git+https://github.com/emmaneugene/llmeter
# Uninstall
pip uninstall llmeter
```

### Local development

```bash
uv sync --extra dev
```

## Configuration

Config file lives at `~/.config/llmeter/settings.json`.

For example:

```json
{
  "providers": [
    { "id": "codex", "enabled": true },
    { "id": "claude", "enabled": false },
    { "id": "cursor", "enabled": true },
    {
        "id": "openai-api",
        "api_key": "sk-admin-...",
        "monthly_budget": 50.0 ,
        "enabled": false
    },
    {
        "id": "anthropic-api",
        "api_key": "sk-ant-admin01-...",
        "monthly_budget": 50.0 ,
        "enabled": false
    },
    {
        "id": "opencode",
        "api_key": "<auth-cookie>",
        "monthly_budget": 20.0,
        "enabled": true
    }
  ],
  "refresh_interval": 300
}
```

Generate a default:

```bash
llmeter --init-config
```

Provider-specific settings:

| Setting | Applies to | Description |
|---------|-----------|-------------|
| `api_key` | `openai-api`, `anthropic-api`, `opencode` | Admin API key or auth cookie (overrides env var) |
| `monthly_budget` | `openai-api`, `anthropic-api`, `opencode` | Budget in USD — spend shown as a percentage bar |

### Credential storage

All OAuth credentials are stored in a single file:

```
~/.config/llmeter/auth.json
```

Each provider stores its tokens under a provider key. Tokens are auto-refreshed on each run where applicable. The file is created with `0600` permissions.

### CLI flags

| Flag | Description |
|------|-------------|
| `--snapshot` | Fetch data once and print to stdout (no TUI). |
| `--json` | With `--snapshot`: emit JSON instead of Rich panels. |
| `--refresh SECONDS` | Override auto-refresh interval (60–3600 s). |
| `--login PROVIDER` | Run the interactive login flow for a provider. |
| `--logout PROVIDER` | Remove stored credentials for a provider. |
| `--init-config` | Write a default config file and exit. |
| `--version` | Print version and exit. |

### Environment variables

API keys can also be set via environment variables:

| Variable | Provider | Notes |
|----------|----------|-------|
| `OPENAI_ADMIN_KEY` | `openai-api` | Primary — admin key for costs endpoint |
| `OPENAI_API_KEY` | `openai-api` | Fallback |
| `ANTHROPIC_ADMIN_KEY` | `anthropic-api` | Primary — admin key for cost reports |
| `ANTHROPIC_API_KEY` | `anthropic-api` | Fallback |
| `OPENCODE_AUTH_COOKIE` | `opencode` | Value of the `auth` cookie (see above) |

If no config file exists, no providers are enabled by default. Running `llmeter --login <provider>` will create/update `settings.json` and enable that provider automatically.

### HTTP debug logging

To inspect provider HTTP request/response metadata without disrupting the TUI, enable file-based debug logging:

```bash
LLMETER_DEBUG_HTTP=1 llmeter
```

Logs are written as JSON lines to:

```
~/.config/llmeter/debug.log
```

Optional custom path:

```bash
LLMETER_DEBUG_HTTP=1 LLMETER_DEBUG_LOG_PATH=/tmp/llmeter-debug.log llmeter
```

Logs include full request metadata (including auth headers/tokens/cookies when present).
The debug log file is written with user-only permissions when possible (`0600`).

## References

- **[CodexBar](https://github.com/steipete/CodexBar)** — Original inspiration
- **[pi-mono](https://github.com/badlogic/pi-mono)** — Referenced for OAuth implementations, and my daily driver
- **[ccusage](https://github.com/ryoppippi/ccusage)** — Also very useful for cost tracking
