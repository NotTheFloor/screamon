"""Sound alert system for screamon."""

import logging
from enum import Enum
from pathlib import Path
from typing import Callable
import threading

logger = logging.getLogger(__name__)

# Default sound directory - try multiple locations
def _find_sound_dir() -> Path:
    """Find the sounds directory."""
    # Try relative to this file (when running from source)
    source_path = Path(__file__).parent.parent.parent.parent / "sounds"
    if source_path.exists():
        return source_path

    # Try current working directory
    cwd_path = Path.cwd() / "sounds"
    if cwd_path.exists():
        return cwd_path

    # Default to source path even if it doesn't exist
    logger.warning("Sound directory not found at %s or %s", source_path, cwd_path)
    return source_path


DEFAULT_SOUND_DIR = _find_sound_dir()


class AlertType(Enum):
    """Types of alerts that can be played."""

    INCREASE = "increase"    # Something increased (usually bad - more players)
    DECREASE = "decrease"    # Something decreased (usually good - fewer players)
    ERROR = "error"          # Detection error / misread
    WARNING = "warning"      # General warning
    INFO = "info"           # Informational


# Default sound file mappings
DEFAULT_SOUNDS = {
    AlertType.INCREASE: "bad.wav",
    AlertType.DECREASE: "ok.wav",
    AlertType.ERROR: "click_x.wav",
    AlertType.WARNING: "buzzer3_x.wav",
    AlertType.INFO: "coin_flip.wav",
}


class SoundPlayer:
    """
    Sound player for alert notifications.

    Supports playing sounds asynchronously to avoid blocking the main thread.
    """

    def __init__(self, sound_dir: Path | str | None = None):
        """
        Initialize the sound player.

        Args:
            sound_dir: Directory containing sound files. Defaults to project sounds/.
        """
        self.sound_dir = Path(sound_dir) if sound_dir else DEFAULT_SOUND_DIR
        self.sounds: dict[AlertType, Path] = {}
        self.enabled = True
        self._load_default_sounds()

    def _load_default_sounds(self) -> None:
        """Load default sound mappings."""
        logger.info("Loading sounds from: %s", self.sound_dir)
        for alert_type, filename in DEFAULT_SOUNDS.items():
            path = self.sound_dir / filename
            if path.exists():
                self.sounds[alert_type] = path
                logger.debug("Loaded sound for %s: %s", alert_type.value, path)
            else:
                logger.warning("Sound file not found: %s", path)
        logger.info("Loaded %d/%d sounds", len(self.sounds), len(DEFAULT_SOUNDS))

    def set_sound(self, alert_type: AlertType, path: Path | str) -> None:
        """
        Set a custom sound for an alert type.

        Args:
            alert_type: The alert type to configure
            path: Path to the sound file
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Sound file not found: {path}")
        self.sounds[alert_type] = path
        logger.info("Set custom sound for %s: %s", alert_type.value, path)

    def play(self, alert_type: AlertType | str, blocking: bool = False) -> None:
        """
        Play a sound for the given alert type.

        Args:
            alert_type: Alert type or alert level string
            blocking: If True, wait for sound to complete. Default False.
        """
        if not self.enabled:
            logger.debug("Sound disabled, skipping %s", alert_type)
            return

        # Convert string to AlertType if needed
        if isinstance(alert_type, str):
            try:
                alert_type = AlertType(alert_type)
            except ValueError:
                logger.warning("Unknown alert type: %s", alert_type)
                return

        sound_path = self.sounds.get(alert_type)
        if sound_path is None:
            logger.warning("No sound configured for %s", alert_type.value)
            return

        if blocking:
            self._play_sound(sound_path)
        else:
            # Play in background thread
            thread = threading.Thread(
                target=self._play_sound,
                args=(sound_path,),
                daemon=True
            )
            thread.start()

    def _play_sound(self, path: Path) -> None:
        """Actually play the sound file using platform-native methods."""
        import platform
        import subprocess

        system = platform.system()

        try:
            if system == "Darwin":
                # macOS: use afplay (built-in)
                subprocess.run(
                    ["afplay", str(path)],
                    check=True,
                    capture_output=True,
                )
            elif system == "Windows":
                # Windows: use winsound (standard library)
                import winsound
                winsound.PlaySound(str(path), winsound.SND_FILENAME)
            else:
                # Linux: try aplay (ALSA) or paplay (PulseAudio)
                try:
                    subprocess.run(
                        ["aplay", "-q", str(path)],
                        check=True,
                        capture_output=True,
                    )
                except FileNotFoundError:
                    # Try PulseAudio
                    subprocess.run(
                        ["paplay", str(path)],
                        check=True,
                        capture_output=True,
                    )
            logger.debug("Played sound: %s", path)
        except FileNotFoundError as e:
            # Native player not found, try simpleaudio as last resort
            logger.warning("Native audio player not found, trying simpleaudio")
            self._play_with_simpleaudio(path)
        except Exception as e:
            logger.error("Failed to play sound %s: %s", path, e)
            # Don't crash on sound errors

    def _play_with_simpleaudio(self, path: Path) -> None:
        """Fallback to simpleaudio library."""
        try:
            import simpleaudio as sa
            wave_obj = sa.WaveObject.from_wave_file(str(path))
            play_obj = wave_obj.play()
            play_obj.wait_done()
            logger.debug("Played sound via simpleaudio: %s", path)
        except ImportError:
            logger.warning("simpleaudio not installed, sound disabled")
            self.enabled = False
        except Exception as e:
            logger.error("simpleaudio failed: %s", e)

    def play_file(self, path: Path | str, blocking: bool = False) -> None:
        """
        Play a specific sound file.

        Args:
            path: Path to sound file
            blocking: If True, wait for sound to complete
        """
        if not self.enabled:
            return

        path = Path(path)
        if not path.exists():
            logger.error("Sound file not found: %s", path)
            return

        if blocking:
            self._play_sound(path)
        else:
            thread = threading.Thread(
                target=self._play_sound,
                args=(path,),
                daemon=True
            )
            thread.start()


# Module-level default player instance
_default_player: SoundPlayer | None = None


def get_player() -> SoundPlayer:
    """Get or create the default sound player."""
    global _default_player
    if _default_player is None:
        _default_player = SoundPlayer()
    return _default_player


def play_alert(alert_type: AlertType | str, blocking: bool = False) -> None:
    """
    Play an alert sound using the default player.

    Args:
        alert_type: Alert type or string like "increase", "decrease", "error"
        blocking: If True, wait for sound to complete
    """
    get_player().play(alert_type, blocking)


def play_for_result(alert_level: str | None, blocking: bool = False) -> None:
    """
    Play appropriate sound for a detector result alert level.

    Args:
        alert_level: Alert level from DetectorResult ("increase", "decrease", "error", None)
        blocking: If True, wait for sound to complete
    """
    if alert_level is None:
        return

    play_alert(alert_level, blocking)


def set_enabled(enabled: bool) -> None:
    """Enable or disable sound alerts globally."""
    get_player().enabled = enabled
    logger.info("Sound alerts %s", "enabled" if enabled else "disabled")
