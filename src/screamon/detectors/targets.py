"""Detector for target/asteroid count in EVE Online."""

import logging
from dataclasses import dataclass, field

from .base import BaseDetector

logger = logging.getLogger(__name__)

# Common OCR misreadings of "Asteroid"
ASTEROID_VARIATIONS = [
    "Asteroid",
    "Astroid",     # Common typo
    "Asteraid",    # OCR error
    "Asterpid",    # OCR error
    "Asterocid",   # OCR error
    "Astersid",    # OCR error
    "Asterold",    # OCR error
    "Asterold",    # OCR error (l vs i)
]


@dataclass
class TargetDetector(BaseDetector):
    """
    Detector for the target/asteroid count.

    Counts occurrences of "Asteroid" (and common OCR variations) in the
    target information panel.
    """

    name: str = "targets"
    display_name: str = "Target Count"
    enabled: bool = False  # Disabled by default as per original code

    # Configurable search terms
    search_terms: list[str] = field(default_factory=lambda: ASTEROID_VARIATIONS.copy())

    def _extract_value(self, text: str) -> int | None:
        """
        Extract target count from OCR text.

        Counts occurrences of configured search terms (asteroids by default).
        """
        count = 0
        for term in self.search_terms:
            term_count = text.count(term)
            if term_count > 0:
                logger.debug("Found %d occurrences of '%s'", term_count, term)
            count += term_count

        logger.debug("Total target count: %d", count)
        return count

    def _determine_alert_level(self, old_value: int, new_value: int) -> str | None:
        """
        Determine alert level for target count changes.

        For asteroid mining:
        - Increase = new asteroids selected (positive)
        - Decrease = asteroids depleted/deselected (negative)
        """
        if new_value > old_value:
            return "increase"
        elif new_value < old_value:
            return "decrease"
        return None

    def add_search_term(self, term: str) -> None:
        """Add a search term to look for."""
        if term not in self.search_terms:
            self.search_terms.append(term)
            logger.info("Added search term: %s", term)

    def remove_search_term(self, term: str) -> None:
        """Remove a search term."""
        if term in self.search_terms:
            self.search_terms.remove(term)
            logger.info("Removed search term: %s", term)

    def get_status(self) -> dict:
        """Get detector status with target-specific info."""
        status = super().get_status()
        status["target_count"] = self._last_value
        status["search_terms"] = self.search_terms
        return status


def create_target_detector() -> TargetDetector:
    """Factory function to create a TargetDetector."""
    return TargetDetector()
