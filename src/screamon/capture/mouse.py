"""Mouse coordinate capture utilities.

This module wraps the bundled mouse library to provide coordinate capture
functionality for calibrating screen regions.
"""

import sys
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Add the project root to path so we can import the bundled mouse module
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import mouse  # noqa: E402

# Type alias for coordinates
Coords = list[list[float]]


def get_position() -> tuple[float, float]:
    """
    Get the current mouse position.

    Returns:
        Tuple of (x, y) coordinates
    """
    return mouse.get_position()


def get_coords(location: str, callback: callable = None) -> Coords:
    """
    Interactively capture coordinates by having user click two corners.

    The user should click the top-left corner first, then the bottom-right corner.

    Args:
        location: Description of what region to click (shown to user)
        callback: Optional callback to invoke with progress updates

    Returns:
        Coordinates as [[x1, y1], [x2, y2]]
    """
    storage = []

    def store_click():
        pos = mouse.get_position()
        storage.append(list(pos))
        logger.debug("Captured click at %s", pos)
        if callback:
            callback(len(storage), pos)

    # Print instructions
    print(f"Please click the top left then bottom right corners of {location}")

    # Register click handler
    mouse.on_pressed(store_click)

    # Wait for two clicks (mouse UP events)
    mouse.wait(target_types=mouse.UP)
    mouse.wait(target_types=mouse.UP)

    # Clean up handlers (mouse library doesn't unhook properly)
    mouse._listener.handlers = []

    logger.info("Captured coordinates for %s: %s", location, storage)
    return storage


def get_coords_async(location: str, on_complete: callable, on_click: callable = None) -> None:
    """
    Asynchronously capture coordinates (non-blocking version for web UI).

    Args:
        location: Description of what region to click
        on_complete: Callback invoked with final coordinates when done
        on_click: Optional callback invoked after each click with click number and position
    """
    import threading

    def capture_thread():
        coords = get_coords(location, callback=on_click)
        on_complete(coords)

    thread = threading.Thread(target=capture_thread, daemon=True)
    thread.start()


class CalibrationSession:
    """
    Manages a calibration session for capturing multiple regions.

    Usage:
        session = CalibrationSession()
        session.add_region("local_count", "Local [x] Corp [x] line")
        session.add_region("overview", "type column in overview")
        session.start(on_complete=handle_results)
    """

    def __init__(self):
        self.regions: list[tuple[str, str]] = []
        self.results: dict[str, Coords] = {}
        self._current_index = 0
        self._on_complete: callable = None
        self._on_progress: callable = None

    def add_region(self, name: str, description: str) -> "CalibrationSession":
        """Add a region to calibrate."""
        self.regions.append((name, description))
        return self

    def start(
        self,
        on_complete: callable,
        on_progress: callable = None,
        blocking: bool = True
    ) -> dict[str, Coords] | None:
        """
        Start the calibration session.

        Args:
            on_complete: Callback with dict of {name: coords} when all done
            on_progress: Optional callback with (region_name, coords) after each region
            blocking: If True, block until complete. If False, run in background thread.

        Returns:
            Results dict if blocking, None if non-blocking
        """
        self._on_complete = on_complete
        self._on_progress = on_progress
        self._current_index = 0
        self.results = {}

        if blocking:
            self._run_calibration()
            return self.results
        else:
            import threading
            thread = threading.Thread(target=self._run_calibration, daemon=True)
            thread.start()
            return None

    def _run_calibration(self):
        """Run through all regions."""
        for name, description in self.regions:
            coords = get_coords(description)
            self.results[name] = coords
            if self._on_progress:
                self._on_progress(name, coords)

        if self._on_complete:
            self._on_complete(self.results)
