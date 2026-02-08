"""Litestar web server for screamon dashboard."""

import logging
from pathlib import Path

from litestar import Litestar
from litestar.static_files import StaticFilesConfig

from ..config import AppConfig
from ..database import Database

logger = logging.getLogger(__name__)

# Static files directory
STATIC_DIR = Path(__file__).parent / "static"


def create_app(
    config_path: str = "config.json",
    db_path: str = "screamon.db",
) -> Litestar:
    """
    Create the Litestar application.

    Args:
        config_path: Path to config file
        db_path: Path to database

    Returns:
        Configured Litestar app
    """
    # Initialize shared state
    config = AppConfig.load(config_path)
    db = Database(db_path)

    # Import routes here to avoid circular imports
    from .routes import create_routes

    route_handlers = create_routes(config, db, config_path)

    # Add ESI routes (always registered; login endpoint checks for client_id)
    from ..esi.auth import ESIAuth
    from .esi_routes import create_esi_routes

    encryption_key = db.get_or_create_encryption_key()
    esi_auth = ESIAuth(config.esi, encryption_key)
    esi_routes = create_esi_routes(config, db, esi_auth)
    route_handlers.extend(esi_routes)
    if config.esi.client_id:
        logger.info("ESI routes enabled for client_id=%s...", config.esi.client_id[:8])

    app = Litestar(
        route_handlers=route_handlers,
        static_files_config=[
            StaticFilesConfig(
                path="/static",
                directories=[STATIC_DIR],
            ),
        ],
        debug=True,
    )

    logger.info("Created Litestar app with %d routes", len(route_handlers))
    return app


def run_server(
    config_path: str = "config.json",
    db_path: str = "screamon.db",
    host: str = "127.0.0.1",
    port: int = 8080,
) -> None:
    """
    Run the web server.

    Args:
        config_path: Path to config file
        db_path: Path to database
        host: Host to bind to
        port: Port to listen on
    """
    import uvicorn

    logger.info("Starting web server on http://%s:%d", host, port)
    print("\nScreenon Web Dashboard")
    print(f"Open http://{host}:{port} in your browser")
    print("Press Ctrl+C to stop\n")

    # Create app
    app = create_app(config_path=config_path, db_path=db_path)

    # Run with uvicorn
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="info",
    )
