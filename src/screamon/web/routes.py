"""API routes for the screamon web dashboard."""

import logging
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator

from litestar import Controller, get, post, put, Response
from litestar.response import Template, Redirect
from litestar.exceptions import HTTPException

from ..config import AppConfig
from ..database import Database

logger = logging.getLogger(__name__)


def create_routes(config: AppConfig, db: Database, config_path: str) -> list:
    """
    Create route handlers with injected dependencies.

    Args:
        config: App configuration
        db: Database instance
        config_path: Path to config file for saving

    Returns:
        List of route handler classes
    """

    class IndexController(Controller):
        """Serve the main dashboard page."""

        path = "/"

        @get()
        async def index(self) -> Response:
            """Redirect to static index.html."""
            return Redirect(path="/static/index.html")

        @get("/favicon.ico")
        async def favicon(self) -> Response:
            """Redirect favicon requests to static file."""
            return Redirect(path="/static/favicon.svg")

    class StatusController(Controller):
        """API endpoints for status information."""

        path = "/api"

        @get("/status")
        async def get_status(self) -> dict:
            """Get current status of all detectors."""
            states = db.get_all_detector_states()
            return {
                "running": True,  # Assume monitor is running if web server is up
                "timestamp": datetime.now().isoformat(),
                "detectors": {
                    state.name: {
                        "enabled": state.enabled,
                        "value": state.value,
                        "last_changed": state.last_changed.isoformat() if state.last_changed else None,
                    }
                    for state in states
                },
            }

        @get("/config")
        async def get_config(self) -> dict:
            """Get current configuration."""
            return {
                "version": config.version,
                "refresh_rate": config.refresh_rate,
                "detectors": {
                    name: {
                        "enabled": det.enabled,
                        "coords": det.coords,
                        "pipeline": det.pipeline,
                    }
                    for name, det in config.detectors.items()
                },
                "pipelines": list(config.pipelines.keys()),
            }

        @put("/config")
        async def update_config(self, data: dict) -> dict:
            """Update configuration."""
            if "refresh_rate" in data:
                config.refresh_rate = float(data["refresh_rate"])

            config.save(config_path)
            logger.info("Configuration updated")
            return {"status": "ok", "message": "Configuration saved"}

    class DetectorController(Controller):
        """API endpoints for detector management."""

        path = "/api/detectors"

        @get("/")
        async def list_detectors(self) -> list[dict]:
            """List all detectors with their status."""
            states = db.get_all_detector_states()
            state_map = {s.name: s for s in states}

            result = []
            for name, det_config in config.detectors.items():
                state = state_map.get(name)
                result.append({
                    "name": name,
                    "enabled": det_config.enabled,
                    "coords_set": len(det_config.coords) == 2,
                    "pipeline": det_config.pipeline,
                    "value": state.value if state else None,
                    "last_changed": state.last_changed.isoformat() if state and state.last_changed else None,
                })
            return result

        @get("/{name:str}")
        async def get_detector(self, name: str) -> dict:
            """Get details for a specific detector."""
            if name not in config.detectors:
                raise HTTPException(status_code=404, detail=f"Detector not found: {name}")

            det_config = config.detectors[name]
            state = db.get_detector_state(name)

            return {
                "name": name,
                "enabled": det_config.enabled,
                "coords": det_config.coords,
                "pipeline": det_config.pipeline,
                "value": state.value if state else None,
                "last_changed": state.last_changed.isoformat() if state and state.last_changed else None,
                "raw_text": state.raw_text if state else None,
            }

        @post("/{name:str}/toggle")
        async def toggle_detector(self, name: str) -> dict:
            """Toggle a detector's enabled state."""
            if name not in config.detectors:
                raise HTTPException(status_code=404, detail=f"Detector not found: {name}")

            det_config = config.detectors[name]
            det_config.enabled = not det_config.enabled
            config.save(config_path)

            # Update database state
            state = db.get_detector_state(name)
            if state:
                state.enabled = det_config.enabled
                db.set_detector_state(state)

            logger.info("Toggled detector %s to %s", name, det_config.enabled)
            return {
                "status": "ok",
                "name": name,
                "enabled": det_config.enabled,
            }

        @post("/{name:str}/calibrate")
        async def request_calibration(self, name: str) -> dict:
            """Request calibration for a detector (handled by monitor process)."""
            if name not in config.detectors:
                raise HTTPException(status_code=404, detail=f"Detector not found: {name}")

            # Set calibration request in database
            db.set_calibration_request(name)
            logger.info("Calibration requested for %s", name)

            return {
                "status": "ok",
                "message": f"Calibration requested for {name}. "
                           "Please click the corners when prompted in the monitor terminal.",
            }

        @post("/{name:str}/pipeline")
        async def set_pipeline(self, name: str, data: dict) -> dict:
            """Set the pipeline for a detector."""
            if name not in config.detectors:
                raise HTTPException(status_code=404, detail=f"Detector not found: {name}")

            pipeline = data.get("pipeline", "default_ocr")
            if pipeline not in config.pipelines:
                raise HTTPException(status_code=400, detail=f"Unknown pipeline: {pipeline}")

            config.detectors[name].pipeline = pipeline
            config.save(config_path)

            logger.info("Set pipeline for %s to %s", name, pipeline)
            return {"status": "ok", "name": name, "pipeline": pipeline}

    class EventsController(Controller):
        """API endpoints for event history."""

        path = "/api/events"

        @get("/")
        async def get_events(self, limit: int = 50, detector: str | None = None) -> list[dict]:
            """Get recent events."""
            events = db.get_recent_events(limit=limit, detector=detector)
            return [
                {
                    "id": e.id,
                    "detector": e.detector,
                    "event_type": e.event_type,
                    "old_value": e.old_value,
                    "new_value": e.new_value,
                    "timestamp": e.timestamp.isoformat(),
                }
                for e in events
            ]

        @get("/stream")
        async def event_stream(self) -> AsyncGenerator[str, None]:
            """
            Server-Sent Events stream for real-time updates.

            Note: This is a simple polling implementation.
            For true real-time, consider using websockets.
            """
            import asyncio

            last_event_id = None

            while True:
                # Get latest events
                events = db.get_recent_events(limit=5)

                # Check for new events
                if events and (last_event_id is None or events[0].id != last_event_id):
                    last_event_id = events[0].id
                    event_data = {
                        "detector": events[0].detector,
                        "event_type": events[0].event_type,
                        "value": events[0].new_value,
                        "timestamp": events[0].timestamp.isoformat(),
                    }
                    yield f"data: {event_data}\n\n"

                # Also send status update
                states = db.get_all_detector_states()
                status_data = {
                    "type": "status",
                    "detectors": {
                        s.name: {"value": s.value, "enabled": s.enabled}
                        for s in states
                    },
                }
                yield f"data: {status_data}\n\n"

                await asyncio.sleep(1)  # Poll every second

    return [IndexController, StatusController, DetectorController, EventsController]
