"""CLI entry point for the daily snapshot.

Usage:
    python scripts/run_daily.py
    python scripts/run_daily.py --dry-run
    python scripts/run_daily.py --no-x
    python scripts/run_daily.py --no-discord
"""
from __future__ import annotations

import argparse
import logging
import sys

from src.config import load_settings
from src.daily_snapshot.job import run as run_daily_snapshot

log = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Smart Money Daily Snapshot")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build chart and tweet text but skip Discord/X posts.",
    )
    parser.add_argument(
        "--no-x",
        action="store_true",
        help="Skip the X (Twitter) post; still post to Discord.",
    )
    parser.add_argument(
        "--no-discord",
        action="store_true",
        help="Skip the Discord post; still post to X.",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    if args.dry_run:
        settings.dry_run = True
    if args.no_x:
        settings.daily_snapshot.enable_x = False
    if args.no_discord:
        settings.daily_snapshot.enable_discord = False

    try:
        run_daily_snapshot(settings)
    except Exception:
        logging.basicConfig(level=settings.log_level)
        log.exception("daily snapshot failed")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
