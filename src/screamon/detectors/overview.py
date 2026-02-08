"""Detector for overview line count in EVE Online."""

import logging
from dataclasses import dataclass

from .base import BaseDetector

logger = logging.getLogger(__name__)


@dataclass
class OverviewDetector(BaseDetector):
    """
    Detector for the overview panel line count.

    Counts the number of non-empty lines in the overview's type column,
    which represents the number of visible entities (ships, objects, etc.).
    """

    name: str = "overview"
    display_name: str = "Overview Count"
    enabled: bool = True

    def _extract_value(self, text: str) -> int | None:
        """
        Extract line count from OCR text.

        Returns the number of non-empty lines.
        """
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        count = len(lines)
        logger.debug("Extracted overview count: %d lines", count)
        return count

    def _determine_alert_level(self, old_value: int, new_value: int) -> str | None:
        """
        Determine alert level for overview count changes.

        Increase = new entities appeared (potential danger)
        Decrease = entities left (potential safety)
        """
        if new_value > old_value:
            return "increase"
        elif new_value < old_value:
            return "decrease"
        return None

    def get_status(self) -> dict:
        """Get detector status with overview-specific info."""
        status = super().get_status()
        status["entity_count"] = self._last_value
        return status


def create_overview_detector() -> OverviewDetector:
    """Factory function to create an OverviewDetector."""
    return OverviewDetector()
