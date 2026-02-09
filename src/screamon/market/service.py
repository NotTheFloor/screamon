"""Cached market price lookups via public ESI market orders endpoint."""

import asyncio
import logging
import time

import httpx

logger = logging.getLogger(__name__)

ESI_BASE_URL = "https://esi.evetech.net"
CACHE_TTL = 300  # 5 minutes, matches ESI cache


class MarketService:
    """Fetches and caches best buy/sell prices from ESI public market data."""

    def __init__(self, region_id: int = 10000002, location_id: int | None = 60003760):
        self.region_id = region_id
        self.location_id = location_id
        self._cache: dict[int, dict] = {}  # type_id -> {sell, buy, cached_at}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(base_url=ESI_BASE_URL, timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _is_cached(self, type_id: int) -> bool:
        entry = self._cache.get(type_id)
        if entry is None:
            return False
        return (time.time() - entry["cached_at"]) < CACHE_TTL

    async def _fetch_prices(self, type_id: int) -> dict:
        """Fetch best buy/sell prices for a single type_id from ESI."""
        client = await self._get_client()

        params = {
            "datasource": "tranquility",
            "type_id": type_id,
            "order_type": "all",
        }

        response = await client.get(
            f"/v1/markets/{self.region_id}/orders/",
            params=params,
        )
        response.raise_for_status()
        orders = response.json()

        # Filter by location if specified
        if self.location_id:
            orders = [o for o in orders if o["location_id"] == self.location_id]

        sell_orders = [o for o in orders if not o["is_buy_order"]]
        buy_orders = [o for o in orders if o["is_buy_order"]]

        best_sell = min((o["price"] for o in sell_orders), default=None)
        best_buy = max((o["price"] for o in buy_orders), default=None)

        return {
            "sell": best_sell,
            "buy": best_buy,
            "cached_at": time.time(),
        }

    async def get_price(self, type_id: int) -> dict:
        """Get cached or fresh best buy/sell prices for a type_id."""
        if self._is_cached(type_id):
            entry = self._cache[type_id]
            return {"sell": entry["sell"], "buy": entry["buy"]}

        try:
            result = self._cache[type_id] = await self._fetch_prices(type_id)
            return {"sell": result["sell"], "buy": result["buy"]}
        except Exception:
            logger.warning("Failed to fetch market price for type %d", type_id)
            return {"sell": None, "buy": None}

    async def get_prices(self, type_ids: list[int]) -> dict[int, dict]:
        """Get prices for multiple type_ids concurrently, using cache."""
        # Split into cached and uncached
        results: dict[int, dict] = {}
        to_fetch: list[int] = []

        for tid in type_ids:
            if self._is_cached(tid):
                entry = self._cache[tid]
                results[tid] = {"sell": entry["sell"], "buy": entry["buy"]}
            else:
                to_fetch.append(tid)

        if to_fetch:
            # Fetch uncached prices concurrently (batch of 20 to avoid overwhelming ESI)
            for i in range(0, len(to_fetch), 20):
                batch = to_fetch[i:i + 20]
                fetched = await asyncio.gather(
                    *(self.get_price(tid) for tid in batch),
                    return_exceptions=True,
                )
                for tid, result in zip(batch, fetched):
                    if isinstance(result, Exception):
                        logger.warning("Price fetch failed for type %d: %s", tid, result)
                        results[tid] = {"sell": None, "buy": None}
                    else:
                        results[tid] = result

        return results

    @property
    def cache_stats(self) -> dict:
        """Return cache statistics."""
        now = time.time()
        valid = sum(1 for e in self._cache.values() if (now - e["cached_at"]) < CACHE_TTL)
        return {
            "total_entries": len(self._cache),
            "valid_entries": valid,
            "ttl_seconds": CACHE_TTL,
        }
