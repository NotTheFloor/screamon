"""Detector for local chat player count in EVE Online."""

import re
import logging
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

from .base import BaseDetector, DetectorResult

logger = logging.getLogger(__name__)


@dataclass
class LocalCountDetector(BaseDetector):
    """
    Detector for the local chat player count.

    Reads the "Local [X] Corp [Y]" text from the chat window header
    and extracts the player count (X).
    """

    name: str = "local_count"
    display_name: str = "Local Chat Count"
    enabled: bool = True

    # OCR patterns for extracting count
    # Pattern: "Local [number] Corp" or "Local (number) Corp"
    _patterns: list[re.Pattern] = field(default_factory=lambda: [
        re.compile(r"[Ll]ocal\s*[\[\(](\d+)[\]\)]"),
        re.compile(r"l\s*[\[\(](\d+)[\]\)]\s*[Cc]"),  # Partial match
    ])

    def _extract_value(self, text: str) -> int | None:
        """
        Extract local player count from OCR text.

        Handles various OCR misreadings of "Local [X] Corp [Y]" format.
        """
        # Try regex patterns first
        for pattern in self._patterns:
            match = pattern.search(text)
            if match:
                try:
                    count = int(match.group(1))
                    logger.debug("Extracted local count %d via regex", count)
                    return count
                except ValueError:
                    continue

        # Fallback: manual parsing (original algorithm)
        return self._manual_extract(text)

    def _manual_extract(self, text: str) -> int | None:
        """
        Manual extraction fallback for edge cases.

        Based on original screamon.py logic with bug fixes.
        """
        # Find 'l' (start of "Local" or just 'l' before bracket)
        local_index = text.find('l')
        corp_index = text.find('C')

        # Skip if we found "Local" - look for 'l' before the bracket
        if local_index != -1 and len(text) > local_index + 1:
            if text[local_index + 1] == 'o':
                local_index = text.find('l', local_index + 1)

        # Validate indices
        if local_index == -1 or corp_index == -1:
            logger.debug("Could not find markers in: %r", text)
            return None

        if local_index > corp_index:
            logger.debug("Invalid marker positions in: %r", text)
            return None

        # Extract substring between markers
        # BUG FIX: original code used wrong variable name
        substring = text[local_index + 1:corp_index]

        if substring.strip() == '':
            return 0

        # Find brackets
        open_idx = substring.find('[')
        if open_idx == -1:
            open_idx = substring.find('(')

        if open_idx == -1:
            logger.debug("No opening bracket in: %r", substring)
            return None

        close_idx = substring.find(']')
        if close_idx == -1:
            close_idx = substring.find(')')

        if close_idx == -1 or close_idx <= open_idx:
            logger.debug("No valid closing bracket in: %r", substring)
            return None

        # Extract and parse number
        number_str = substring[open_idx + 1:close_idx].strip()

        try:
            count = int(number_str)
            logger.debug("Extracted local count %d via manual parse", count)
            return count
        except ValueError:
            logger.debug("Could not parse number from: %r", number_str)
            return None

    def _determine_alert_level(self, old_value: int, new_value: int) -> str | None:
        """
        Determine alert level for local count changes.

        Increase = danger (new players in local)
        Decrease = safe (players left local)
        """
        if new_value > old_value:
            return "increase"  # Bad - more players
        elif new_value < old_value:
            return "decrease"  # Good - fewer players
        return None

    def get_status(self) -> dict:
        """Get detector status with local-specific info."""
        status = super().get_status()
        status["player_count"] = self._last_value
        return status


def create_local_count_detector() -> LocalCountDetector:
    """Factory function to create a LocalCountDetector."""
    return LocalCountDetector()
