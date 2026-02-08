"""Image processing pipeline orchestrator."""

from dataclasses import dataclass, field
import logging
from typing import Any

from PIL import Image
import numpy as np

from .filters import FILTER_REGISTRY, create_filter, to_pil, ImageFilter

logger = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    """Configuration for an image processing pipeline."""

    filters: list[str] = field(default_factory=list)
    params: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def default_ocr(cls) -> "PipelineConfig":
        """Default pipeline for OCR text extraction."""
        return cls(
            filters=["upscale", "contrast", "grayscale", "threshold"],
            params={
                "upscale": {"factor": 2},
                "contrast": {"factor": 2.0},
                "threshold": {"value": 180},
            },
        )

    @classmethod
    def star_background(cls) -> "PipelineConfig":
        """Pipeline for regions with star backgrounds."""
        return cls(
            filters=["star_removal", "upscale", "contrast", "grayscale", "threshold"],
            params={
                "star_removal": {"kernel_size": 3},
                "upscale": {"factor": 2},
                "contrast": {"factor": 2.0},
                "threshold": {"value": 180},
            },
        )

    @classmethod
    def high_contrast(cls) -> "PipelineConfig":
        """Pipeline for low-contrast text."""
        return cls(
            filters=["upscale", "contrast", "grayscale", "adaptive_threshold"],
            params={
                "upscale": {"factor": 2},
                "contrast": {"factor": 3.0},
                "adaptive_threshold": {"block_size": 11, "c": 2},
            },
        )


class ImageProcessor:
    """
    Configurable image processing pipeline.

    Chains multiple filters together to process images for OCR or other analysis.
    """

    def __init__(self, config: PipelineConfig | None = None):
        """
        Initialize processor with given config.

        Args:
            config: Pipeline configuration. If None, uses default_ocr.
        """
        self.config = config or PipelineConfig.default_ocr()
        self._filters: list[ImageFilter] = []
        self._build_filters()

    def _build_filters(self) -> None:
        """Build filter instances from config."""
        self._filters = []
        for filter_name in self.config.filters:
            params = self.config.params.get(filter_name, {})
            try:
                filter_instance = create_filter(filter_name, **params)
                self._filters.append(filter_instance)
                logger.debug("Added filter: %s with params %s", filter_name, params)
            except ValueError as e:
                logger.error("Failed to create filter %s: %s", filter_name, e)
                raise

    def process(self, image: Image.Image) -> Image.Image:
        """
        Run image through all filters in the pipeline.

        Args:
            image: Input PIL Image

        Returns:
            Processed PIL Image
        """
        result = image
        for f in self._filters:
            result = f.apply(result)
            logger.debug("Applied filter: %s", f.name)

        # Ensure output is PIL Image
        return to_pil(result)

    def process_to_array(self, image: Image.Image) -> np.ndarray:
        """
        Run image through pipeline and return as numpy array.

        Args:
            image: Input PIL Image

        Returns:
            Processed image as numpy array
        """
        result = self.process(image)
        return np.array(result)

    @classmethod
    def default_ocr(cls) -> "ImageProcessor":
        """Create processor with default OCR pipeline."""
        return cls(PipelineConfig.default_ocr())

    @classmethod
    def star_background(cls) -> "ImageProcessor":
        """Create processor for star background regions."""
        return cls(PipelineConfig.star_background())

    @classmethod
    def from_preset(cls, preset_name: str) -> "ImageProcessor":
        """
        Create processor from a preset name.

        Args:
            preset_name: One of "default_ocr", "star_background", "high_contrast"

        Returns:
            ImageProcessor configured with the preset

        Raises:
            ValueError: If preset name not recognized
        """
        presets = {
            "default_ocr": PipelineConfig.default_ocr,
            "star_background": PipelineConfig.star_background,
            "high_contrast": PipelineConfig.high_contrast,
        }

        if preset_name not in presets:
            raise ValueError(f"Unknown preset: {preset_name}. Available: {list(presets.keys())}")

        return cls(presets[preset_name]())


# Convenience function for simple use cases
def process_for_ocr(image: Image.Image) -> Image.Image:
    """
    Process an image for OCR using default settings.

    Args:
        image: Input image

    Returns:
        Processed image ready for OCR
    """
    processor = ImageProcessor.default_ocr()
    return processor.process(image)
