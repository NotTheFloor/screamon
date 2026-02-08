"""Template matching utilities for image recognition."""

import logging
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class Match(NamedTuple):
    """A template match result."""

    x: int           # Top-left x coordinate
    y: int           # Top-left y coordinate
    width: int       # Template width
    height: int      # Template height
    confidence: float  # Match confidence (0-1)


class TemplateMatcher:
    """
    Match template images against screen captures.

    Useful for detecting specific UI elements, icons, or patterns
    that are consistent across sessions.
    """

    def __init__(self, template_dir: Path | str | None = None):
        """
        Initialize the template matcher.

        Args:
            template_dir: Directory containing template images.
                         If None, templates must be added manually.
        """
        self.templates: dict[str, np.ndarray] = {}
        self.template_sizes: dict[str, tuple[int, int]] = {}

        if template_dir:
            self.load_templates(Path(template_dir))

    def load_templates(self, directory: Path) -> int:
        """
        Load all PNG templates from a directory.

        Args:
            directory: Directory containing template images

        Returns:
            Number of templates loaded
        """
        if not directory.exists():
            logger.warning("Template directory not found: %s", directory)
            return 0

        count = 0
        for path in directory.glob("*.png"):
            try:
                self.add_template(path.stem, path)
                count += 1
            except Exception as e:
                logger.error("Failed to load template %s: %s", path, e)

        logger.info("Loaded %d templates from %s", count, directory)
        return count

    def add_template(self, name: str, path: Path | str) -> None:
        """
        Add a template image.

        Args:
            name: Unique name for this template
            path: Path to template image file
        """
        path = Path(path)
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            raise ValueError(f"Could not load template: {path}")

        self.templates[name] = img
        self.template_sizes[name] = (img.shape[1], img.shape[0])  # (width, height)
        logger.debug("Added template '%s' (%dx%d)", name, img.shape[1], img.shape[0])

    def add_template_from_image(self, name: str, image: Image.Image) -> None:
        """
        Add a template from a PIL Image.

        Args:
            name: Unique name for this template
            image: PIL Image to use as template
        """
        arr = np.array(image)
        if len(arr.shape) == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        self.templates[name] = arr
        self.template_sizes[name] = (arr.shape[1], arr.shape[0])
        logger.debug("Added template '%s' from image (%dx%d)", name, arr.shape[1], arr.shape[0])

    def find(
        self,
        image: Image.Image | np.ndarray,
        template_name: str,
        threshold: float = 0.8,
    ) -> list[Match]:
        """
        Find all occurrences of a template in an image.

        Args:
            image: Image to search in
            template_name: Name of template to find
            threshold: Minimum confidence (0-1) for a match

        Returns:
            List of Match objects for each found instance
        """
        template = self.templates.get(template_name)
        if template is None:
            logger.warning("Unknown template: %s", template_name)
            return []

        # Convert image to grayscale numpy array
        if isinstance(image, Image.Image):
            arr = np.array(image)
            if len(arr.shape) == 3:
                arr = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        else:
            arr = image
            if len(arr.shape) == 3:
                arr = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)

        # Perform template matching
        result = cv2.matchTemplate(arr, template, cv2.TM_CCOEFF_NORMED)

        # Find all locations above threshold
        locations = np.where(result >= threshold)
        width, height = self.template_sizes[template_name]

        matches = []
        for pt in zip(*locations[::-1]):  # Switch x and y
            confidence = result[pt[1], pt[0]]
            matches.append(Match(
                x=pt[0],
                y=pt[1],
                width=width,
                height=height,
                confidence=float(confidence),
            ))

        # Remove overlapping matches (non-maximum suppression)
        matches = self._nms(matches)

        logger.debug("Found %d matches for '%s' (threshold=%.2f)", len(matches), template_name, threshold)
        return matches

    def find_best(
        self,
        image: Image.Image | np.ndarray,
        template_name: str,
        threshold: float = 0.8,
    ) -> Match | None:
        """
        Find the best match for a template.

        Args:
            image: Image to search in
            template_name: Name of template to find
            threshold: Minimum confidence for a valid match

        Returns:
            Best Match, or None if no match above threshold
        """
        matches = self.find(image, template_name, threshold)
        if not matches:
            return None

        # Return highest confidence match
        return max(matches, key=lambda m: m.confidence)

    def exists(
        self,
        image: Image.Image | np.ndarray,
        template_name: str,
        threshold: float = 0.8,
    ) -> bool:
        """
        Check if a template exists in the image.

        Args:
            image: Image to search in
            template_name: Name of template to find
            threshold: Minimum confidence

        Returns:
            True if template found
        """
        match = self.find_best(image, template_name, threshold)
        return match is not None

    def _nms(self, matches: list[Match], overlap_threshold: float = 0.5) -> list[Match]:
        """
        Non-maximum suppression to remove overlapping matches.

        Args:
            matches: List of matches to filter
            overlap_threshold: IoU threshold for considering overlap

        Returns:
            Filtered list of matches
        """
        if not matches:
            return []

        # Sort by confidence
        matches = sorted(matches, key=lambda m: m.confidence, reverse=True)

        kept = []
        for match in matches:
            # Check overlap with already kept matches
            overlaps = False
            for kept_match in kept:
                if self._iou(match, kept_match) > overlap_threshold:
                    overlaps = True
                    break

            if not overlaps:
                kept.append(match)

        return kept

    def _iou(self, m1: Match, m2: Match) -> float:
        """Calculate Intersection over Union for two matches."""
        # Calculate intersection
        x1 = max(m1.x, m2.x)
        y1 = max(m1.y, m2.y)
        x2 = min(m1.x + m1.width, m2.x + m2.width)
        y2 = min(m1.y + m1.height, m2.y + m2.height)

        if x2 <= x1 or y2 <= y1:
            return 0.0

        intersection = (x2 - x1) * (y2 - y1)

        # Calculate union
        area1 = m1.width * m1.height
        area2 = m2.width * m2.height
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0


# Singleton matcher for convenience
_default_matcher: TemplateMatcher | None = None


def get_matcher() -> TemplateMatcher:
    """Get or create the default template matcher."""
    global _default_matcher
    if _default_matcher is None:
        _default_matcher = TemplateMatcher()
    return _default_matcher


def find_template(
    image: Image.Image | np.ndarray,
    template_name: str,
    threshold: float = 0.8,
) -> list[Match]:
    """
    Find template using default matcher.

    Args:
        image: Image to search
        template_name: Template name
        threshold: Match threshold

    Returns:
        List of matches
    """
    return get_matcher().find(image, template_name, threshold)
