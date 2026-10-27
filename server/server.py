#!/usr/bin/env python3
"""CLI entrypoint for running the FastAPI app with Uvicorn."""

import argparse
import logging
import os

import uvicorn
from pydantic import ValidationError

from .config import ROUTING_MODES, get_settings


def main() -> None:
    try:
        settings = get_settings()
    except ValidationError as exc:
        raise SystemExit(f"Invalid configuration:\n{exc}") from None
    default_host = settings.server_host
    default_port = settings.server_port

    parser = argparse.ArgumentParser(description="OpenPoke FastAPI server")
    parser.add_argument("--host", default=default_host, help=f"Host to bind (default: {default_host})")
    parser.add_argument("--port", type=int, default=default_port, help=f"Port to bind (default: {default_port})")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    parser.add_argument(
        "--routing",
        choices=ROUTING_MODES,
        default=None,
        help=f"Interaction-agent routing mode (default: OPENPOKE_ROUTING, else legacy; now {settings.routing_mode})",
    )
    args = parser.parse_args()

    if args.routing:
        # The environment, not just the cached settings, so uvicorn's reload worker inherits it.
        os.environ["OPENPOKE_ROUTING"] = args.routing
        get_settings.cache_clear()

    from .app import app

    # Reduce uvicorn access log noise - only show warnings and errors
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    # Reduce watchfiles noise during development
    logging.getLogger("watchfiles.main").setLevel(logging.WARNING)
    
    if args.reload:
        # For reload mode, use import string
        uvicorn.run(
            "server.app:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info",
            access_log=False,  # Disable access logs completely for cleaner output
        )
    else:
        # For production mode, use app object directly
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            reload=args.reload,
            log_level="info",
            access_log=False,  # Disable access logs completely for cleaner output
        )


if __name__ == "__main__":  # pragma: no cover - CLI invocation guard
    main()
