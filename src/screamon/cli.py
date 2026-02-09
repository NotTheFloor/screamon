"""Command-line interface entry points for screamon."""

import argparse
import logging
import sys
from pathlib import Path


def run_monitor() -> None:
    """Entry point for the screamon monitor command."""
    parser = argparse.ArgumentParser(
        description="EVE Online screen reader - monitors game UI and plays audio alerts"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Path to config file (default: config.json)"
    )
    parser.add_argument(
        "-d", "--database",
        default="screamon.db",
        help="Path to database file (default: screamon.db)"
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="Force calibration before starting"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit"
    )

    args = parser.parse_args()

    if args.version:
        from . import __version__
        print(f"screamon version {__version__}")
        return

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Import here to avoid circular imports and speed up --help
    from .monitor.runner import run_monitor as _run_monitor

    _run_monitor(
        config_path=args.config,
        db_path=args.database,
        calibrate=args.calibrate,
    )


def run_web() -> None:
    """Entry point for the screamon-web server command."""
    parser = argparse.ArgumentParser(
        description="EVE Online screen reader - web dashboard server"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.json",
        help="Path to config file (default: config.json)"
    )
    parser.add_argument(
        "-d", "--database",
        default="screamon.db",
        help="Path to database file (default: screamon.db)"
    )
    parser.add_argument(
        "-p", "--port",
        type=int,
        default=8080,
        help="Port to run server on (default: 8080)"
    )
    parser.add_argument(
        "-H", "--host",
        default="127.0.0.1",
        help="Host to bind to (default: 127.0.0.1)"
    )
    parser.add_argument(
        "-s", "--sde",
        default="sde",
        help="Path to SDE data directory (default: sde)"
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help="Show version and exit"
    )

    args = parser.parse_args()

    if args.version:
        from . import __version__
        print(f"screamon version {__version__}")
        return

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Import here to avoid circular imports
    from .web.server import run_server

    run_server(
        config_path=args.config,
        db_path=args.database,
        host=args.host,
        port=args.port,
        sde_path=args.sde,
    )


def main() -> None:
    """Main entry point that shows usage if called directly."""
    print("Screamon - EVE Online Screen Reader")
    print()
    print("Available commands:")
    print("  screamon      - Run the monitor (detection loop)")
    print("  screamon-web  - Run the web dashboard server")
    print()
    print("Use --help with each command for more options.")


if __name__ == "__main__":
    main()
