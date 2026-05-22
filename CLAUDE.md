# events-analytics

Alert correlation service. An upstream alert backend collects events from monitoring
systems (Zabbix, SCOM, Splunk, Pingdom, Monit24) off the event bus, normalizes them
to a canonical JSON schema, maps severity to a single scale, and deduplicates them.
events-analytics polls that backend's HTTP API, enriches each batch with CMDB context,
sends it to a LiteLLM proxy for root-cause analysis, persists results to SQLite, and
serves them to a React UI for operators.

---

## Working agreement

- Discuss the approach before writing code. Implement only on explicit request.
- Stay in scope — change only what was asked. No drive-by refactors, cleanups, or
  speculative abstractions.
- Be terse. Don't recap diffs in chat; the diff already shows what changed.

---

## Architecture

```
   Monitoring systems (Zabbix / SCOM / Splunk / Pingdom / Monit24)
                        │  (event bus)
                        ▼
            ┌───────────────────────────┐
            │     alert backend         │   normalize + severity mapping + dedup
            └───────────────┬───────────┘
                            │  HTTP  (canonical, deduplicated alerts)
                            ▼
   ┌────────────────────────────────────────────────────────┐
   │                  events-analytics                      │
   │                                                        │
   │   APScheduler (every 5 min)  ─┐                        │
   │                                ├─→  poller             │
   │   FastAPI POST /analyze       ─┘      │                │
   │                                       ▼                │
   │                              cmdb.get_context()        │
   │                                       │                │
   │                                       ▼                │
   │                              llm_client (httpx → LiteLLM proxy)
   │                                       │                │
   │                                       ▼                │
   │                              db (SQLAlchemy / SQLite)  │
   │                                       │                │
   │                                       ▼                │
   │                              FastAPI GET /analyses     │
   └───────────────────────────────────────┬────────────────┘
                                           │
                                           ▼
                                React UI (operator console)
```

Single Python process: FastAPI (serving the React UI) + APScheduler
`BackgroundScheduler` sharing the same database session factory. Split into two
processes only if scaling demands it.

The upstream alert backend already handles normalization, severity mapping, and
deduplication. events-analytics does not reimplement any of that — the poller
fetches alerts and hands them, untransformed, to the prompt builder. Each alert
already carries a `repeat_count` from upstream.

---

## Components

| Path                     | Role |
|--------------------------|------|
| `src/poller.py`          | `httpx` GET to backend `/api/alerts?since=&until=`; returns alert dicts. |
| `src/cmdb.py`            | Load CMDB JSON at startup → `dict[hostname → metadata]`; `get_context(hosts) -> str` for prompt injection. |
| `src/llm_client.py`      | `httpx` POST to the LiteLLM proxy; prompt assembly; JSON parsing with retry. |
| `src/db.py`              | SQLAlchemy 2.0 models + session factory; stores analyses and `last_run_timestamp`. |
| `src/scheduler.py`       | APScheduler `BackgroundScheduler`; wires the periodic `run_analysis_cycle` job. |
| `src/api.py`             | FastAPI app: `GET /analyses`, `GET /analyses/{id}`, `POST /analyze`, `GET /healthz`. |
| `src/settings.py`        | `pydantic-settings`; `validate_settings()` fail-fast on missing required vars. |
| `src/logging_config.py`  | `dictConfig`; structured stdout logs. |
| `src/main.py`            | Entry point — wires logging, settings, DB, scheduler, FastAPI; starts uvicorn. |
| `ui/`                    | React + TypeScript app. Calls the FastAPI service for analyses and the on-demand trigger. |

CMDB stays as an in-process `dict` loaded from JSON. No vector store, no embeddings —
hostname is the only lookup key needed.

---

## Tech stack

| Layer        | Choice                                       |
|--------------|----------------------------------------------|
| HTTP server  | FastAPI + Uvicorn                            |
| Scheduler    | APScheduler `BackgroundScheduler` (sync)     |
| HTTP client  | `httpx` (sync)                               |
| Database     | SQLite via SQLAlchemy 2.0                    |
| Config       | `pydantic-settings` + `python-dotenv`        |
| Tests        | `pytest` + `pytest-httpx`                    |
| Lint/format  | `black` + `isort` + `flake8`                 |
| Types        | `mypy` (strict=False)                        |
| Frontend     | React + TypeScript + Vite                    |

LLM access is `httpx` directly to the LiteLLM proxy (OpenAI-compatible chat
completions endpoint). No vendor SDK.

Python dependency source of truth: `requirements.ini` (loose). Lockfile:
`requirements.txt`, regenerated by `scripts/lock_deps.py` via `make lock`.

---

## Repository layout

```
src/
├── api.py
├── scheduler.py
├── poller.py
├── llm_client.py
├── cmdb.py
├── db.py
├── settings.py
├── logging_config.py
├── main.py
└── tests/
ui/                     # React app — own package.json, build pipeline
├── src/
├── public/
└── package.json
scripts/lock_deps.py
hooks/pre-commit
data/                   # SQLite + CMDB JSON (gitignored)
```

---

## Commands

```bash
source .venv/bin/activate

make lock          # regenerate requirements.txt after editing requirements.ini
make install       # install Python deps from lockfile
make install-hooks # one-time, after clone
make format        # isort + black
make check         # format + lint + types + tests
python -m src.main # API + scheduler in one process

cd ui && npm install
cd ui && npm run dev
cd ui && npm run build
```

---

## Conventions

- **Python 3.12.** Line length 100. `isort profile = black`. `flake8` ignores
  `E203, W503`.
- **Imports:** `from src.poller import fetch_alerts` (run from project root;
  requires `src/__init__.py`).
- **`httpx` synchronous.** APScheduler 3.x is sync; AsyncScheduler is not worth
  the complexity here.
- **SQLAlchemy 2.0 API:** `with Session(engine) as session: ...`.
- **Settings:** required vars (`backend_url`, `litellm_url`, `litellm_api_key`)
  carry `""` defaults so `from src.settings import settings` works without `.env`
  (tests stay green); production values are validated in `validate_settings()`
  called from `main()`.
- **Logging:** `logger = logging.getLogger(__name__)` per module;
  `setup_logging()` is the first call in any entry point.
- **API contract:** the React UI is the only consumer; shape endpoints for it,
  not for generic CRUD.
