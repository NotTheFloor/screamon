"""SDE data loader for blueprint manufacturing materials."""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class SDEData:
    """Loads and indexes SDE data for blueprint material lookups.

    Indexes blueprints.jsonl by blueprintTypeID and builds a minimal
    type name lookup from types.jsonl (only names referenced by blueprints).
    """

    def __init__(self, sde_path: Path | str) -> None:
        self.sde_path = Path(sde_path)
        self._blueprints: dict[int, dict] = {}
        self._type_names: dict[int, str] = {}
        self._loaded = False

    def load(self) -> None:
        """Load and index SDE data files."""
        bp_path = self.sde_path / "blueprints.jsonl"
        types_path = self.sde_path / "types.jsonl"

        if not bp_path.exists():
            logger.warning("SDE blueprints.jsonl not found at %s", bp_path)
            return
        if not types_path.exists():
            logger.warning("SDE types.jsonl not found at %s", types_path)
            return

        # Load blueprints, index by blueprintTypeID
        bp_count = 0
        with open(bp_path) as f:
            for line in f:
                bp = json.loads(line)
                bp_id = bp.get("blueprintTypeID", bp.get("_key"))
                if bp_id is not None:
                    self._blueprints[bp_id] = bp
                    bp_count += 1

        # Collect all type IDs we need names for (materials + products + blueprint itself)
        needed_ids: set[int] = set()
        for bp in self._blueprints.values():
            needed_ids.add(bp.get("blueprintTypeID", bp.get("_key", 0)))
            activities = bp.get("activities", {})
            for activity in activities.values():
                if isinstance(activity, dict):
                    for mat in activity.get("materials", []):
                        needed_ids.add(mat["typeID"])
                    for prod in activity.get("products", []):
                        needed_ids.add(prod["typeID"])

        # Stream types.jsonl, only keep needed names
        name_count = 0
        with open(types_path) as f:
            for line in f:
                t = json.loads(line)
                tid = t.get("_key")
                if tid in needed_ids:
                    name = t.get("name", {})
                    if isinstance(name, dict):
                        self._type_names[tid] = name.get("en", f"Type {tid}")
                    elif isinstance(name, str):
                        self._type_names[tid] = name
                    else:
                        self._type_names[tid] = f"Type {tid}"
                    name_count += 1

        self._loaded = True
        logger.info(
            "SDE loaded: %d blueprints, %d type names resolved", bp_count, name_count
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_type_name(self, type_id: int) -> str:
        """Get the English name for a type ID."""
        return self._type_names.get(type_id, f"Unknown ({type_id})")

    def get_blueprint_materials(self, blueprint_type_id: int) -> dict | None:
        """Get manufacturing materials for a blueprint type ID.

        Returns:
            Dict with 'materials', 'products', 'time', and 'skills' keys,
            each with resolved type names. None if blueprint not found.
        """
        bp = self._blueprints.get(blueprint_type_id)
        if bp is None:
            return None

        mfg = bp.get("activities", {}).get("manufacturing")
        if mfg is None:
            return None

        materials = []
        for mat in mfg.get("materials", []):
            materials.append({
                "type_id": mat["typeID"],
                "type_name": self.get_type_name(mat["typeID"]),
                "quantity": mat["quantity"],
            })

        products = []
        for prod in mfg.get("products", []):
            products.append({
                "type_id": prod["typeID"],
                "type_name": self.get_type_name(prod["typeID"]),
                "quantity": prod["quantity"],
            })

        return {
            "time": mfg.get("time", 0),
            "materials": materials,
            "products": products,
        }

    def get_all_blueprint_ids(self) -> list[int]:
        """Get all known blueprint type IDs."""
        return list(self._blueprints.keys())
