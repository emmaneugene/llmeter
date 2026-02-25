"""Entry point for llmeter — run with `python -m llmeter` or `llmeter`."""

from __future__ import annotations

import argparse
import sys

from . import __version__


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="llmeter",
        description="llmeter — Terminal dashboard for AI coding assistant usage limits.",
    )
    parser.add_argument(
        "-V", "--version",
        action="version",
        version=f"llmeter {__version__}",
    )
    parser.add_argument(
        "--refresh",
        type=float,
        default=None,
        metavar="SECONDS",
        help="Auto-refresh interval in seconds (60–3600, default: 300).",
    )
    parser.add_argument(
        "--snapshot",
        action="store_true",
        help="Fetch and print data once to stdout (no TUI), with Rich formatting.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="When used with --snapshot, emit JSON instead of Rich panels.",
    )
    parser.add_argument(
        "--init-config",
        action="store_true",
        help="Create a default config file and exit.",
    )
    parser.add_argument(
        "--login",
        metavar="PROVIDER",
        help="Authenticate with an auth provider.",
    )
    parser.add_argument(
        "--logout",
        metavar="PROVIDER",
        help="Remove stored credentials for an auth provider.",
    )
    args = parser.parse_args()

    if args.init_config:
        from .config import init_config
        init_config()
        return

    if args.login and args.logout:
        print("Specify only one of --login or --logout.", file=sys.stderr)
        sys.exit(2)

    if args.json_output and not args.snapshot:
        print("--json can only be used with --snapshot.", file=sys.stderr)
        sys.exit(2)

    if args.login:
        from .cli.auth import login_provider
        provider = args.login.strip().lower()
        try:
            login_provider(provider)
        except (RuntimeError, KeyboardInterrupt) as e:
            print(f"Login failed: {e}", file=sys.stderr)
            sys.exit(1)
        return

    if args.logout:
        from .cli.auth import logout_provider
        provider = args.logout.strip().lower()
        logout_provider(provider)
        return

    from .config import load_config

    config = load_config()

    # CLI --refresh overrides config (clamped to 60s–3600s)
    if args.refresh is not None:
        from .config import AppConfig
        config.refresh_interval = max(
            AppConfig.MIN_REFRESH, min(AppConfig.MAX_REFRESH, args.refresh)
        )

    if args.snapshot:
        from .cli.snapshot import run_snapshot
        run_snapshot(config, json_output=args.json_output)
        return

    from .app import LLMeterApp

    app = LLMeterApp(config=config)
    app.run()


if __name__ == "__main__":
    main()
