# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**automa-aoNutriDeby** is an automated pipeline that:
1. Extracts patient data from the Datebox CRM via browser automation (Playwright)
2. Stores structured records in PostgreSQL
3. Segments text into chunks for FAISS-based vector search (planned)
4. Generates personalized nutritional campaigns via the DeepSeek LLM (planned)

The project is in early development — many worker functions are stubs with `TODO` comments indicating where real selectors/logic must be added.

## Commands

### Local Development

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
playwright install chromium
```

### Running Workers

```bash
# Smoke-test Chromium environment
python -m nutrideby.workers.crm_extract --dry-run

# Validate PostgreSQL connectivity
python -m nutrideby.workers.crm_extract --check-db
```

### Docker (primary dev environment)

```bash
# Start PostgreSQL and Redis
docker compose up -d postgres redis

# Build worker image
docker compose --profile tools build worker

# Run worker with dry-run inside container
docker compose --profile tools run --rm worker python -m nutrideby.workers.crm_extract --dry-run

# Reset database
docker compose down -v
```

### Linting

```bash
ruff check src/
```

Ruff is configured in `pyproject.toml`: line-length 100, target Python 3.10.

## Architecture

### Package Layout

```
src/
  nutrideby/            # Main installable package
    config.py           # Pydantic-settings singleton (env-driven)
    db.py               # psycopg3 helpers (check_connection)
    workers/
      crm_extract.py    # Playwright worker — primary entry point
  scraper/              # Selenium-based extraction (alternative/legacy approach)
    extract_patients.py # Paginated patient list + profile extraction
    anti_detection.py   # Human-like delays and mouse simulation
infra/
  sql/
    001_initial.sql     # PostgreSQL schema (auto-applied by Docker on first run)
```

### Data Flow

```
Datebox CRM (browser)
  → nutrideby.workers.crm_extract  (Playwright, sync API)
  → nutrideby.db                   (psycopg3 → PostgreSQL)
  → chunks table                   (for future FAISS indexing)
  → campaign_drafts table          (LLM output, requires human review)
```

### Database Schema (`infra/sql/001_initial.sql`)

| Table | Purpose |
|---|---|
| `patients` | CRM-synced records; `external_id` + `source_system` are the unique key |
| `documents` | Raw clinical/admin text per patient; deduplicated by `content_sha256` |
| `chunks` | Text segments ready for embeddings; `faiss_id` populated post-indexing |
| `extraction_runs` | Audit log per worker run; `cursor_state` (JSONB) enables resumption |
| `campaign_drafts` | LLM-generated campaign text; `channel` + `model` tracked; human review required |

### Configuration (`nutrideby/config.py`)

`Settings` is a Pydantic-settings class loaded from `.env`. Copy `.env.example` to `.env` and fill in real values. Key variables:

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | psycopg3 connection string |
| `REDIS_URL` | For future Celery/RQ queue |
| `CRM_BASE_URL` | Datebox instance URL |
| `CRM_USERNAME` / `CRM_PASSWORD` | CRM login credentials |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_API_BASE` | LLM integration |
| `PLAYWRIGHT_HEADLESS` | `true` in production/Docker |
| `PLAYWRIGHT_STORAGE_STATE` | Optional path to saved browser auth session |

### Two Browser Automation Approaches

- **`nutrideby/workers/crm_extract.py`** (Playwright): The active approach. All new CRM extraction work should go here. Uses `sync_playwright`. `_jitter_ms()` adds 200–800 ms random delays.
- **`src/scraper/`** (Selenium): Legacy/alternative approach. `anti_detection.py` provides similar human-like delay utilities.

## LGPD Compliance

- Real patient CSVs (`data/pacientes.csv`) are `.gitignore`d — never commit them.
- Use `data/pacientes_export_template.csv` (anonymized) as structure reference.
- `patients` and `documents` tables include PII-minimization comments in the schema — respect them when adding columns.
- The `data/` directory is for local development only; production data stays in the database.

## Infrastructure

- Docker Compose mounts `infra/sql/` into the PostgreSQL container's `docker-entrypoint-initdb.d/` directory, so the schema is initialized automatically on first `docker compose up`.
- Redis is provisioned but unused until Celery/RQ workers are implemented.
- Production deployment: `git pull` on server at `/opt/automa-aoNutriDeby`.
