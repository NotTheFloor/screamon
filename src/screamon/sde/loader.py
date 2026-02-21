"""SDE data loader for blueprint manufacturing materials."""

import json
import logging
import math
from pathlib import Path

logger = logging.getLogger(__name__)

# Structure type IDs
STRUCTURE_TYPE_IDS = {35825, 35826, 35827}  # Raitaru, Azbel, Sotiyo

# Dogma attribute IDs
ATTR_STRUCTURE_MAT_BONUS = 2600  # structure material efficiency multiplier
ATTR_STRUCTURE_COST_BONUS = 2601  # structure cost reduction multiplier
ATTR_STRUCTURE_TIME_BONUS = 2602  # structure time reduction multiplier
ATTR_RIG_MAT_BONUS = 2594  # rig material efficiency bonus (negative %)
ATTR_RIG_COST_BONUS = 2595  # rig cost efficiency bonus (negative %)

# Decryptor dogma attribute IDs
ATTR_DECRYPTOR_PROB_MULT = 1112  # invention probability multiplier
ATTR_DECRYPTOR_ME_MOD = 1113  # ME modifier
ATTR_DECRYPTOR_TE_MOD = 1114  # TE modifier
ATTR_DECRYPTOR_RUN_MOD = 1124  # run modifier
DECRYPTOR_GROUP_ID = 1304  # decryptor group ID
ENCRYPTION_METHODS_GROUP_ID = 1162  # Encryption Methods skill group

# Engineering rig group ID ranges (categoryID=66)
RIG_GROUP_RANGE = range(1816, 1871)

# Rig group → rig category mapping
# Medium rigs (separate ME/TE groups)
_M_RIG_CATEGORY = {
    1816: "equipment",  # M Equipment ME
    1819: "equipment",  # M Equipment TE
    1820: "ammunition",  # M Ammunition ME
    1821: "ammunition",  # M Ammunition TE
    1822: "drone_fighter",  # M Drone/Fighter ME
    1823: "drone_fighter",  # M Drone/Fighter TE
    1824: "basic_small_ship",  # M Basic Small Ship ME
    1825: "basic_small_ship",  # M Basic Small Ship TE
    1826: "basic_medium_ship",  # M Basic Medium Ship ME
    1827: "basic_medium_ship",  # M Basic Medium Ship TE
    1828: "basic_large_ship",  # M Basic Large Ship ME
    1829: "basic_large_ship",  # M Basic Large Ship TE
    1830: "advanced_small_ship",  # M Advanced Small Ship ME
    1831: "advanced_small_ship",  # M Advanced Small Ship TE
    1832: "advanced_medium_ship",  # M Advanced Medium Ship ME
    1833: "advanced_medium_ship",  # M Advanced Medium Ship TE
    1834: "advanced_large_ship",  # M Advanced Large Ship ME
    1835: "advanced_large_ship",  # M Advanced Large Ship TE
    1836: "advanced_component",  # M Advanced Component ME
    1837: "advanced_component",  # M Advanced Component TE
    1838: "capital_component",  # M Basic Capital Component TE
    1839: "capital_component",  # M Basic Capital Component ME
    1840: "structure",  # M Structure ME
    1841: "structure",  # M Structure TE
}

# Large rigs (combined ME+TE "Efficiency" groups)
_L_RIG_CATEGORY = {
    1850: "equipment",
    1851: "ammunition",
    1852: "drone_fighter",
    1853: "basic_small_ship",
    1854: "basic_medium_ship",
    1855: "basic_large_ship",
    1856: "advanced_small_ship",
    1857: "advanced_medium_ship",
    1858: "advanced_large_ship",
    1859: "capital_ship",
    1860: "advanced_component",
    1861: "capital_component",
    1862: "structure",
}

# XL rigs (combined broad categories)
_XL_RIG_CATEGORY = {
    1867: "equipment",  # XL Equipment and Consumable
    1868: "ship",  # XL Ship (all ships)
    1869: "structure",  # XL Structure and Component
}

# Ship group IDs for classification
SMALL_SHIP_GROUPS = {25, 31, 237, 420}  # frigate, shuttle, rookie, destroyer
MEDIUM_SHIP_GROUPS = {26, 419}  # cruiser, combat battlecruiser
LARGE_SHIP_GROUPS = {27, 513}  # battleship, attack battlecruiser
CAPITAL_SHIP_GROUPS = {30, 485, 547, 659, 4594}  # titan, dread, carrier, supercarrier, FAX


class SDEData:
    """Loads and indexes SDE data for blueprint material lookups.

    Indexes blueprints.jsonl by blueprintTypeID and builds a minimal
    type name lookup from types.jsonl (only names referenced by blueprints).
    """

    def __init__(self, sde_path: Path | str) -> None:
        self.sde_path = Path(sde_path)
        self._blueprints: dict[int, dict] = {}
        self._type_names: dict[int, str] = {}
        self._solar_systems: dict[str, int] = {}  # lowercase name -> system_id
        self._solar_system_names: dict[int, str] = {}  # system_id -> name
        self._solar_system_security: dict[int, float] = {}  # system_id -> securityStatus
        self._structures: dict[int, dict] = {}  # type_id -> {name, mat_bonus, ...}
        self._engineering_rigs: dict[int, dict] = {}  # type_id -> {name, mat_bonus, ...}
        self._group_categories: dict[int, int] = {}  # groupID -> categoryID
        self._type_metadata: dict[int, dict] = {}  # type_id -> {groupID, metaGroupID}
        self._blueprint_products: dict[int, int] = {}  # blueprint_type_id -> product type_id
        self._invention_data: dict[int, dict] = {}  # T1 bp_type_id -> invention activity
        self._decryptors: dict[int, dict] = {}  # type_id -> {name, prob_mult, ...}
        self._t2_bp_materials: dict[int, dict] = {}  # T2 bp_type_id -> {materials, bp_type_id}
        self._t2_to_t1_bp: dict[int, int] = {}  # T2 bp_type_id -> T1 bp_type_id
        self._encryption_skill_ids: set[int] = set()  # typeIDs of Encryption Methods skills
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

        # Load blueprints, index by blueprintTypeID, extract product type_ids
        bp_count = 0
        invention_product_bp_ids: set[int] = set()  # T2 product type_ids from invention
        with open(bp_path) as f:
            for line in f:
                bp = json.loads(line)
                bp_id = bp.get("blueprintTypeID", bp.get("_key"))
                if bp_id is not None:
                    self._blueprints[bp_id] = bp
                    bp_count += 1
                    # Extract product type_id for rig category lookups
                    # Check manufacturing first, then reaction
                    activities = bp.get("activities", {})
                    activity = activities.get("manufacturing") or activities.get("reaction")
                    if activity:
                        products = activity.get("products", [])
                        if products:
                            self._blueprint_products[bp_id] = products[0]["typeID"]
                    # Extract invention data
                    invention = activities.get("invention")
                    if invention:
                        self._invention_data[bp_id] = invention
                        for prod in invention.get("products", []):
                            invention_product_bp_ids.add(prod["typeID"])

        # Resolve T2 blueprint manufacturing materials for invention EIV calc
        # invention products are T2 blueprint type_ids — look up their manufacturing mats
        for t2_bp_id in invention_product_bp_ids:
            t2_bp = self._blueprints.get(t2_bp_id)
            if t2_bp:
                t2_mfg = t2_bp.get("activities", {}).get("manufacturing")
                if t2_mfg and t2_mfg.get("materials"):
                    self._t2_bp_materials[t2_bp_id] = {
                        "materials": t2_mfg["materials"],
                        "bp_type_id": t2_bp_id,
                    }

        # Build T2 -> T1 blueprint reverse mapping from invention data
        for t1_bp_id, invention in self._invention_data.items():
            for prod in invention.get("products", []):
                self._t2_to_t1_bp[prod["typeID"]] = t1_bp_id

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
                    for skill in activity.get("skills", []):
                        needed_ids.add(skill["typeID"])

        # Add T2 manufacturing material type_ids for name resolution
        for entry in self._t2_bp_materials.values():
            for mat in entry["materials"]:
                needed_ids.add(mat["typeID"])

        # Load groups.jsonl for categoryID mapping
        groups_path = self.sde_path / "groups.jsonl"
        group_count = 0
        rig_group_ids: set[int] = set()
        if groups_path.exists():
            with open(groups_path) as f:
                for line in f:
                    g = json.loads(line)
                    gid = g.get("_key")
                    cat_id = g.get("categoryID")
                    if gid is not None and cat_id is not None:
                        self._group_categories[gid] = cat_id
                        group_count += 1
                        if gid in RIG_GROUP_RANGE:
                            rig_group_ids.add(gid)
            logger.info("SDE loaded: %d groups", group_count)

        # Load typeDogma.jsonl for structure, rig, and decryptor bonuses
        dogma_path = self.sde_path / "typeDogma.jsonl"
        structure_dogma: dict[int, dict] = {}
        rig_dogma: dict[int, dict] = {}
        decryptor_dogma: dict[int, dict] = {}
        if dogma_path.exists():
            with open(dogma_path) as f:
                for line in f:
                    td = json.loads(line)
                    tid = td.get("_key")
                    attrs = {a["attributeID"]: a["value"] for a in td.get("dogmaAttributes", [])}
                    # Structure bonuses
                    if tid in STRUCTURE_TYPE_IDS:
                        structure_dogma[tid] = {
                            "mat_bonus": attrs.get(ATTR_STRUCTURE_MAT_BONUS, 1.0),
                            "cost_bonus": attrs.get(ATTR_STRUCTURE_COST_BONUS, 1.0),
                            "time_bonus": attrs.get(ATTR_STRUCTURE_TIME_BONUS, 1.0),
                        }
                    # Rig bonuses — check for attr 2594 presence
                    if ATTR_RIG_MAT_BONUS in attrs:
                        rig_dogma[tid] = {
                            "mat_bonus": attrs.get(ATTR_RIG_MAT_BONUS, 0.0),
                            "cost_bonus": attrs.get(ATTR_RIG_COST_BONUS, 0.0),
                        }
                    # Decryptor bonuses — check for probability multiplier attr
                    if ATTR_DECRYPTOR_PROB_MULT in attrs:
                        decryptor_dogma[tid] = {
                            "prob_mult": attrs.get(ATTR_DECRYPTOR_PROB_MULT, 1.0),
                            "me_mod": int(attrs.get(ATTR_DECRYPTOR_ME_MOD, 0)),
                            "te_mod": int(attrs.get(ATTR_DECRYPTOR_TE_MOD, 0)),
                            "run_mod": int(attrs.get(ATTR_DECRYPTOR_RUN_MOD, 0)),
                        }

        # Stream types.jsonl — load names, structures, rigs, and product metadata
        # We need product type_ids for metadata
        product_type_ids = set(self._blueprint_products.values())
        # Collect rig type_ids as we go
        name_count = 0
        structure_count = 0
        rig_count = 0
        with open(types_path) as f:
            for line in f:
                t = json.loads(line)
                tid = t.get("_key")
                group_id = t.get("groupID")
                published = t.get("published", False)

                # Type names for blueprint materials
                if tid in needed_ids:
                    name = t.get("name", {})
                    if isinstance(name, dict):
                        self._type_names[tid] = name.get("en", f"Type {tid}")
                    elif isinstance(name, str):
                        self._type_names[tid] = name
                    else:
                        self._type_names[tid] = f"Type {tid}"
                    name_count += 1
                    # Track Encryption Methods skills for invention role classification
                    if group_id == ENCRYPTION_METHODS_GROUP_ID:
                        self._encryption_skill_ids.add(tid)

                # Structure types
                if tid in STRUCTURE_TYPE_IDS and published:
                    name = t.get("name", {})
                    en_name = name.get("en", "") if isinstance(name, dict) else str(name)
                    dogma = structure_dogma.get(tid, {})
                    rig_size = self._rig_size_for_structure(tid)
                    self._structures[tid] = {
                        "name": en_name,
                        "mat_bonus": dogma.get("mat_bonus", 1.0),
                        "cost_bonus": dogma.get("cost_bonus", 1.0),
                        "time_bonus": dogma.get("time_bonus", 1.0),
                        "rig_size": rig_size,
                    }
                    # Also ensure structure names are in type_names
                    if tid not in self._type_names:
                        self._type_names[tid] = en_name
                    structure_count += 1

                # Engineering rig types
                if group_id in rig_group_ids and published and tid in rig_dogma:
                    name = t.get("name", {})
                    en_name = name.get("en", "") if isinstance(name, dict) else str(name)
                    dogma = rig_dogma[tid]
                    rig_cat = self._classify_rig_group(group_id)
                    rig_sz = self._rig_size_from_group(group_id)
                    self._engineering_rigs[tid] = {
                        "name": en_name,
                        "mat_bonus": dogma["mat_bonus"],
                        "cost_bonus": dogma["cost_bonus"],
                        "rig_category": rig_cat,
                        "rig_size": rig_sz,
                    }
                    # Also add to type_names
                    if tid not in self._type_names:
                        self._type_names[tid] = en_name
                    rig_count += 1

                # Product type metadata for rig category classification
                if tid in product_type_ids:
                    self._type_metadata[tid] = {
                        "groupID": group_id,
                        "metaGroupID": t.get("metaGroupID"),
                    }

                # Decryptor types
                if group_id == DECRYPTOR_GROUP_ID and published and tid in decryptor_dogma:
                    name = t.get("name", {})
                    en_name = name.get("en", "") if isinstance(name, dict) else str(name)
                    dogma = decryptor_dogma[tid]
                    self._decryptors[tid] = {
                        "name": en_name,
                        "prob_mult": dogma["prob_mult"],
                        "me_mod": dogma["me_mod"],
                        "te_mod": dogma["te_mod"],
                        "run_mod": dogma["run_mod"],
                    }
                    needed_ids.add(tid)

        # Load solar system name -> ID mappings + security status
        systems_path = self.sde_path / "mapSolarSystems.jsonl"
        system_count = 0
        if systems_path.exists():
            with open(systems_path) as f:
                for line in f:
                    s = json.loads(line)
                    sid = s.get("_key")
                    name = s.get("name", {})
                    en_name = name.get("en", "") if isinstance(name, dict) else str(name)
                    if sid and en_name:
                        self._solar_systems[en_name.lower()] = sid
                        self._solar_system_names[sid] = en_name
                        sec = s.get("securityStatus", 0.0)
                        self._solar_system_security[sid] = sec
                        system_count += 1

        self._loaded = True
        logger.info(
            "SDE loaded: %d blueprints, %d type names, %d solar systems, "
            "%d structures, %d engineering rigs, %d invention blueprints, %d decryptors",
            bp_count,
            name_count,
            system_count,
            structure_count,
            rig_count,
            len(self._invention_data),
            len(self._decryptors),
        )

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    def get_type_name(self, type_id: int) -> str:
        """Get the English name for a type ID."""
        return self._type_names.get(type_id, f"Unknown ({type_id})")

    def get_blueprint_materials(self, blueprint_type_id: int) -> dict | None:
        """Get manufacturing or reaction materials for a blueprint type ID.

        Returns:
            Dict with 'materials', 'products', 'time', and 'activity_type' keys,
            each with resolved type names. None if blueprint not found.
        """
        bp = self._blueprints.get(blueprint_type_id)
        if bp is None:
            return None

        activities = bp.get("activities", {})
        mfg = activities.get("manufacturing")
        activity_type = "manufacturing"
        if mfg is None:
            mfg = activities.get("reaction")
            activity_type = "reaction"
        if mfg is None:
            return None

        materials = []
        for mat in mfg.get("materials", []):
            materials.append(
                {
                    "type_id": mat["typeID"],
                    "type_name": self.get_type_name(mat["typeID"]),
                    "quantity": mat["quantity"],
                }
            )

        products = []
        for prod in mfg.get("products", []):
            products.append(
                {
                    "type_id": prod["typeID"],
                    "type_name": self.get_type_name(prod["typeID"]),
                    "quantity": prod["quantity"],
                }
            )

        return {
            "time": mfg.get("time", 0),
            "materials": materials,
            "products": products,
            "activity_type": activity_type,
        }

    def get_system_id(self, name: str) -> int | None:
        """Get solar system ID by name (case-insensitive)."""
        return self._solar_systems.get(name.lower())

    def get_system_name(self, system_id: int) -> str | None:
        """Get solar system name by ID."""
        return self._solar_system_names.get(system_id)

    def get_all_blueprint_ids(self) -> list[int]:
        """Get all known blueprint type IDs."""
        return list(self._blueprints.keys())

    # --- Facility-related methods ---

    def get_system_security(self, system_id: int) -> float | None:
        """Get security status for a solar system."""
        return self._solar_system_security.get(system_id)

    @staticmethod
    def get_security_multiplier(security: float) -> float:
        """Get rig bonus multiplier based on system security status.

        highsec (>=0.5) = 1.0x, lowsec (0.1-0.4) = 1.9x, nullsec (<0.1) = 2.1x
        """
        if security >= 0.45:  # rounds to 0.5+
            return 1.0
        elif security >= 0.05:  # rounds to 0.1+
            return 1.9
        else:
            return 2.1

    def get_structures(self) -> dict[int, dict]:
        """Get all known engineering structures with bonuses."""
        return dict(self._structures)

    def get_engineering_rigs(self) -> dict[int, dict]:
        """Get all known engineering rigs with bonuses and categories."""
        return dict(self._engineering_rigs)

    def get_blueprint_rig_category(self, blueprint_type_id: int) -> str | None:
        """Determine which rig category applies to a blueprint's product."""
        product_tid = self._blueprint_products.get(blueprint_type_id)
        if product_tid is None:
            return None

        meta = self._type_metadata.get(product_tid)
        if meta is None:
            return None

        group_id = meta.get("groupID")
        meta_group_id = meta.get("metaGroupID")
        if group_id is None:
            return None

        cat_id = self._group_categories.get(group_id)
        return self._classify_product(cat_id, group_id, meta_group_id)

    # --- Invention methods ---

    def has_invention(self, blueprint_type_id: int) -> bool:
        """Check if a blueprint has invention activity."""
        return blueprint_type_id in self._invention_data

    def get_blueprint_invention(self, blueprint_type_id: int) -> dict | None:
        """Get invention data for a blueprint type ID.

        Returns:
            Dict with 'materials', 'products', 'skills', 'time' keys,
            each with resolved type names. None if no invention data.
        """
        inv = self._invention_data.get(blueprint_type_id)
        if inv is None:
            return None

        materials = []
        for mat in inv.get("materials", []):
            materials.append(
                {
                    "type_id": mat["typeID"],
                    "type_name": self.get_type_name(mat["typeID"]),
                    "quantity": mat["quantity"],
                }
            )

        products = []
        for prod in inv.get("products", []):
            products.append(
                {
                    "type_id": prod["typeID"],
                    "type_name": self.get_type_name(prod["typeID"]),
                    "probability": prod.get("probability", 1.0),
                    "quantity": prod.get("quantity", 1),
                }
            )

        skills = []
        for skill in inv.get("skills", []):
            skill_tid = skill["typeID"]
            role = "encryption" if skill_tid in self._encryption_skill_ids else "science"
            skills.append(
                {
                    "type_id": skill_tid,
                    "type_name": self.get_type_name(skill_tid),
                    "level": skill.get("level", 1),
                    "role": role,
                }
            )

        return {
            "time": inv.get("time", 0),
            "materials": materials,
            "products": products,
            "skills": skills,
        }

    def get_decryptors(self) -> dict[int, dict]:
        """Get all published decryptors with their modifiers."""
        return dict(self._decryptors)

    def get_t2_blueprint_materials(self, t2_blueprint_type_id: int) -> list[dict] | None:
        """Get manufacturing materials for a T2 blueprint (for invention EIV calc).

        Args:
            t2_blueprint_type_id: The type ID of the T2 blueprint (invention product)

        Returns:
            List of material dicts with type_id, type_name, quantity. None if not found.
        """
        entry = self._t2_bp_materials.get(t2_blueprint_type_id)
        if entry is None:
            return None

        materials = []
        for mat in entry["materials"]:
            materials.append(
                {
                    "type_id": mat["typeID"],
                    "type_name": self.get_type_name(mat["typeID"]),
                    "quantity": mat["quantity"],
                }
            )
        return materials

    # --- T2 blueprint methods ---

    def get_t1_blueprint_for_t2(self, t2_bp_id: int) -> int | None:
        """Get the T1 blueprint type ID that invents into this T2 blueprint."""
        return self._t2_to_t1_bp.get(t2_bp_id)

    def is_t2_blueprint(self, bp_id: int) -> bool:
        """Check if a blueprint produces a T2 item (metaGroupID == 2)."""
        product_tid = self._blueprint_products.get(bp_id)
        if product_tid is None:
            return False
        meta = self._type_metadata.get(product_tid)
        if meta is None:
            return False
        return meta.get("metaGroupID") == 2

    # --- Private classification methods ---

    @staticmethod
    def _rig_size_for_structure(type_id: int) -> str:
        """Get the rig size a structure accepts."""
        if type_id == 35825:  # Raitaru
            return "m"
        elif type_id == 35826:  # Azbel
            return "l"
        elif type_id == 35827:  # Sotiyo
            return "xl"
        return "m"

    @staticmethod
    def _classify_rig_group(group_id: int) -> str:
        """Map a rig SDE group to its product category string."""
        if group_id in _M_RIG_CATEGORY:
            return _M_RIG_CATEGORY[group_id]
        if group_id in _L_RIG_CATEGORY:
            return _L_RIG_CATEGORY[group_id]
        if group_id in _XL_RIG_CATEGORY:
            return _XL_RIG_CATEGORY[group_id]
        return "unknown"

    @staticmethod
    def _rig_size_from_group(group_id: int) -> str:
        """Determine rig size (m/l/xl) from its group ID range."""
        if 1816 <= group_id <= 1849:
            return "m"
        elif 1850 <= group_id <= 1866:
            return "l"
        elif 1867 <= group_id <= 1870:
            return "xl"
        return "m"

    @staticmethod
    def _classify_product(
        category_id: int | None, group_id: int, meta_group_id: int | None
    ) -> str | None:
        """Classify a blueprint product into a rig category.

        Returns the rig category string that matches this product, or None.
        """
        if category_id == 7:
            return "equipment"
        if category_id == 8:
            return "ammunition"
        if category_id in (18, 87):
            return "drone_fighter"
        if category_id == 65:
            return "structure"

        # Ship classification based on groupID and metaGroupID
        if category_id == 6:
            mg = meta_group_id or 1
            if group_id in SMALL_SHIP_GROUPS:
                return "advanced_small_ship" if mg in (2, 14) else "basic_small_ship"
            if group_id in MEDIUM_SHIP_GROUPS:
                return "advanced_medium_ship" if mg in (2, 14) else "basic_medium_ship"

        # Large ships (categoryID may vary)
        if group_id in LARGE_SHIP_GROUPS:
            mg = meta_group_id or 1
            return "advanced_large_ship" if mg in (2, 14) else "basic_large_ship"

        if group_id in CAPITAL_SHIP_GROUPS:
            return "capital_ship"

        return None

    @staticmethod
    def compute_adjusted_quantity(
        base_qty: int, me_level: int, structure_mat_bonus: float, rig_mat_bonus: float
    ) -> int:
        """Compute ME-adjusted material quantity.

        Formula: ceil(base_qty * (1 - ME/100) * structure_mat_bonus * rig_mat_bonus)
        rig_mat_bonus is already the multiplier (e.g. 0.958 for -4.2% at lowsec).
        """
        adjusted = base_qty * (1 - me_level / 100) * structure_mat_bonus * rig_mat_bonus
        return max(1, math.ceil(adjusted))
