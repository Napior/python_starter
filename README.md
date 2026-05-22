# Serwis analityczny alertów

## Setup po sklonowaniu

1. `python3.12 -m venv .venv && source .venv/bin/activate`
2. `make install` (lub `make lock` jeśli `requirements.txt` jeszcze nie istnieje)
3. `make install-hooks`
4. `cp .env.example .env` i uzupełnij wymagane wartości

## Uruchomienie

- Serwis: `python -m src.main`
- UI: `streamlit run ui/app.py`
- Testy + lint + typy: `make check`
- Formatowanie przed commitem: `make format`
