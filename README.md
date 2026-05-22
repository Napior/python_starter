# events-analytics

## Setup after cloning

1. `python3.12 -m venv .venv && source .venv/bin/activate`
2. `make install` (or `make lock` if `requirements.txt` does not exist yet)
3. `make install-hooks`
4. `cp .env.example .env` and fill in the required values
5. `cd ui && npm install`

## Running

- API + scheduler: `python -m src.main`
- UI (dev server): `cd ui && npm run dev`
- UI (production build): `cd ui && npm run build`
- Tests + lint + types: `make check`
- Format before committing: `make format`
