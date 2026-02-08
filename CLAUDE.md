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

## Code Conventions

- Python 3.11+, type hints throughout
- Ruff linter: rules E, F, I, W (E501 ignored); line length 100
- Dataclasses for config and data structures
- Protocol interfaces for `Detector` and `ImageFilter`
- Per-module `logging.getLogger(__name__)` loggers
- Source package lives under `src/screamon/`; build system is hatchling
