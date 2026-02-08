"""SQLite database for screamon state and history."""

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from cryptography.fernet import Fernet

from .esi.models import ESICharacter, ESIToken

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("screamon.db")


@dataclass
class DetectorState:
    """Current state of a detector."""

    name: str
    enabled: bool
    value: Any
    last_changed: datetime | None
    raw_text: str | None = None


@dataclass
class Event:
    """A detection event."""

    id: int | None
    detector: str
    event_type: str  # "increase", "decrease", "error"
    old_value: Any
    new_value: Any
    timestamp: datetime
    raw_text: str | None = None


@dataclass
class Player:
    """A player seen in local chat."""

    id: int | None
    name: str
    first_seen: datetime
    last_seen: datetime
    times_seen: int = 1


class Database:
    """SQLite database manager for screamon."""

    def __init__(self, path: Path | str = DEFAULT_DB_PATH):
        self.path = Path(path)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with self._connect() as conn:
            conn.executescript("""
                -- Detector state table
                CREATE TABLE IF NOT EXISTS detector_state (
                    name TEXT PRIMARY KEY,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    value TEXT,
                    last_changed TEXT,
                    raw_text TEXT
                );

                -- Events history table
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    detector TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    timestamp TEXT NOT NULL,
                    raw_text TEXT
                );

                -- Players seen table (for future use)
                CREATE TABLE IF NOT EXISTS players (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    times_seen INTEGER DEFAULT 1
                );

                -- Runtime config table (for web server communication)
                CREATE TABLE IF NOT EXISTS runtime_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                -- ESI tokens table
                CREATE TABLE IF NOT EXISTS esi_tokens (
                    character_id INTEGER PRIMARY KEY,
                    character_name TEXT NOT NULL,
                    access_token TEXT NOT NULL,
                    refresh_token_encrypted TEXT NOT NULL,
                    token_type TEXT DEFAULT 'Bearer',
                    expires_at TEXT NOT NULL,
                    scopes TEXT DEFAULT ''
                );

                -- ESI characters table
                CREATE TABLE IF NOT EXISTS esi_characters (
                    character_id INTEGER PRIMARY KEY,
                    character_name TEXT NOT NULL,
                    corporation_id INTEGER,
                    alliance_id INTEGER,
                    added_at TEXT NOT NULL,
                    is_active INTEGER DEFAULT 0
                );

                -- ESI encryption key (single-row table)
                CREATE TABLE IF NOT EXISTS esi_encryption (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    fernet_key TEXT NOT NULL
                );

                -- Create indexes for common queries
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_events_detector ON events(detector);
                CREATE INDEX IF NOT EXISTS idx_players_last_seen ON players(last_seen DESC);
            """)
            logger.info("Database initialized at %s", self.path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Context manager for database connections."""
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # Detector State Methods

    def get_detector_state(self, name: str) -> DetectorState | None:
        """Get current state of a detector."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM detector_state WHERE name = ?", (name,)
            ).fetchone()

            if row is None:
                return None

            return DetectorState(
                name=row["name"],
                enabled=bool(row["enabled"]),
                value=json.loads(row["value"]) if row["value"] else None,
                last_changed=datetime.fromisoformat(row["last_changed"]) if row["last_changed"] else None,
                raw_text=row["raw_text"],
            )

    def set_detector_state(self, state: DetectorState) -> None:
        """Update detector state."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO detector_state
                (name, enabled, value, last_changed, raw_text)
                VALUES (?, ?, ?, ?, ?)
            """, (
                state.name,
                int(state.enabled),
                json.dumps(state.value) if state.value is not None else None,
                state.last_changed.isoformat() if state.last_changed else None,
                state.raw_text,
            ))

    def get_all_detector_states(self) -> list[DetectorState]:
        """Get all detector states."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM detector_state").fetchall()
            return [
                DetectorState(
                    name=row["name"],
                    enabled=bool(row["enabled"]),
                    value=json.loads(row["value"]) if row["value"] else None,
                    last_changed=datetime.fromisoformat(row["last_changed"]) if row["last_changed"] else None,
                    raw_text=row["raw_text"],
                )
                for row in rows
            ]

    # Events Methods

    def add_event(self, event: Event) -> int:
        """Add a detection event to history."""
        with self._connect() as conn:
            cursor = conn.execute("""
                INSERT INTO events (detector, event_type, old_value, new_value, timestamp, raw_text)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                event.detector,
                event.event_type,
                json.dumps(event.old_value) if event.old_value is not None else None,
                json.dumps(event.new_value) if event.new_value is not None else None,
                event.timestamp.isoformat(),
                event.raw_text,
            ))
            return cursor.lastrowid

    def get_recent_events(self, limit: int = 50, detector: str | None = None) -> list[Event]:
        """Get recent events, optionally filtered by detector."""
        with self._connect() as conn:
            if detector:
                rows = conn.execute(
                    "SELECT * FROM events WHERE detector = ? ORDER BY timestamp DESC LIMIT ?",
                    (detector, limit)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events ORDER BY timestamp DESC LIMIT ?",
                    (limit,)
                ).fetchall()

            return [
                Event(
                    id=row["id"],
                    detector=row["detector"],
                    event_type=row["event_type"],
                    old_value=json.loads(row["old_value"]) if row["old_value"] else None,
                    new_value=json.loads(row["new_value"]) if row["new_value"] else None,
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    raw_text=row["raw_text"],
                )
                for row in rows
            ]

    # Players Methods (for future use)

    def upsert_player(self, name: str) -> Player:
        """Add or update a player sighting."""
        now = datetime.now()
        with self._connect() as conn:
            # Try to get existing player
            row = conn.execute(
                "SELECT * FROM players WHERE name = ?", (name,)
            ).fetchone()

            if row:
                # Update existing
                conn.execute("""
                    UPDATE players
                    SET last_seen = ?, times_seen = times_seen + 1
                    WHERE name = ?
                """, (now.isoformat(), name))
                return Player(
                    id=row["id"],
                    name=name,
                    first_seen=datetime.fromisoformat(row["first_seen"]),
                    last_seen=now,
                    times_seen=row["times_seen"] + 1,
                )
            else:
                # Insert new
                cursor = conn.execute("""
                    INSERT INTO players (name, first_seen, last_seen, times_seen)
                    VALUES (?, ?, ?, 1)
                """, (name, now.isoformat(), now.isoformat()))
                return Player(
                    id=cursor.lastrowid,
                    name=name,
                    first_seen=now,
                    last_seen=now,
                    times_seen=1,
                )

    def get_recent_players(self, limit: int = 100) -> list[Player]:
        """Get recently seen players."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM players ORDER BY last_seen DESC LIMIT ?",
                (limit,)
            ).fetchall()

            return [
                Player(
                    id=row["id"],
                    name=row["name"],
                    first_seen=datetime.fromisoformat(row["first_seen"]),
                    last_seen=datetime.fromisoformat(row["last_seen"]),
                    times_seen=row["times_seen"],
                )
                for row in rows
            ]

    # Runtime Config Methods (for monitor <-> web communication)

    def set_runtime_config(self, key: str, value: Any) -> None:
        """Set a runtime config value."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO runtime_config (key, value, updated_at)
                VALUES (?, ?, ?)
            """, (key, json.dumps(value), datetime.now().isoformat()))

    def get_runtime_config(self, key: str, default: Any = None) -> Any:
        """Get a runtime config value."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM runtime_config WHERE key = ?", (key,)
            ).fetchone()

            if row is None:
                return default
            return json.loads(row["value"])

    def set_calibration_request(self, detector: str) -> None:
        """Request calibration for a detector (called by web server)."""
        self.set_runtime_config(f"calibrate_{detector}", True)

    def check_calibration_request(self, detector: str) -> bool:
        """Check if calibration was requested (called by monitor)."""
        result = self.get_runtime_config(f"calibrate_{detector}", False)
        if result:
            # Clear the request
            self.set_runtime_config(f"calibrate_{detector}", False)
        return result

    # ESI Token Methods

    def save_esi_token(self, token: ESIToken, encrypted_refresh: str) -> None:
        """Save or update an ESI token."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO esi_tokens
                (character_id, character_name, access_token, refresh_token_encrypted,
                 token_type, expires_at, scopes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                token.character_id,
                token.character_name,
                token.access_token,
                encrypted_refresh,
                "Bearer",
                token.expires_at.isoformat(),
                " ".join(token.scopes),
            ))

    def get_esi_token(self, character_id: int) -> dict | None:
        """Get a stored ESI token row (with encrypted refresh token)."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM esi_tokens WHERE character_id = ?", (character_id,)
            ).fetchone()

            if row is None:
                return None

            return {
                "character_id": row["character_id"],
                "character_name": row["character_name"],
                "access_token": row["access_token"],
                "refresh_token_encrypted": row["refresh_token_encrypted"],
                "expires_at": row["expires_at"],
                "scopes": row["scopes"].split() if row["scopes"] else [],
            }

    def get_all_esi_tokens(self) -> list[dict]:
        """Get all stored ESI token rows."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM esi_tokens").fetchall()
            return [
                {
                    "character_id": row["character_id"],
                    "character_name": row["character_name"],
                    "access_token": row["access_token"],
                    "refresh_token_encrypted": row["refresh_token_encrypted"],
                    "expires_at": row["expires_at"],
                    "scopes": row["scopes"].split() if row["scopes"] else [],
                }
                for row in rows
            ]

    def delete_esi_token(self, character_id: int) -> None:
        """Delete an ESI token."""
        with self._connect() as conn:
            conn.execute("DELETE FROM esi_tokens WHERE character_id = ?", (character_id,))

    # ESI Character Methods

    def save_esi_character(self, character: ESICharacter) -> None:
        """Save or update an ESI character."""
        with self._connect() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO esi_characters
                (character_id, character_name, corporation_id, alliance_id, added_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                character.character_id,
                character.character_name,
                character.corporation_id,
                character.alliance_id,
                character.added_at.isoformat(),
                int(character.is_active),
            ))

    def get_esi_character(self, character_id: int) -> ESICharacter | None:
        """Get an ESI character by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM esi_characters WHERE character_id = ?", (character_id,)
            ).fetchone()

            if row is None:
                return None

            return ESICharacter(
                character_id=row["character_id"],
                character_name=row["character_name"],
                corporation_id=row["corporation_id"],
                alliance_id=row["alliance_id"],
                added_at=datetime.fromisoformat(row["added_at"]),
                is_active=bool(row["is_active"]),
            )

    def get_all_esi_characters(self) -> list[ESICharacter]:
        """Get all ESI characters."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM esi_characters").fetchall()
            return [
                ESICharacter(
                    character_id=row["character_id"],
                    character_name=row["character_name"],
                    corporation_id=row["corporation_id"],
                    alliance_id=row["alliance_id"],
                    added_at=datetime.fromisoformat(row["added_at"]),
                    is_active=bool(row["is_active"]),
                )
                for row in rows
            ]

    def get_active_esi_character(self) -> ESICharacter | None:
        """Get the currently active ESI character."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM esi_characters WHERE is_active = 1"
            ).fetchone()

            if row is None:
                return None

            return ESICharacter(
                character_id=row["character_id"],
                character_name=row["character_name"],
                corporation_id=row["corporation_id"],
                alliance_id=row["alliance_id"],
                added_at=datetime.fromisoformat(row["added_at"]),
                is_active=True,
            )

    def set_active_esi_character(self, character_id: int) -> None:
        """Set a character as the active ESI character (deactivates all others)."""
        with self._connect() as conn:
            conn.execute("UPDATE esi_characters SET is_active = 0")
            conn.execute(
                "UPDATE esi_characters SET is_active = 1 WHERE character_id = ?",
                (character_id,)
            )

    def delete_esi_character(self, character_id: int) -> None:
        """Delete an ESI character and their token."""
        with self._connect() as conn:
            conn.execute("DELETE FROM esi_characters WHERE character_id = ?", (character_id,))
            conn.execute("DELETE FROM esi_tokens WHERE character_id = ?", (character_id,))

    # ESI Encryption Key

    def get_or_create_encryption_key(self) -> bytes:
        """Get or create the Fernet encryption key for ESI token storage."""
        with self._connect() as conn:
            row = conn.execute("SELECT fernet_key FROM esi_encryption WHERE id = 1").fetchone()

            if row is not None:
                return row["fernet_key"].encode()

            # Generate new key
            key = Fernet.generate_key()
            conn.execute(
                "INSERT INTO esi_encryption (id, fernet_key) VALUES (1, ?)",
                (key.decode(),)
            )
            logger.info("Generated new ESI encryption key")
            return key
