"""Configuration management for screamon."""

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .esi.models import ESIConfig

logger = logging.getLogger(__name__)

# Type alias for coordinate pairs
Coords = list[list[float]]


@dataclass
class DetectorConfig:
    """Configuration for a single detector."""

    enabled: bool = True
    coords: Coords = field(default_factory=list)
    pipeline: str = "default_ocr"
    options: dict = field(default_factory=dict)


@dataclass
class PipelinePreset:
    """A named image processing pipeline configuration."""

    filters: list[str] = field(default_factory=list)
    params: dict[str, dict] = field(default_factory=dict)


@dataclass
class AppConfig:
    """Main application configuration."""

    version: str = "0.2.0"
    refresh_rate: float = 3.0

    detectors: dict[str, DetectorConfig] = field(default_factory=lambda: {
        "local_count": DetectorConfig(),
        "overview": DetectorConfig(),
        "targets": DetectorConfig(enabled=False),
    })

    pipelines: dict[str, dict] = field(default_factory=lambda: {
        "default_ocr": {
            "filters": ["upscale", "contrast", "grayscale", "threshold"],
            "params": {
                "upscale": {"factor": 2},
                "contrast": {"factor": 2.0},
                "threshold": {"value": 180},
            },
        },
        "star_background": {
            "filters": ["star_removal", "upscale", "contrast", "grayscale", "threshold"],
            "params": {
                "star_removal": {"kernel_size": 3},
                "upscale": {"factor": 2},
                "contrast": {"factor": 2.0},
                "threshold": {"value": 180},
            },
        },
    })

    sounds: dict[str, str] = field(default_factory=lambda: {
        "increase": "sounds/bad.wav",
        "decrease": "sounds/ok.wav",
        "error": "sounds/click_x.wav",
    })

    esi: ESIConfig = field(default_factory=ESIConfig)

    @classmethod
    def load(cls, path: Path | str = Path("config.json")) -> "AppConfig":
        """Load configuration from file, or return defaults if not found."""
        path = Path(path)
        if not path.exists():
            # Try loading from old settings.conf format
            old_path = path.parent / "settings.conf"
            if old_path.exists():
                logger.info("Migrating from old settings.conf format")
                return cls._migrate_v1(old_path)
            return cls()

        with open(path) as f:
            data = json.load(f)

        # Check if this is old format (has COORDS key)
        if "COORDS" in data:
            return cls._migrate_v1_data(data)

        # Parse new format
        return cls._from_dict(data)

    @classmethod
    def _from_dict(cls, data: dict) -> "AppConfig":
        """Create AppConfig from dictionary."""
        config = cls(
            version=data.get("version", cls.version),
            refresh_rate=data.get("refresh_rate", 3.0),
        )

        # Parse detectors
        if "detectors" in data:
            for name, det_data in data["detectors"].items():
                config.detectors[name] = DetectorConfig(
                    enabled=det_data.get("enabled", True),
                    coords=det_data.get("coords", []),
                    pipeline=det_data.get("pipeline", "default_ocr"),
                    options=det_data.get("options", {}),
                )

        # Parse pipelines
        if "pipelines" in data:
            config.pipelines = data["pipelines"]

        # Parse sounds
        if "sounds" in data:
            config.sounds = data["sounds"]

        # Parse ESI config (client_id/client_secret come from .env, not config.json)
        if "esi" in data:
            esi_data = data["esi"]
            config.esi = ESIConfig(
                callback_port=esi_data.get("callback_port", 8080),
                callback_path=esi_data.get("callback_path", "/esi/callback"),
                scopes=esi_data.get("scopes", ESIConfig().scopes),
            )

        return config

    @classmethod
    def _migrate_v1(cls, old_path: Path) -> "AppConfig":
        """Migrate from old settings.conf format."""
        with open(old_path) as f:
            data = json.load(f)
        return cls._migrate_v1_data(data)

    @classmethod
    def _migrate_v1_data(cls, data: dict) -> "AppConfig":
        """Migrate from old settings data format."""
        config = cls()
        coords = data.get("COORDS", [])

        if len(coords) >= 1:
            config.detectors["local_count"].coords = coords[0]
        if len(coords) >= 2:
            config.detectors["overview"].coords = coords[1]
        if len(coords) >= 3:
            config.detectors["targets"].coords = coords[2]

        logger.info("Migrated %d coordinate sets from old format", len(coords))
        return config

    def save(self, path: Path | str = Path("config.json")) -> None:
        """Save configuration to file."""
        path = Path(path)

        # Convert to serializable dict
        data = {
            "version": self.version,
            "refresh_rate": self.refresh_rate,
            "detectors": {
                name: asdict(det) for name, det in self.detectors.items()
            },
            "pipelines": self.pipelines,
            "sounds": self.sounds,
            "esi": {
                "callback_port": self.esi.callback_port,
                "callback_path": self.esi.callback_path,
                "scopes": self.esi.scopes,
            },
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2)

        logger.info("Saved configuration to %s", path)

    def get_detector_config(self, name: str) -> DetectorConfig | None:
        """Get configuration for a specific detector."""
        return self.detectors.get(name)

    def set_detector_enabled(self, name: str, enabled: bool) -> None:
        """Enable or disable a detector."""
        if name in self.detectors:
            self.detectors[name].enabled = enabled

    def set_detector_coords(self, name: str, coords: Coords) -> None:
        """Set coordinates for a detector."""
        if name in self.detectors:
            self.detectors[name].coords = coords
