"""Image processing filters for the screamon pipeline."""

from typing import Protocol, Union
import logging

import cv2
import numpy as np
from PIL import Image, ImageEnhance

logger = logging.getLogger(__name__)

# Type for images that can be either PIL or numpy array
ImageType = Union[Image.Image, np.ndarray]


class ImageFilter(Protocol):
    """Protocol for image processing filters."""

    name: str

    def apply(self, image: ImageType) -> ImageType:
        """Apply the filter and return processed image."""
        ...


def to_numpy(image: ImageType) -> np.ndarray:
    """Convert PIL Image to numpy array if needed."""
    if isinstance(image, Image.Image):
        return np.array(image)
    return image


def to_pil(image: ImageType) -> Image.Image:
    """Convert numpy array to PIL Image if needed."""
    if isinstance(image, np.ndarray):
        return Image.fromarray(image)
    return image


class UpscaleFilter:
    """Upscale image by a factor using LANCZOS resampling."""

    name = "upscale"

    def __init__(self, factor: int = 2):
        self.factor = factor

    def apply(self, image: ImageType) -> Image.Image:
        pil_image = to_pil(image)
        new_size = (pil_image.width * self.factor, pil_image.height * self.factor)
        return pil_image.resize(new_size, Image.Resampling.LANCZOS)


class ContrastFilter:
    """Enhance image contrast."""

    name = "contrast"

    def __init__(self, factor: float = 2.0):
        self.factor = factor

    def apply(self, image: ImageType) -> Image.Image:
        pil_image = to_pil(image)
        enhancer = ImageEnhance.Contrast(pil_image)
        return enhancer.enhance(self.factor)


class GrayscaleFilter:
    """Convert image to grayscale."""

    name = "grayscale"

    def apply(self, image: ImageType) -> np.ndarray:
        arr = to_numpy(image)
        # Handle different input formats
        if len(arr.shape) == 2:
            # Already grayscale
            return arr
        elif arr.shape[2] == 4:
            # RGBA - convert to RGB first, then grayscale
            rgb = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
            return cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        else:
            # RGB
            return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


class ThresholdFilter:
    """Apply binary thresholding."""

    name = "threshold"

    def __init__(self, value: int = 180):
        self.value = value

    def apply(self, image: ImageType) -> np.ndarray:
        arr = to_numpy(image)
        # Ensure grayscale
        if len(arr.shape) == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        _, thresh = cv2.threshold(arr, self.value, 255, cv2.THRESH_BINARY)
        return thresh


class DenoiseFilter:
    """Apply median blur denoising."""

    name = "denoise"

    def __init__(self, kernel_size: int = 3):
        # Kernel size must be odd
        self.kernel_size = kernel_size if kernel_size % 2 == 1 else kernel_size + 1

    def apply(self, image: ImageType) -> np.ndarray:
        arr = to_numpy(image)
        return cv2.medianBlur(arr, self.kernel_size)


class StarRemovalFilter:
    """
    Remove small bright spots (stars) from EVE backgrounds.

    Uses morphological opening to remove small bright artifacts while
    preserving larger text elements.
    """

    name = "star_removal"

    def __init__(self, kernel_size: int = 3, iterations: int = 1):
        self.kernel_size = kernel_size
        self.iterations = iterations

    def apply(self, image: ImageType) -> np.ndarray:
        arr = to_numpy(image)

        # Convert to grayscale if needed
        if len(arr.shape) == 3:
            if arr.shape[2] == 4:
                arr = cv2.cvtColor(arr, cv2.COLOR_RGBA2GRAY)
            else:
                arr = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)

        # Morphological opening removes small bright spots
        kernel = np.ones((self.kernel_size, self.kernel_size), np.uint8)
        opened = cv2.morphologyEx(arr, cv2.MORPH_OPEN, kernel, iterations=self.iterations)

        return opened


class InvertFilter:
    """Invert image colors (useful for dark backgrounds with light text)."""

    name = "invert"

    def apply(self, image: ImageType) -> np.ndarray:
        arr = to_numpy(image)
        return cv2.bitwise_not(arr)


class AdaptiveThresholdFilter:
    """
    Apply adaptive thresholding for better handling of varying lighting.

    This can work better than fixed thresholding when the background
    brightness varies across the image.
    """

    name = "adaptive_threshold"

    def __init__(self, block_size: int = 11, c: int = 2):
        # Block size must be odd
        self.block_size = block_size if block_size % 2 == 1 else block_size + 1
        self.c = c

    def apply(self, image: ImageType) -> np.ndarray:
        arr = to_numpy(image)
        # Ensure grayscale
        if len(arr.shape) == 3:
            arr = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
        return cv2.adaptiveThreshold(
            arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, self.block_size, self.c
        )


# Registry of available filters
FILTER_REGISTRY: dict[str, type] = {
    "upscale": UpscaleFilter,
    "contrast": ContrastFilter,
    "grayscale": GrayscaleFilter,
    "threshold": ThresholdFilter,
    "denoise": DenoiseFilter,
    "star_removal": StarRemovalFilter,
    "invert": InvertFilter,
    "adaptive_threshold": AdaptiveThresholdFilter,
}


def create_filter(name: str, **params) -> ImageFilter:
    """
    Create a filter instance by name.

    Args:
        name: Filter name from registry
        **params: Parameters to pass to filter constructor

    Returns:
        Filter instance

    Raises:
        ValueError: If filter name not found
    """
    if name not in FILTER_REGISTRY:
        raise ValueError(f"Unknown filter: {name}. Available: {list(FILTER_REGISTRY.keys())}")

    filter_class = FILTER_REGISTRY[name]
    return filter_class(**params)
