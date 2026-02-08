"""Screen capture utilities."""

import logging
from PIL import Image, ImageGrab

logger = logging.getLogger(__name__)

# Type alias for bounding box coordinates
# Format: [[x1, y1], [x2, y2]] where (x1, y1) is top-left, (x2, y2) is bottom-right
Coords = list[list[float]]


def capture_region(coords: Coords) -> Image.Image:
    """
    Capture a screenshot of a specific screen region.

    Args:
        coords: Bounding box as [[x1, y1], [x2, y2]]

    Returns:
        PIL Image of the captured region
    """
    if len(coords) != 2 or len(coords[0]) != 2 or len(coords[1]) != 2:
        raise ValueError(f"Invalid coordinates format: {coords}")

    bbox = (
        int(coords[0][0]),  # x1 (left)
        int(coords[0][1]),  # y1 (top)
        int(coords[1][0]),  # x2 (right)
        int(coords[1][1]),  # y2 (bottom)
    )

    logger.debug("Capturing region: %s", bbox)
    return ImageGrab.grab(bbox=bbox)


def capture_full_screen() -> Image.Image:
    """
    Capture the full screen.

    Returns:
        PIL Image of the full screen
    """
    return ImageGrab.grab()


def coords_valid(coords: Coords) -> bool:
    """
    Check if coordinates are valid (non-empty and properly formatted).

    Args:
        coords: Coordinates to validate

    Returns:
        True if valid, False otherwise
    """
    if not coords or len(coords) != 2:
        return False
    if len(coords[0]) != 2 or len(coords[1]) != 2:
        return False
    # Check that x2 > x1 and y2 > y1
    if coords[1][0] <= coords[0][0] or coords[1][1] <= coords[0][1]:
        return False
    return True
