"""Main monitoring loop runner."""

import logging
import time
from datetime import datetime
from pathlib import Path

from ..config import AppConfig
from ..database import Database, DetectorState, Event
from ..capture.screen import capture_region, coords_valid
from ..capture.mouse import get_coords, CalibrationSession
from ..detectors.registry import DetectorRegistry, create_default_registry
from ..alerts.sound import play_for_result

logger = logging.getLogger(__name__)


class MonitorRunner:
    """
    Main monitoring loop that coordinates all detectors.

    Responsibilities:
    - Load configuration and initialize detectors
    - Run the main detection loop
    - Handle calibration requests from web UI
    - Write state to database for web server
    - Play audio alerts
    """

    def __init__(
        self,
        config_path: Path | str = Path("config.json"),
        db_path: Path | str = Path("screamon.db"),
    ):
        """
        Initialize the monitor runner.

        Args:
            config_path: Path to config file
            db_path: Path to SQLite database
        """
        self.config_path = Path(config_path)
        self.db_path = Path(db_path)

        self.config: AppConfig | None = None
        self.db: Database | None = None
        self.registry: DetectorRegistry | None = None

        self.running = False
        self._misread_counts: dict[str, int] = {}

    def initialize(self) -> None:
        """Initialize configuration, database, and detectors."""
        logger.info("Initializing monitor runner")

        # Load configuration
        self.config = AppConfig.load(self.config_path)
        logger.info("Loaded config version %s", self.config.version)

        # Initialize database
        self.db = Database(self.db_path)

        # Create detector registry
        self.registry = create_default_registry()

        # Configure detectors from config
        detector_configs = {
            name: {
                "coords": det.coords,
                "enabled": det.enabled,
                "pipeline": det.pipeline,
            }
            for name, det in self.config.detectors.items()
        }
        self.registry.configure_from_config(detector_configs)

        # Initialize detector states in database
        for detector in self.registry:
            state = DetectorState(
                name=detector.name,
                enabled=detector.enabled,
                value=None,
                last_changed=None,
            )
            self.db.set_detector_state(state)

        logger.info("Initialized %d detectors", len(self.registry))

    def calibrate_detector(self, detector_name: str) -> bool:
        """
        Run calibration for a specific detector.

        Args:
            detector_name: Name of detector to calibrate

        Returns:
            True if calibration succeeded
        """
        detector = self.registry.get(detector_name)
        if detector is None:
            logger.error("Unknown detector: %s", detector_name)
            return False

        # Get display name for prompt
        display_name = getattr(detector, 'display_name', detector_name)

        print(f"\nCalibrating {display_name}...")
        coords = get_coords(display_name)

        if not coords_valid(coords):
            logger.error("Invalid coordinates captured: %s", coords)
            return False

        # Update detector
        detector.configure(coords)

        # Update config
        if detector_name in self.config.detectors:
            self.config.detectors[detector_name].coords = coords
            self.config.save(self.config_path)

        logger.info("Calibrated %s with coords: %s", detector_name, coords)
        return True

    def calibrate_all(self) -> None:
        """Run calibration for all detectors."""
        session = CalibrationSession()

        for detector in self.registry:
            display_name = getattr(detector, 'display_name', detector.name)
            session.add_region(detector.name, display_name)

        def on_complete(results: dict):
            for name, coords in results.items():
                detector = self.registry.get(name)
                if detector and coords_valid(coords):
                    detector.configure(coords)
                    if name in self.config.detectors:
                        self.config.detectors[name].coords = coords

            self.config.save(self.config_path)
            logger.info("Calibration complete for %d detectors", len(results))

        session.start(on_complete=on_complete, blocking=True)

    def check_calibration_requests(self) -> None:
        """Check for calibration requests from web UI."""
        for detector in self.registry:
            if self.db.check_calibration_request(detector.name):
                logger.info("Calibration requested for %s", detector.name)
                self.calibrate_detector(detector.name)

    def run_once(self) -> dict[str, any]:
        """
        Run one detection cycle for all enabled detectors.

        Returns:
            Dict of {detector_name: result} for detectors that ran
        """
        results = {}

        for detector in self.registry.enabled():
            # Check if detector has valid coordinates
            if not coords_valid(detector.coords):
                logger.debug("Skipping %s - no coords", detector.name)
                continue

            try:
                # Capture screen region
                image = capture_region(detector.coords)

                # Run detection
                result = detector.detect(image)
                results[detector.name] = result

                # Handle errors
                if result.alert_level == "error":
                    self._misread_counts[detector.name] = self._misread_counts.get(detector.name, 0) + 1
                    if self._misread_counts[detector.name] <= 1 or self._misread_counts[detector.name] > 4:
                        play_for_result("error")
                        self._misread_counts[detector.name] = 1
                    logger.warning("Misread on %s (count: %d)", detector.name, self._misread_counts[detector.name])
                    continue

                # Reset misread count on success
                self._misread_counts[detector.name] = 0

                # Update database state
                state = DetectorState(
                    name=detector.name,
                    enabled=detector.enabled,
                    value=result.value,
                    last_changed=result.timestamp if result.changed else None,
                    raw_text=result.raw_text,
                )
                self.db.set_detector_state(state)

                # Play alert if changed
                if result.changed and result.alert_level:
                    play_for_result(result.alert_level)

                    # Log the change
                    print(f"{detector.display_name}: {result.alert_level} to {result.value}")

                    # Record event
                    event = Event(
                        id=None,
                        detector=detector.name,
                        event_type=result.alert_level,
                        old_value=detector._last_value,
                        new_value=result.value,
                        timestamp=result.timestamp,
                        raw_text=result.raw_text,
                    )
                    self.db.add_event(event)

            except Exception as e:
                logger.error("Error running detector %s: %s", detector.name, e, exc_info=True)

        return results

    def run(self) -> None:
        """
        Run the main monitoring loop.

        This blocks until stopped via stop() or keyboard interrupt.
        """
        if self.config is None:
            self.initialize()

        self.running = True
        refresh_rate = self.config.refresh_rate

        print(f"\nEntering monitoring loop (refresh rate: {refresh_rate}s)")
        print("Press Ctrl+C to stop\n")

        try:
            while self.running:
                loop_start = time.time()

                # Check for calibration requests from web UI
                self.check_calibration_requests()

                # Run detection cycle
                self.run_once()

                # Wait for next cycle
                elapsed = time.time() - loop_start
                sleep_time = max(0, refresh_rate - elapsed)
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\nStopping monitor...")
            self.running = False

    def stop(self) -> None:
        """Stop the monitoring loop."""
        self.running = False
        logger.info("Monitor stop requested")


def run_monitor(
    config_path: str = "config.json",
    db_path: str = "screamon.db",
    calibrate: bool = False,
) -> None:
    """
    Entry point for running the monitor.

    Args:
        config_path: Path to config file
        db_path: Path to database
        calibrate: If True, run calibration before starting
    """
    # Set up logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("\n" + "=" * 50)
    print("  Screamon - EVE Online Screen Reader")
    print("=" * 50 + "\n")

    runner = MonitorRunner(config_path=config_path, db_path=db_path)
    runner.initialize()

    # Check calibration status for each detector
    uncalibrated = []
    calibrated = []
    for detector in runner.registry:
        if detector.enabled:
            if coords_valid(detector.coords):
                calibrated.append(detector.display_name)
            else:
                uncalibrated.append(detector.display_name)

    print("Detector Status:")
    for name in calibrated:
        print(f"  [OK] {name} - calibrated")
    for name in uncalibrated:
        print(f"  [!!] {name} - NEEDS CALIBRATION")

    # Check if any detector needs calibration
    needs_calibration = calibrate or len(uncalibrated) > 0

    if needs_calibration:
        if len(uncalibrated) > 0:
            print(f"\n{len(uncalibrated)} detector(s) need calibration.")
            print("For each detector, click the TOP-LEFT corner, then BOTTOM-RIGHT corner")
            print("of the region you want to monitor.\n")
        runner.calibrate_all()
        print("\nCalibration complete! Settings saved.\n")

    if len(calibrated) == 0 and len(uncalibrated) == 0:
        print("\nNo detectors enabled. Enable detectors in config.json or via web UI.")
        return

    try:
        runner.run()
    except Exception as e:
        logger.exception("Fatal error in monitor loop")
        print(f"\nFATAL ERROR: {e}")
        print("Check the log output above for details.")
        raise
