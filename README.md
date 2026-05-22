# Alert Analytics Service

## Setup after cloning

1. `python3.12 -m venv .venv && source .venv/bin/activate`
2. `make install` (or `make lock` if `requirements.txt` does not exist yet)
3. `make install-hooks`
4. `cp .env.example .env` and fill in the required values

## Running

- Service: `python -m src.main`
- UI: `streamlit run ui/app.py`
- Tests + lint + types: `make check`
- Format before committing: `make format`
