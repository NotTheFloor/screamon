"""Detection modules for EVE Online UI elements."""

from .base import Detector, DetectorResult
from .registry import DetectorRegistry, create_default_registry

__all__ = ["Detector", "DetectorResult", "DetectorRegistry", "create_default_registry"]
