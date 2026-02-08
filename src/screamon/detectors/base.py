"""Base classes and protocols for detectors."""

from dataclasses import dataclass, field
from typing import Any, Protocol
from datetime import datetime

from PIL import Image


@dataclass
class DetectorResult:
    """Result from a detector run."""

    value: Any                      # The detected value (count, text, list, etc.)
    changed: bool                   # Did value change from last run?
    alert_level: str | None = None  # "increase", "decrease", "error", or None
    raw_text: str | None = None     # Raw OCR output for debugging
    confidence: float | None = None  # OCR confidence if available
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "value": self.value,
            "changed": self.changed,
            "alert_level": self.alert_level,
            "raw_text": self.raw_text,
            "confidence": self.confidence,
            "timestamp": self.timestamp.isoformat(),
        }


class Detector(Protocol):
    """
    Protocol defining the interface for all detectors.

    Detectors are responsible for:
    - Capturing a screen region
    - Processing the image
    - Extracting relevant data
    - Tracking changes between runs
    """

    name: str              # Unique identifier (e.g., "local_count")
    display_name: str      # Human-readable name (e.g., "Local Chat Count")
    enabled: bool          # Whether detector is active

    def configure(self, coords: list, **options) -> None:
        """
        Configure the detector with screen coordinates and options.

        Args:
            coords: Bounding box as [[x1, y1], [x2, y2]]
            **options: Additional detector-specific options
        """
        ...

    def detect(self, image: Image.Image) -> DetectorResult:
        """
        Run detection on a captured image.

        Args:
            image: PIL Image of the screen region

        Returns:
            DetectorResult with detected value and change status
        """
        ...

    def get_status(self) -> dict:
        """
        Get current detector status for display/API.

        Returns:
            Dict with at minimum: enabled, last_value, coords_set
        """
        ...

    def reset(self) -> None:
        """Reset detector state (clear last value, etc.)."""
        ...


@dataclass
class BaseDetector:
    """
    Base implementation of a detector with common functionality.

    Subclasses should override:
    - _extract_value(text) - Extract the relevant value from OCR text
    - _determine_alert_level(old, new) - Determine if change is significant
    """

    name: str = "base"
    display_name: str = "Base Detector"
    enabled: bool = True

    coords: list = field(default_factory=list)
    pipeline_name: str = "default_ocr"

    # Internal state
    _last_value: Any = field(default=None, repr=False)
    _last_raw_text: str | None = field(default=None, repr=False)
    _error_count: int = field(default=0, repr=False)

    def configure(self, coords: list, **options) -> None:
        """Configure detector with coordinates and options."""
        self.coords = coords
        if "pipeline" in options:
            self.pipeline_name = options["pipeline"]
        if "enabled" in options:
            self.enabled = options["enabled"]

    def detect(self, image: Image.Image) -> DetectorResult:
        """
        Run detection on captured image.

        This base implementation handles the common flow:
        1. Process image through pipeline
        2. Extract text via OCR
        3. Parse the value
        4. Determine if changed
        5. Return result
        """
        from ..pipeline.processor import ImageProcessor
        from ..pipeline.ocr import extract_text

        # Process image
        processor = ImageProcessor.from_preset(self.pipeline_name)
        processed = processor.process(image)

        # Extract text
        raw_text = extract_text(processed)

        # Parse value (subclass implements this)
        value = self._extract_value(raw_text)

        # Handle extraction failure
        if value is None:
            self._error_count += 1
            return DetectorResult(
                value=None,
                changed=False,
                alert_level="error",
                raw_text=raw_text,
            )

        # Determine if changed
        changed = value != self._last_value
        alert_level = None

        if changed and self._last_value is not None:
            alert_level = self._determine_alert_level(self._last_value, value)

        # Update state
        old_value = self._last_value
        self._last_value = value
        self._last_raw_text = raw_text
        self._error_count = 0

        return DetectorResult(
            value=value,
            changed=changed,
            alert_level=alert_level,
            raw_text=raw_text,
        )

    def _extract_value(self, text: str) -> Any:
        """
        Extract the relevant value from OCR text.

        Override in subclasses.

        Args:
            text: Raw OCR text

        Returns:
            Extracted value, or None if extraction failed
        """
        raise NotImplementedError("Subclasses must implement _extract_value")

    def _determine_alert_level(self, old_value: Any, new_value: Any) -> str | None:
        """
        Determine the alert level for a change.

        Override in subclasses for custom logic.

        Args:
            old_value: Previous value
            new_value: New value

        Returns:
            Alert level string or None
        """
        return None

    def get_status(self) -> dict:
        """Get current detector status."""
        return {
            "name": self.name,
            "display_name": self.display_name,
            "enabled": self.enabled,
            "last_value": self._last_value,
            "coords_set": len(self.coords) == 2,
            "error_count": self._error_count,
        }

    def reset(self) -> None:
        """Reset detector state."""
        self._last_value = None
        self._last_raw_text = None
        self._error_count = 0
