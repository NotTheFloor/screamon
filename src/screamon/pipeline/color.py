"""Color analysis utilities for image processing."""

import logging
from typing import NamedTuple

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class ColorRGB(NamedTuple):
    """RGB color representation."""

    r: int
    g: int
    b: int


# Common EVE Online UI colors
EVE_COLORS = {
    "red_alert": ColorRGB(255, 0, 0),       # Hostile/danger
    "orange_alert": ColorRGB(255, 165, 0),  # Warning
    "yellow": ColorRGB(255, 255, 0),        # Caution
    "green": ColorRGB(0, 255, 0),           # Safe/friendly
    "blue": ColorRGB(0, 0, 255),            # Corp/fleet
    "white": ColorRGB(255, 255, 255),       # Neutral text
}


def color_percentage(
    image: Image.Image,
    target_color: tuple[int, int, int] | ColorRGB,
    tolerance: int = 30
) -> float:
    """
    Calculate percentage of pixels matching target color within tolerance.

    Args:
        image: PIL Image to analyze
        target_color: RGB color to search for
        tolerance: Maximum difference per channel to count as match

    Returns:
        Percentage of pixels matching (0.0 to 1.0)
    """
    arr = np.array(image)

    # Handle different image modes
    if len(arr.shape) == 2:
        # Grayscale - convert target to grayscale for comparison
        target_gray = int(0.299 * target_color[0] + 0.587 * target_color[1] + 0.114 * target_color[2])
        diff = np.abs(arr.astype(int) - target_gray)
        mask = diff <= tolerance
    elif arr.shape[2] == 4:
        # RGBA - ignore alpha channel
        diff = np.abs(arr[:, :, :3].astype(int) - np.array(target_color))
        mask = np.all(diff <= tolerance, axis=2)
    else:
        # RGB
        diff = np.abs(arr.astype(int) - np.array(target_color))
        mask = np.all(diff <= tolerance, axis=2)

    percentage = np.sum(mask) / mask.size
    logger.debug("Color %s percentage: %.2f%%", target_color, percentage * 100)
    return percentage


def detect_red_alert(image: Image.Image, threshold: float = 0.05) -> bool:
    """
    Check if image contains significant red (EVE alert/danger state).

    Args:
        image: Image to analyze
        threshold: Minimum percentage of red pixels (0.0 to 1.0)

    Returns:
        True if red alert detected
    """
    red_pct = color_percentage(image, EVE_COLORS["red_alert"], tolerance=50)
    result = red_pct > threshold
    if result:
        logger.info("Red alert detected: %.2f%% red pixels", red_pct * 100)
    return result


def detect_color_change(
    image1: Image.Image,
    image2: Image.Image,
    color: tuple[int, int, int] | ColorRGB,
    tolerance: int = 30,
    change_threshold: float = 0.02
) -> tuple[bool, float]:
    """
    Detect if a specific color has changed significantly between two images.

    Args:
        image1: First image
        image2: Second image
        color: Color to track
        tolerance: Color matching tolerance
        change_threshold: Minimum change to report

    Returns:
        Tuple of (changed: bool, delta: float where positive = more color)
    """
    pct1 = color_percentage(image1, color, tolerance)
    pct2 = color_percentage(image2, color, tolerance)
    delta = pct2 - pct1

    changed = abs(delta) > change_threshold
    return changed, delta


def dominant_color(image: Image.Image, num_colors: int = 5) -> list[tuple[ColorRGB, float]]:
    """
    Find the dominant colors in an image.

    Args:
        image: Image to analyze
        num_colors: Number of dominant colors to return

    Returns:
        List of (color, percentage) tuples sorted by prevalence
    """
    # Resize for faster processing
    small = image.copy()
    small.thumbnail((100, 100))

    arr = np.array(small)
    if len(arr.shape) == 2:
        # Grayscale - can't find color dominance meaningfully
        return []

    if arr.shape[2] == 4:
        arr = arr[:, :, :3]

    # Flatten to list of pixels
    pixels = arr.reshape(-1, 3)

    # Simple color quantization using unique colors
    unique, counts = np.unique(pixels, axis=0, return_counts=True)

    # Sort by count
    sorted_indices = np.argsort(-counts)

    results = []
    total_pixels = pixels.shape[0]

    for i in sorted_indices[:num_colors]:
        color = ColorRGB(*unique[i])
        percentage = counts[i] / total_pixels
        results.append((color, percentage))

    return results


def brightness_level(image: Image.Image) -> float:
    """
    Calculate average brightness of an image.

    Args:
        image: Image to analyze

    Returns:
        Brightness value from 0.0 (black) to 1.0 (white)
    """
    arr = np.array(image)

    if len(arr.shape) == 2:
        # Already grayscale
        return arr.mean() / 255.0

    if arr.shape[2] == 4:
        arr = arr[:, :, :3]

    # Convert to grayscale using luminosity method
    gray = 0.299 * arr[:, :, 0] + 0.587 * arr[:, :, 1] + 0.114 * arr[:, :, 2]
    return gray.mean() / 255.0
