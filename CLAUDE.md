# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Screamon is an EVE Online screen reader that monitors game UI regions via OCR and provides audio alerts when values change. It captures screen regions (local chat count, overview entities, target asteroids), runs them through configurable image processing pipelines, extracts values with Tesseract OCR, and plays sounds on state changes. A companion web dashboard communicates with the monitor via shared SQLite database.

## Commands

```bash
# Install with uv (project uses uv as package manager)
uv sync
uv sync --extra macos   # macOS-specific dependencies
uv sync --extra dev      # dev tools (pytest, ruff)

# Run the monitor
uv run screamon [--calibrate] [--verbose] [--config config.json] [--database screamon.db]

# Run the web dashboard
uv run screamon-web [--port 8080] [--host 127.0.0.1] [--verbose]

# Lint
uv run ruff check src/

# Format
uv run ruff format src/

# Run tests
uv run pytest
```

## Architecture

### Entry Points
- `screamon` CLI → `src/screamon/cli.py:run_monitor()` → `MonitorRunner`
- `screamon-web` CLI → `src/screamon/cli.py:run_web()` → Litestar/uvicorn server

### Core Loop (MonitorRunner in `monitor/runner.py`)
Each cycle: capture screen region per detector → run image pipeline → OCR → extract value → compare to previous → play alert if changed → store in SQLite.

### Detector System (`detectors/`)
- `base.py` — `BaseDetector` ABC and `DetectorResult` dataclass
- `registry.py` — `DetectorRegistry` manages detector lifecycle
- `local_count.py` — Extracts player count from "Local [X]" text via regex
- `overview.py` — Counts non-empty lines in overview panel
- `targets.py` — Searches for "Asteroid" text variations (disabled by default)

Each detector has coordinates (calibrated via mouse clicks), a named pipeline, and alert logic (increase=danger, decrease=safe).

### Image Processing (`pipeline/`)
Pipelines are named chains of filters applied before OCR:
- **default_ocr**: Upscale → Contrast → Grayscale → Threshold
- **star_background**: StarRemoval → Upscale → Contrast → Grayscale → Threshold
- **high_contrast**: Upscale → high Contrast → Grayscale → AdaptiveThreshold

Filters in `filters.py`: Upscale, Contrast, Grayscale, Threshold, Denoise, StarRemoval, Invert, AdaptiveThreshold.

### Monitor ↔ Web Communication
The monitor and web server are separate processes sharing a SQLite database (`screamon.db`). The monitor writes detector state and events; the web UI reads them and writes runtime config (e.g., recalibration requests) that the monitor polls.

### Key Modules
- `config.py` — Dataclass-based config with migration from v1 `settings.conf` format
- `database.py` — SQLite with tables: `detector_state`, `events`, `players`, `runtime_config`, `esi_tokens`, `esi_characters`, `esi_encryption`
- `capture/screen.py` — Screenshot via PIL.ImageGrab; `capture/mouse.py` — coordinate calibration
- `alerts/sound.py` — Cross-platform audio (afplay/winsound/aplay with fallbacks)
- `web/routes.py` — REST API: `/api/status`, `/api/detectors/`, `/api/events/`, `/api/events/stream` (SSE)
- `mouse/` — Bundled cross-platform mouse library (pip `mouse` doesn't work on macOS)

### ESI Authentication (`esi/`)
EVE SSO OAuth2 PKCE integration for direct API access to character data:
- `models.py` — `ESIConfig`, `ESIToken`, `ESICharacter` dataclasses
- `auth.py` — `ESIAuth` class: OAuth2 PKCE flow (authorization URL, code exchange, token refresh, JWT validation, Fernet encryption for refresh tokens)
- `client.py` — `ESIClient` class: authenticated ESI HTTP client with auto token refresh; convenience methods for location, ship, online, contacts, standings
- `__init__.py` — Package exports: `ESIAuth`, `ESIClient`, `ESIConfig`, `ESIToken`

**Config**: `esi` section in `config.json` with `client_id`, `callback_port`, `callback_path`, `scopes`

**DB Tables**: `esi_tokens` (character tokens with encrypted refresh), `esi_characters` (authenticated characters), `esi_encryption` (single-row Fernet key)

**Web Routes** (`web/esi_routes.py`):
- `GET /esi/login` — Generate auth URL, open browser for EVE SSO
- `GET /esi/callback` — OAuth callback, exchange code, save character
- `GET /esi/status` — ESI config and auth status
- `GET /api/esi/characters/` — List authenticated characters
- `POST /api/esi/characters/{id}/activate` — Set active character
- `DELETE /api/esi/characters/{id}` — Remove character
- `GET /api/esi/data/location` — Active character's current system
- `GET /api/esi/data/ship` — Active character's ship type
- `GET /api/esi/data/online` — Active character's online status
- `GET /api/esi/data/contacts` — Active character's contacts
- `GET /api/esi/data/standings` — Active character's NPC standings

**Setup**: Register app at developers.eveonline.com, set callback to `http://localhost:8080/esi/callback`, add `client_id` to `config.json` under `esi.client_id`.

### Industry Analyzer (`sde/`, `market/`, facility system)

The web dashboard includes a blueprint/industry analyzer with manufacturing cost calculations.

**Facility System** (`database.py` facilities table, `web/esi_routes.py` FacilityController):
Saved configurations of structure + rigs + tax. Structures: Raitaru (35825, M rigs), Azbel (35826, L rigs), Sotiyo (35827, XL rigs).

**SDE Loader** (`sde/loader.py`):
Loads blueprints, types, groups, typeDogma, mapSolarSystems. Extracts structure bonuses (dogma attrs 2600/2601/2602), engineering rig bonuses (attrs 2594/2595), system security, and blueprint product → rig category classification. Handles both `manufacturing` and `reaction` activities.

**Manufacturing Formulas**:
- Material quantity: `max(runs, ceil(base_qty * (1 - ME/100) * structure_mat_bonus * rig_mat_bonus))`
  - `structure_mat_bonus`: dogma attr 2600 (e.g. 0.99 for Raitaru = 1% reduction)
  - `rig_mat_bonus`: `1 + (dogma_attr_2594 / 100) * security_multiplier` (e.g. -2.0% × 1.9 lowsec = 0.962)
  - Security multiplier: highsec(≥0.45)=1.0×, lowsec(0.05-0.44)=1.9×, null(<0.05)=2.1×
  - Reactions always use ME=0
- Job cost: `EIV * (SCI * (1 - structure_cost_bonus) + SCC_surcharge + facility_tax)`
  - EIV = sum of adjusted_price × base_quantity for all materials
  - SCC surcharge = 4% (fixed)
  - Reactions use activity="reaction" for system cost index lookup

**Systems**: Manufacturing uses Serren, reactions use Obalyu (hardcoded in app.js for now).

### EVE Industry Skill Mechanics (Reference for Future Implementation)

Skills do NOT affect material quantities or ISK job cost. They affect **time only** and act as **eligibility gates**.

**Time Reduction Skills** (stack multiplicatively):

| Skill (typeID) | Dogma Attr | Bonus/Level | Applies To |
|---|---|---|---|
| Industry (3380) | 440 `manufacturingTimeBonus` | -4% | All manufacturing |
| Advanced Industry (3388) | 1961 `advancedIndustrySkillIndustryJobTimeBonus` | -3% | All manufacturing + research |
| Reactions (45746) | 2660 `reactionTimeBonus` | -4% | All reactions |
| Adv Small Ship Construction (3395) | 1982 `manufactureTimePerLevel` | -1% | Items requiring this skill |
| Adv Medium Ship Construction (3397) | 1982 | -1% | Items requiring this skill |
| Adv Large Ship Construction (3398) | 1982 | -1% | Items requiring this skill |
| Adv Industrial Ship Construction (3396) | 1982 | -1% | Items requiring this skill |
| Capital Ship Construction (22242) | — | No time bonus | Pure prerequisite gate |
| Science/Engineering skills (16 total, group 270) | 1982 | -1% | Items requiring that skill |

**Full time formula**: `base_time * runs * (1 - 0.02*TE) * (1 - 0.04*industry_lvl) * (1 - 0.03*adv_industry_lvl) * (1 - 0.01*science_skill_lvl) * (1 - implant_bonus) * (1 - structure_time_bonus) * (1 - rig_time_bonus*sec_mult)`

At max skills (Industry V + Advanced Industry V) without other bonuses: `0.80 * 0.85 = 0.68` (32% reduction).

**Implants** (slot 8, one active): BX-801 (1%), BX-802 (2%), BX-804 (4%).

**Eligibility Patterns** (from SDE `blueprints.jsonl` → `activities.manufacturing.skills`):
- T1 items: Industry I-V only (1,669 blueprints need just Industry I)
- T2 items: Industry V + 2 science skills at level 1
- T2 ships: Above + Advanced Ship Construction specialization
- T2 rigs: Above + Jury Rigging (26252)
- Capital items: Capital Ship Construction (22242), requires Industry V + Advanced Industry V
- Reactions: Reactions skill (45746) at levels 1-5

**ESI Access**: Character skills via `GET /characters/{id}/skills/` (scope `esi-skills.read_skills.v1`) returns `skill_id`, `trained_skill_level`, `active_skill_level`.

**Implementation Notes for Job Time Feature**:
1. Fetch character skills via ESI and cache them
2. For each blueprint, read required skills from `blueprints.jsonl` → `activities.*.skills`
3. Look up time bonus dogma attrs (440, 1961, 1982, 2660) for each required skill
4. Apply multiplicatively along with blueprint TE, structure time bonus (dogma 2602), and rig time bonus
5. Structure time bonus attr 2602 is a multiplier (e.g. 0.85 for Raitaru = 15% reduction)
6. 83 unique skills are referenced across all manufacturing/reaction blueprints

## Code Conventions

- Python 3.11+, type hints throughout
- Ruff linter: rules E, F, I, W (E501 ignored); line length 100
- Dataclasses for config and data structures
- Protocol interfaces for `Detector` and `ImageFilter`
- Per-module `logging.getLogger(__name__)` loggers
- Source package lives under `src/screamon/`; build system is hatchling
