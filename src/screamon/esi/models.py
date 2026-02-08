"""Data models for EVE Online ESI authentication and API."""

import os
from dataclasses import dataclass, field
from datetime import datetime

from dotenv import load_dotenv

# Load .env file (no-op if not present)
load_dotenv()


@dataclass
class ESIConfig:
    """ESI OAuth2 configuration. Loads client_id/client_secret from .env file."""

    client_id: str = field(default_factory=lambda: os.getenv("client_id", ""))
    client_secret: str = field(default_factory=lambda: os.getenv("client_secret", ""))
    callback_port: int = 8080
    callback_path: str = "/esi/callback"
    scopes: list[str] = field(default_factory=lambda: [
        "esi-location.read_location.v1",
        "esi-location.read_ship_type.v1",
        "esi-location.read_online.v1",
        "esi-characters.read_contacts.v1",
        "esi-characters.read_standings.v1",
    ])


@dataclass
class ESIToken:
    """OAuth2 token for an authenticated EVE character."""

    character_id: int
    character_name: str
    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: list[str] = field(default_factory=list)

    @property
    def is_expired(self) -> bool:
        """Check if token is expired (with 60s buffer)."""
        from datetime import timedelta
        return datetime.now() >= (self.expires_at - timedelta(seconds=60))


@dataclass
class ESICharacter:
    """An authenticated EVE character."""

    character_id: int
    character_name: str
    corporation_id: int | None = None
    alliance_id: int | None = None
    added_at: datetime = field(default_factory=datetime.now)
    is_active: bool = False
