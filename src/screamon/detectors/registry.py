"""Detector registry for managing available detectors."""

import logging
from typing import Iterator

from .base import Detector
from .local_count import LocalCountDetector
from .overview import OverviewDetector
from .targets import TargetDetector

logger = logging.getLogger(__name__)


class DetectorRegistry:
    """
    Registry for managing detector instances.

    Provides methods for:
    - Registering detectors
    - Looking up detectors by name
    - Iterating over enabled detectors
    """

    def __init__(self):
        self._detectors: dict[str, Detector] = {}

    def register(self, detector: Detector) -> None:
        """
        Register a detector.

        Args:
            detector: Detector instance to register
        """
        self._detectors[detector.name] = detector
        logger.debug("Registered detector: %s", detector.name)

    def unregister(self, name: str) -> Detector | None:
        """
        Unregister a detector by name.

        Args:
            name: Detector name

        Returns:
            Removed detector, or None if not found
        """
        return self._detectors.pop(name, None)

    def get(self, name: str) -> Detector | None:
        """
        Get a detector by name.

        Args:
            name: Detector name

        Returns:
            Detector instance or None if not found
        """
        return self._detectors.get(name)

    def all(self) -> list[Detector]:
        """Get all registered detectors."""
        return list(self._detectors.values())

    def enabled(self) -> list[Detector]:
        """Get all enabled detectors."""
        return [d for d in self._detectors.values() if d.enabled]

    def names(self) -> list[str]:
        """Get all registered detector names."""
        return list(self._detectors.keys())

    def __iter__(self) -> Iterator[Detector]:
        """Iterate over all detectors."""
        return iter(self._detectors.values())

    def __len__(self) -> int:
        """Number of registered detectors."""
        return len(self._detectors)

    def __contains__(self, name: str) -> bool:
        """Check if detector is registered."""
        return name in self._detectors

    def configure_from_config(self, config: dict[str, dict]) -> None:
        """
        Configure detectors from a config dictionary.

        Args:
            config: Dict of {detector_name: {coords, enabled, pipeline, ...}}
        """
        for name, det_config in config.items():
            detector = self.get(name)
            if detector is None:
                logger.warning("Unknown detector in config: %s", name)
                continue

            detector.configure(
                coords=det_config.get("coords", []),
                enabled=det_config.get("enabled", True),
                pipeline=det_config.get("pipeline", "default_ocr"),
            )
            logger.debug("Configured detector %s: enabled=%s", name, detector.enabled)

    def get_all_status(self) -> dict[str, dict]:
        """Get status of all detectors."""
        return {d.name: d.get_status() for d in self._detectors.values()}


def create_default_registry() -> DetectorRegistry:
    """
    Create a registry with all default detectors.

    Returns:
        DetectorRegistry with LocalCount, Overview, and Target detectors
    """
    registry = DetectorRegistry()

    # Register all default detectors
    registry.register(LocalCountDetector())
    registry.register(OverviewDetector())
    registry.register(TargetDetector())

    logger.info("Created default registry with %d detectors", len(registry))
    return registry


# Module-level default registry instance
_default_registry: DetectorRegistry | None = None


def get_default_registry() -> DetectorRegistry:
    """
    Get or create the default detector registry.

    Returns:
        The default DetectorRegistry instance
    """
    global _default_registry
    if _default_registry is None:
        _default_registry = create_default_registry()
    return _default_registry
