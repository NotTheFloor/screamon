"""ESI authentication and API routes for the screamon web dashboard."""

import logging
import webbrowser
from datetime import datetime

from litestar import Controller, Response, delete, get, post
from litestar.exceptions import HTTPException
from litestar.params import Parameter
from litestar.response import Redirect

from ..config import AppConfig
from ..database import Database
from ..esi.auth import ESIAuth
from ..esi.client import ESIClient
from ..esi.models import ESICharacter, ESIToken

logger = logging.getLogger(__name__)


def create_esi_routes(config: AppConfig, db: Database, auth: ESIAuth) -> list:
    """
    Create ESI route handlers with injected dependencies.

    Args:
        config: App configuration
        db: Database instance
        auth: ESI auth handler

    Returns:
        List of route handler classes
    """

    class ESIAuthController(Controller):
        """ESI OAuth2 authentication endpoints."""

        path = "/esi"

        @get("/login")
        async def login(self) -> dict:
            """Generate auth URL and open browser for EVE SSO login."""
            if not config.esi.client_id:
                raise HTTPException(
                    status_code=400,
                    detail="ESI not configured: set esi.client_id in config.json",
                )

            auth_url, state = auth.get_authorization_url()

            # Try to open browser
            try:
                webbrowser.open(auth_url)
            except Exception:
                logger.warning("Could not open browser automatically")

            return {
                "status": "ok",
                "message": "Opening EVE SSO login in browser",
                "auth_url": auth_url,
            }

        @get("/callback")
        async def callback(
            self,
            code: str,
            oauth_state: str = Parameter(query="state"),
        ) -> Response:
            """OAuth2 callback — exchange code for tokens and save character."""
            try:
                token = await auth.exchange_code(code, oauth_state)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            # Encrypt and save the refresh token
            encrypted_refresh = auth.encrypt_refresh_token(token.refresh_token)
            db.save_esi_token(token, encrypted_refresh)

            # Save character info
            character = ESICharacter(
                character_id=token.character_id,
                character_name=token.character_name,
                added_at=datetime.now(),
                is_active=True,
            )

            # If no other character is active, make this one active
            existing_active = db.get_active_esi_character()
            if existing_active is None:
                character.is_active = True
                db.save_esi_character(character)
            else:
                character.is_active = False
                db.save_esi_character(character)

            # Try to fetch public info for corporation/alliance
            try:
                async with ESIClient(auth, token) as client:
                    info = await client.get_character_public_info(token.character_id)
                    character.corporation_id = info.get("corporation_id")
                    character.alliance_id = info.get("alliance_id")
                    db.save_esi_character(character)
            except Exception:
                logger.warning(
                    "Could not fetch public info for character %d", token.character_id
                )

            logger.info(
                "ESI callback: saved character %s (ID: %d)",
                token.character_name, token.character_id,
            )

            return Redirect(path="/static/index.html")

        @get("/status")
        async def status(self) -> dict:
            """Get ESI configuration and authentication status."""
            configured = bool(config.esi.client_id)
            characters = db.get_all_esi_characters()
            active = db.get_active_esi_character()

            return {
                "configured": configured,
                "characters": [
                    {
                        "character_id": c.character_id,
                        "character_name": c.character_name,
                        "is_active": c.is_active,
                    }
                    for c in characters
                ],
                "active_character": {
                    "character_id": active.character_id,
                    "character_name": active.character_name,
                } if active else None,
            }

    class ESICharacterController(Controller):
        """ESI character management endpoints."""

        path = "/api/esi/characters"

        @get("/")
        async def list_characters(self) -> list[dict]:
            """List all authenticated ESI characters."""
            characters = db.get_all_esi_characters()
            return [
                {
                    "character_id": c.character_id,
                    "character_name": c.character_name,
                    "corporation_id": c.corporation_id,
                    "alliance_id": c.alliance_id,
                    "added_at": c.added_at.isoformat(),
                    "is_active": c.is_active,
                }
                for c in characters
            ]

        @post("/{character_id:int}/activate")
        async def activate_character(self, character_id: int) -> dict:
            """Set a character as the active ESI character."""
            character = db.get_esi_character(character_id)
            if character is None:
                raise HTTPException(status_code=404, detail="Character not found")

            db.set_active_esi_character(character_id)
            logger.info("Activated ESI character: %s", character.character_name)

            return {
                "status": "ok",
                "message": f"Activated character {character.character_name}",
            }

        @delete("/{character_id:int}", status_code=200)
        async def remove_character(self, character_id: int) -> dict:
            """Remove an authenticated character (logout)."""
            character = db.get_esi_character(character_id)
            if character is None:
                raise HTTPException(status_code=404, detail="Character not found")

            db.delete_esi_character(character_id)
            logger.info("Removed ESI character: %s", character.character_name)

            return {
                "status": "ok",
                "message": f"Removed character {character.character_name}",
            }

    class ESIDataController(Controller):
        """ESI data endpoints — proxied through the active character."""

        path = "/api/esi/data"

        async def _get_client(self) -> ESIClient:
            """Get an ESI client for the active character."""
            active = db.get_active_esi_character()
            if active is None:
                raise HTTPException(status_code=400, detail="No active ESI character")

            token_row = db.get_esi_token(active.character_id)
            if token_row is None:
                raise HTTPException(status_code=400, detail="No token for active character")

            # Decrypt refresh token and build ESIToken
            refresh_token = auth.decrypt_refresh_token(token_row["refresh_token_encrypted"])
            token = ESIToken(
                character_id=token_row["character_id"],
                character_name=token_row["character_name"],
                access_token=token_row["access_token"],
                refresh_token=refresh_token,
                expires_at=datetime.fromisoformat(token_row["expires_at"]),
                scopes=token_row["scopes"],
            )

            async def on_refresh(new_token: ESIToken) -> None:
                encrypted = auth.encrypt_refresh_token(new_token.refresh_token)
                db.save_esi_token(new_token, encrypted)

            return ESIClient(auth, token, on_token_refresh=on_refresh)

        @get("/location")
        async def get_location(self) -> dict:
            """Get active character's current location."""
            async with await self._get_client() as client:
                return await client.get_character_location()

        @get("/ship")
        async def get_ship(self) -> dict:
            """Get active character's current ship."""
            async with await self._get_client() as client:
                return await client.get_character_ship()

        @get("/online")
        async def get_online(self) -> dict:
            """Get active character's online status."""
            async with await self._get_client() as client:
                return await client.get_character_online()

        @get("/contacts")
        async def get_contacts(self) -> list:
            """Get active character's contacts."""
            async with await self._get_client() as client:
                return await client.get_character_contacts()

        @get("/standings")
        async def get_standings(self) -> list:
            """Get active character's NPC standings."""
            async with await self._get_client() as client:
                return await client.get_character_standings()

        @get("/blueprints")
        async def get_blueprints(self) -> list[dict]:
            """Get active character's blueprints with resolved names."""
            async with await self._get_client() as client:
                blueprints = await client.get_character_blueprints()

                # Resolve type_ids to names
                type_ids = list({bp["type_id"] for bp in blueprints})
                names = await client.resolve_type_names(type_ids)

                # Enrich blueprints with name and BPO/BPC label
                for bp in blueprints:
                    bp["type_name"] = names.get(bp["type_id"], f"Unknown ({bp['type_id']})")
                    if bp["quantity"] == -2:
                        bp["copy"] = True
                    else:
                        bp["copy"] = False

                # Sort by name
                blueprints.sort(key=lambda bp: bp["type_name"])
                return blueprints

    return [ESIAuthController, ESICharacterController, ESIDataController]
