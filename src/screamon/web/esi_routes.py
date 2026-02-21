"""ESI authentication and API routes for the screamon web dashboard."""

import logging
import webbrowser
from datetime import datetime

from litestar import Controller, Response, delete, get, post, put
from litestar.exceptions import HTTPException
from litestar.params import Parameter
from litestar.response import Redirect

from ..config import AppConfig
from ..database import Database
from ..esi.auth import ESIAuth
from ..esi.client import ESIClient
from ..esi.models import ESICharacter, ESIToken
from ..market import MarketService
from ..sde import SDEData

logger = logging.getLogger(__name__)


def create_esi_routes(
    config: AppConfig, db: Database, auth: ESIAuth, sde: SDEData, market: MarketService
) -> list:
    """
    Create ESI route handlers with injected dependencies.

    Args:
        config: App configuration
        db: Database instance
        auth: ESI auth handler
        sde: SDE data for blueprint materials
        market: Market price service

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
                logger.warning("Could not fetch public info for character %d", token.character_id)

            logger.info(
                "ESI callback: saved character %s (ID: %d)",
                token.character_name,
                token.character_id,
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
                }
                if active
                else None,
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

        @get("/skills")
        async def get_skills(self) -> dict:
            """Get active character's trained skills."""
            async with await self._get_client() as client:
                return await client.get_character_skills()

        @get("/blueprints")
        async def get_blueprints(self) -> list[dict]:
            """Get active character's blueprints with resolved names."""
            async with await self._get_client() as client:
                blueprints = await client.get_character_blueprints()

                # Resolve type_ids to names
                type_ids = list({bp["type_id"] for bp in blueprints})
                names = await client.resolve_type_names(type_ids)

                # Enrich blueprints with name, BPO/BPC label, and materials
                for bp in blueprints:
                    bp["type_name"] = names.get(bp["type_id"], f"Unknown ({bp['type_id']})")
                    bp["copy"] = bp["quantity"] == -2

                    # Attach SDE manufacturing/reaction materials
                    if sde.is_loaded:
                        mfg = sde.get_blueprint_materials(bp["type_id"])
                        if mfg:
                            bp["materials"] = mfg["materials"]
                            bp["products"] = mfg["products"]
                            bp["manufacturing_time"] = mfg["time"]
                            bp["activity_type"] = mfg["activity_type"]
                        bp["has_invention"] = sde.has_invention(bp["type_id"])
                    bp["is_t2"] = sde.is_t2_blueprint(bp["type_id"])

                # Sort by name
                blueprints.sort(key=lambda bp: bp["type_name"])
                return blueprints

    class FacilityController(Controller):
        """Manufacturing facility CRUD endpoints."""

        path = "/api/facilities"

        @get("/")
        async def list_facilities(self) -> list[dict]:
            """List all saved facilities."""
            return db.get_all_facilities()

        @post("/")
        async def create_facility(self, data: dict) -> dict:
            """Create a new facility."""
            required = ("name", "structure_type_id", "system_name")
            for field in required:
                if field not in data:
                    raise HTTPException(status_code=400, detail=f"Missing required field: {field}")
            facility_id = db.save_facility(data)
            return {"id": facility_id, "status": "ok"}

        @put("/{facility_id:int}")
        async def update_facility(self, facility_id: int, data: dict) -> dict:
            """Update an existing facility."""
            existing = db.get_facility(facility_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Facility not found")
            db.update_facility(facility_id, data)
            return {"status": "ok"}

        @delete("/{facility_id:int}", status_code=200)
        async def delete_facility(self, facility_id: int) -> dict:
            """Delete a facility."""
            existing = db.get_facility(facility_id)
            if existing is None:
                raise HTTPException(status_code=404, detail="Facility not found")
            db.delete_facility(facility_id)
            return {"status": "ok"}

    class SDEController(Controller):
        """SDE data endpoints for static game data."""

        path = "/api/sde"

        @get("/blueprints/{type_id:int}/materials")
        async def get_materials(self, type_id: int) -> dict:
            """Get manufacturing materials for a blueprint type ID."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")

            mfg = sde.get_blueprint_materials(type_id)
            if mfg is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No manufacturing data for type {type_id}",
                )
            return mfg

        @get("/structures")
        async def get_structures(self) -> dict:
            """List all engineering structures with bonuses."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")
            return {str(k): v for k, v in sde.get_structures().items()}

        @get("/rigs")
        async def get_rigs(self) -> dict:
            """List all engineering rigs with bonuses and categories."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")
            return {str(k): v for k, v in sde.get_engineering_rigs().items()}

        @get("/rig-category/{blueprint_type_id:int}")
        async def get_rig_category(self, blueprint_type_id: int) -> dict:
            """Get which rig category applies to a blueprint's product."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")
            category = sde.get_blueprint_rig_category(blueprint_type_id)
            return {
                "blueprint_type_id": blueprint_type_id,
                "rig_category": category,
            }

        @get("/rig-categories")
        async def get_rig_categories(
            self,
            type_ids: str = Parameter(query="type_ids"),
        ) -> dict:
            """Get rig categories for multiple blueprint type IDs.

            Query params:
                type_ids: Comma-separated blueprint type IDs
            """
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")
            ids = [int(x.strip()) for x in type_ids.split(",") if x.strip()]
            categories = {}
            for bp_id in ids:
                cat = sde.get_blueprint_rig_category(bp_id)
                if cat:
                    categories[str(bp_id)] = cat
            return {"categories": categories}

        @get("/blueprints/{type_id:int}/invention")
        async def get_invention(self, type_id: int) -> dict:
            """Get invention data for a blueprint type ID."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")

            inv = sde.get_blueprint_invention(type_id)
            if inv is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No invention data for type {type_id}",
                )
            return inv

        @get("/decryptors")
        async def get_decryptors(self) -> dict:
            """List all decryptors with their modifiers."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")
            return {str(k): v for k, v in sde.get_decryptors().items()}

        @get("/blueprints/{type_id:int}/t2-materials")
        async def get_t2_materials(self, type_id: int) -> dict:
            """Get T2 manufacturing materials for a blueprint (for invention EIV)."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")

            materials = sde.get_t2_blueprint_materials(type_id)
            if materials is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No T2 manufacturing materials for type {type_id}",
                )
            return {"type_id": type_id, "materials": materials}

        @get("/blueprints/{type_id:int}/invention-source")
        async def get_invention_source(self, type_id: int) -> dict:
            """Get the T1 blueprint that invents into this T2 blueprint."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")

            t1_bp_id = sde.get_t1_blueprint_for_t2(type_id)
            if t1_bp_id is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No invention source for type {type_id}",
                )
            return {"t2_blueprint_type_id": type_id, "t1_blueprint_type_id": t1_bp_id}

        @get("/system-security/{system_name:str}")
        async def get_system_security(self, system_name: str) -> dict:
            """Get security status and rig multiplier for a solar system."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")
            system_id = sde.get_system_id(system_name)
            if system_id is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"Solar system '{system_name}' not found",
                )
            security = sde.get_system_security(system_id)
            multiplier = sde.get_security_multiplier(security) if security is not None else 1.0
            return {
                "system_name": sde.get_system_name(system_id),
                "system_id": system_id,
                "security": security,
                "rig_multiplier": multiplier,
            }

    class MarketController(Controller):
        """Market price endpoints with caching."""

        path = "/api/market"

        @get("/prices")
        async def get_prices(
            self,
            type_ids: str = Parameter(query="type_ids"),
        ) -> dict:
            """Get best buy/sell prices for given type IDs.

            Query params:
                type_ids: Comma-separated type IDs (e.g. "34,35,36")
            """
            ids = [int(x.strip()) for x in type_ids.split(",") if x.strip()]
            if not ids:
                raise HTTPException(status_code=400, detail="No type_ids provided")

            prices = await market.get_prices(ids)
            return {
                "prices": {str(k): v for k, v in prices.items()},
                "region_id": market.region_id,
                "location_id": market.location_id,
                "cache": market.cache_stats,
            }

        @get("/eiv/bulk")
        async def get_eiv_bulk(
            self,
            type_ids: str = Parameter(query="type_ids"),
        ) -> dict:
            """Calculate EIV for multiple blueprints in bulk.

            Query params:
                type_ids: Comma-separated blueprint type IDs
            """
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")
            ids = [int(x.strip()) for x in type_ids.split(",") if x.strip()]
            eivs = {}
            for bp_id in ids:
                mfg = sde.get_blueprint_materials(bp_id)
                if mfg is None:
                    continue
                mat_inputs = [
                    {"type_id": m["type_id"], "quantity": m["quantity"]}
                    for m in mfg["materials"]
                ]
                eiv = await market.calculate_eiv(mat_inputs)
                eivs[str(bp_id)] = eiv
            return {"eivs": eivs}

        @get("/eiv/{blueprint_type_id:int}")
        async def get_eiv(self, blueprint_type_id: int) -> dict:
            """Calculate EIV for a blueprint from SDE materials + adjusted prices."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")

            mfg = sde.get_blueprint_materials(blueprint_type_id)
            if mfg is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No manufacturing data for type {blueprint_type_id}",
                )

            # Build material list with type_id and quantity for EIV calc
            mat_inputs = [
                {"type_id": m["type_id"], "quantity": m["quantity"]} for m in mfg["materials"]
            ]
            eiv = await market.calculate_eiv(mat_inputs)

            return {
                "blueprint_type_id": blueprint_type_id,
                "eiv": eiv,
                "materials": mfg["materials"],
            }

        @get("/eiv/invention/{t2_blueprint_type_id:int}")
        async def get_invention_eiv(self, t2_blueprint_type_id: int) -> dict:
            """Calculate EIV for invention from T2 manufacturing materials."""
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")

            materials = sde.get_t2_blueprint_materials(t2_blueprint_type_id)
            if materials is None:
                raise HTTPException(
                    status_code=404,
                    detail=f"No T2 manufacturing materials for type {t2_blueprint_type_id}",
                )

            mat_inputs = [{"type_id": m["type_id"], "quantity": m["quantity"]} for m in materials]
            eiv = await market.calculate_eiv(mat_inputs)

            return {
                "t2_blueprint_type_id": t2_blueprint_type_id,
                "eiv": eiv,
            }

        @get("/system-cost-index")
        async def get_system_cost_index(
            self,
            system: str = Parameter(query="system"),
            activity: str = Parameter(query="activity", default="manufacturing"),
        ) -> dict:
            """Get the industry cost index for a solar system.

            Query params:
                system: Solar system name (e.g. "Serren")
                activity: Activity type (default: "manufacturing")
            """
            if not sde.is_loaded:
                raise HTTPException(status_code=503, detail="SDE data not loaded")

            system_id = sde.get_system_id(system)
            if system_id is None:
                raise HTTPException(status_code=404, detail=f"Solar system '{system}' not found")

            cost_index = await market.get_system_cost_index(system_id, activity)
            return {
                "system_name": sde.get_system_name(system_id),
                "system_id": system_id,
                "activity": activity,
                "cost_index": cost_index,
            }

    class SettingsController(Controller):
        """Global settings endpoints (sales tax, broker fee, etc.)."""

        path = "/api/settings"

        @get("/")
        async def get_settings(self) -> dict:
            """Get current settings."""
            return {
                "sales_tax_rate": db.get_runtime_config("sales_tax_rate", 0.036),
                "broker_fee_rate": db.get_runtime_config("broker_fee_rate", 0.03),
            }

        @put("/")
        async def update_settings(self, data: dict) -> dict:
            """Update settings."""
            if "sales_tax_rate" in data:
                db.set_runtime_config("sales_tax_rate", float(data["sales_tax_rate"]))
            if "broker_fee_rate" in data:
                db.set_runtime_config("broker_fee_rate", float(data["broker_fee_rate"]))
            return {"status": "ok"}

    return [
        ESIAuthController,
        ESICharacterController,
        ESIDataController,
        FacilityController,
        SDEController,
        MarketController,
        SettingsController,
    ]
