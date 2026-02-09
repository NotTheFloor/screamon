"""Authenticated HTTP client for EVE Online ESI API."""

import logging
from collections.abc import Awaitable, Callable

import httpx

from .auth import ESIAuth
from .models import ESIToken

logger = logging.getLogger(__name__)

ESI_BASE_URL = "https://esi.evetech.net"
ESI_DATASOURCE = "tranquility"


class ESIClient:
    """Authenticated ESI HTTP client with automatic token refresh."""

    def __init__(
        self,
        auth: ESIAuth,
        token: ESIToken,
        on_token_refresh: Callable[[ESIToken], Awaitable[None]] | None = None,
    ):
        self.auth = auth
        self.token = token
        self._on_token_refresh = on_token_refresh
        self._client = httpx.AsyncClient(base_url=ESI_BASE_URL)

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    async def __aenter__(self) -> "ESIClient":
        return self

    async def __aexit__(self, *args) -> None:
        await self.close()

    async def _ensure_valid_token(self) -> None:
        """Refresh the token if it's expired."""
        if self.token.is_expired:
            logger.debug("Token expired for character %d, refreshing", self.token.character_id)
            self.token = await self.auth.refresh_token(self.token)
            if self._on_token_refresh:
                await self._on_token_refresh(self.token)

    async def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json_body: dict | list | None = None,
    ) -> dict | list:
        """
        Make an authenticated ESI request.

        Args:
            method: HTTP method
            path: API path (e.g., "/v1/characters/{id}/location/")
            params: Query parameters
            json_body: JSON request body

        Returns:
            Parsed JSON response
        """
        await self._ensure_valid_token()

        if params is None:
            params = {}
        params["datasource"] = ESI_DATASOURCE

        headers = {"Authorization": f"Bearer {self.token.access_token}"}

        response = await self._client.request(
            method,
            path,
            params=params,
            json=json_body,
            headers=headers,
        )

        # Check ESI error limit
        error_remain = response.headers.get("X-ESI-Error-Limit-Remain")
        if error_remain and int(error_remain) < 20:
            logger.warning("ESI error limit low: %s remaining", error_remain)

        if response.status_code == 403:
            raise PermissionError(f"ESI access denied: {response.text}")

        response.raise_for_status()
        return response.json()

    async def _request_paginated(
        self,
        method: str,
        path: str,
        params: dict | None = None,
    ) -> list:
        """
        Make a paginated ESI request, fetching all pages.

        Returns:
            Combined list of results from all pages
        """
        await self._ensure_valid_token()

        if params is None:
            params = {}
        params["datasource"] = ESI_DATASOURCE
        params["page"] = 1

        headers = {"Authorization": f"Bearer {self.token.access_token}"}

        # First page
        response = await self._client.request(method, path, params=params, headers=headers)

        error_remain = response.headers.get("X-ESI-Error-Limit-Remain")
        if error_remain and int(error_remain) < 20:
            logger.warning("ESI error limit low: %s remaining", error_remain)

        if response.status_code == 403:
            raise PermissionError(f"ESI access denied: {response.text}")
        response.raise_for_status()

        results = response.json()
        total_pages = int(response.headers.get("X-Pages", "1"))

        # Fetch remaining pages
        for page in range(2, total_pages + 1):
            params["page"] = page
            response = await self._client.request(method, path, params=params, headers=headers)
            response.raise_for_status()
            results.extend(response.json())

        logger.debug("Paginated request %s: %d pages, %d results", path, total_pages, len(results))
        return results

    # Convenience methods

    async def get_character_location(self) -> dict:
        """Get the active character's current location."""
        cid = self.token.character_id
        location = await self._request("GET", f"/v1/characters/{cid}/location/")

        # Resolve solar system name
        if "solar_system_id" in location:
            system = await self.get_solar_system_info(location["solar_system_id"])
            location["solar_system_name"] = system.get("name", "Unknown")

        return location

    async def get_character_ship(self) -> dict:
        """Get the active character's current ship."""
        cid = self.token.character_id
        return await self._request("GET", f"/v1/characters/{cid}/ship/")

    async def get_character_online(self) -> dict:
        """Get the active character's online status."""
        cid = self.token.character_id
        return await self._request("GET", f"/v2/characters/{cid}/online/")

    async def get_character_contacts(self) -> list:
        """Get the active character's contacts."""
        cid = self.token.character_id
        return await self._request("GET", f"/v2/characters/{cid}/contacts/")

    async def get_character_standings(self) -> list:
        """Get the active character's NPC standings."""
        cid = self.token.character_id
        return await self._request("GET", f"/v2/characters/{cid}/standings/")

    async def get_character_public_info(self, character_id: int) -> dict:
        """Get public info for a character."""
        return await self._request("GET", f"/v5/characters/{character_id}/")

    async def get_solar_system_info(self, system_id: int) -> dict:
        """Get info for a solar system."""
        return await self._request("GET", f"/v4/universe/systems/{system_id}/")

    async def get_character_blueprints(self) -> list:
        """Get all blueprints in the active character's inventory (paginated)."""
        cid = self.token.character_id
        return await self._request_paginated("GET", f"/v3/characters/{cid}/blueprints/")

    async def resolve_type_names(self, type_ids: list[int]) -> dict[int, str]:
        """
        Resolve type IDs to names via POST /universe/names/.

        Args:
            type_ids: List of type IDs to resolve

        Returns:
            Dict mapping type_id -> name
        """
        if not type_ids:
            return {}

        names: dict[int, str] = {}
        # API accepts max 1000 IDs per request
        for i in range(0, len(type_ids), 1000):
            batch = type_ids[i:i + 1000]
            try:
                results = await self._request("POST", "/v3/universe/names/", json_body=batch)
                for entry in results:
                    names[entry["id"]] = entry["name"]
            except Exception:
                logger.warning("Failed to resolve %d type names", len(batch))

        return names
