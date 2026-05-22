# Plan Bootstrapowania Repo — Serwis Analityczny Alertów

> **Środowisko:** RHEL Linux, Python 3.12, pakiety przez wewnętrzne Artifactory.

---

## 0. Konfiguracja Środowiska (RHEL / Artifactory) — ZRÓB NAJPIERW

```bash
# weryfikacja wersji Pythona
python3.12 --version
```

> **RHEL i pip:** Na RHEL komenda `pip` jako samodzielna komenda często nie istnieje.
> Przed aktywacją venv używaj zawsze `python3.12 -m pip`.
> Po `source .venv/bin/activate` komenda `pip` działa normalnie (wskazuje na `.venv/bin/pip`).

### Konfiguracja pip pod Artifactory

W korporacyjnym środowisku pip musi wskazywać na wewnętrzny mirror, nie pypi.org:

```bash
# sprawdź czy pip.conf już istnieje
cat ~/.config/pip/pip.conf   # Linux (user-level)
# lub: cat /etc/pip.conf     # system-level

# jeśli nie ma — skonfiguruj (zapytaj admina o dokładny URL)
python3.12 -m pip config set global.index-url https://<artifactory-host>/repository/pypi-proxy/simple
python3.12 -m pip config set global.trusted-host <artifactory-host>
```

Jeśli Artifactory używa korporacyjnego certyfikatu SSL:

```bash
python3.12 -m pip config set global.cert /path/to/corporate-ca-bundle.crt
# lub (tymczasowo, do weryfikacji):
python3.12 -m pip install --trusted-host <artifactory-host> httpx
```

### Weryfikacja dostępu do pakietów

```bash
python3.12 -m pip install --dry-run httpx   # powinno znaleźć pakiet, nic nie instalować
```

Jeśli to nie działa — zatrzymaj się i rozwiąż problem z pip/Artifactory zanim pójdziesz dalej.

---

## 1. Tooling — Uzasadnienie Wyborów

### Menedżer pakietów: `pip + venv` (stdlib Python)

- Zawsze dostępny — część standardowej biblioteki Pythona, nic do instalowania
- `python3.12 -m venv .venv` tworzy izolowane środowisko
- Działa w każdym środowisku korporacyjnym bez zgody IT na dodatkowe narzędzia
- Zależności w `requirements.ini` (źródło prawdy, loose constraints) i `requirements.txt` (lockfile, pinned versions)
- `requirements.ini` parsowany przez stdlib `configparser` — zero dodatkowych zależności

> **Nota:** `uv` jest znacznie szybszy i wygodniejszy, ale wymaga osobnej instalacji
> (binarny plik z internetu). W zamkniętym środowisku trzymaj się `pip + venv`.

### Linter i formatter: `black` + `isort` + `flake8`

- **black** — formatter (nie dyskutuje ze stylem, zero konfiguracji poza line-length)
- **isort** — sortowanie importów; wymaga `profile = "black"` żeby nie kolidowały
- **flake8** — linter (undefined names, unused imports, style); **nie czyta `pyproject.toml`** — konfiguracja w osobnym `.flake8`
- Wszystkie instalowane przez pip z Artifactory

### Type checker: `mypy`

- Dojrzalszy, lepsza dokumentacja, większa baza pluginów
- Konfiguracja w `pyproject.toml`

### Pre-commit: natywny git hook (shellscript)

Bez frameworka `pre-commit` — zamiast tego prosty shellscript w `.git/hooks/pre-commit`.
Skrypt trzymany w repo pod `hooks/pre-commit`, instalowany ręcznie raz na klon.

---

## 2. Inicjalizacja Repo — Komendy Krok po Kroku

### Krok 1: Tworzenie struktury katalogów

```bash
# w katalogu projektu (analityka_praca/)
mkdir -p src src/tests ui ui/tests data scripts hooks
touch src/__init__.py
touch src/normalize.py src/poller.py src/llm_client.py src/cmdb.py src/db.py src/main.py src/settings.py src/logging_config.py
touch ui/__init__.py ui/app.py
touch src/tests/__init__.py ui/tests/__init__.py
touch data/.gitkeep
touch scripts/lock_deps.py
touch hooks/pre-commit
touch .env.example requirements.ini setup.cfg .flake8 pyproject.toml Makefile README.md
chmod +x hooks/pre-commit
```

> **Ważne:** Wszystkie pliki konfiguracyjne (`requirements.ini`, `setup.cfg`, `.flake8`,
> `pyproject.toml`, `scripts/lock_deps.py`, `hooks/pre-commit`, `Makefile`, `README.md`)
> muszą mieć wpisaną zawartość (sekcje 3 i 8) **zanim** uruchomisz `make lock` w Step 3.

### Krok 2: Tworzenie virtualenv

```bash
python3.12 -m venv .venv
python3.12 -m pip install --upgrade pip   # zaktualizuj pip przed aktywacją venv
source .venv/bin/activate                 # od teraz komenda `pip` działa normalnie
```

Po aktywacji prompt zmienia się na `(.venv) $`. Sprawdź: `which python` — powinno wskazywać na `.venv/bin/python`.

### Krok 3: Wpisz pliki konfiguracyjne (sekcje 3 i 8), następnie zainstaluj

Wpisz zawartość: `requirements.ini`, `setup.cfg`, `.flake8`, `pyproject.toml`,
`scripts/lock_deps.py`, `hooks/pre-commit`, `Makefile`, `README.md`.

```bash
# pierwsze uruchomienie — wygeneruj lockfile (instaluje deps i freezuje wersje)
make lock

# lub na innej maszynie gdzie lockfile już istnieje
make install

# zainstaluj git hook (raz)
make install-hooks
```

### Krok 4: Skonfiguruj `.env`

```bash
cp .env.example .env
# otwórz w edytorze i uzupełnij BACKEND_URL, LITELLM_URL, LITELLM_API_KEY
```

Bez prawdziwych wartości `validate_settings()` (sekcja 4) zatrzyma serwis przy starcie.
Testy jednostkowe modułów typu `normalize.py` działają bez `.env` (Settings ma defaulty).

### Zależności — ściągawka

| Pakiet | Rola |
|--------|------|
| `httpx` | HTTP client (polling backendu + LiteLLM proxy) |
| `apscheduler` | in-process scheduler co 5 minut |
| `sqlalchemy` | ORM dla SQLite |
| `streamlit` | UI |
| `pydantic-settings` | walidacja konfiguracji z env vars + .env file |
| `python-dotenv` | ładowanie .env (używany przez pydantic-settings) |
| `pytest` | framework testowy |
| `pytest-httpx` | mockowanie httpx w testach |
| `black` | formatting |
| `isort` | sortowanie importów |
| `flake8` | linting |
| `mypy` | type checking |

---

## 3. Pliki Konfiguracyjne Zależności i Narzędzi

### `requirements.ini` — źródło prawdy (loose constraints)

```ini
[main]
httpx>=0.27
apscheduler>=3.10
sqlalchemy>=2.0
streamlit>=1.35
pydantic-settings>=2.3
python-dotenv>=1.0

[dev]
pytest>=8.2
pytest-httpx>=0.30
pytest-asyncio>=0.23
black>=24.0
isort>=5.13
flake8>=7.0
mypy>=1.10
```

### `scripts/lock_deps.py` — generuje `requirements.txt`

```python
import configparser
import os
import subprocess
import sys
import tempfile

cfg = configparser.ConfigParser(delimiters=(':',), allow_no_value=True)
cfg.optionxform = str  # zachowaj wielkość liter i >= w stringach requirementów
cfg.read('requirements.ini')

reqs = [key for section in cfg.sections() for key in cfg.options(section)]

with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
    f.write('\n'.join(reqs))
    tmp = f.name

try:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', tmp], check=True)
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'freeze'],
        capture_output=True, text=True, check=True,
    )
    with open('requirements.txt', 'w') as out:
        out.write(result.stdout)
    print('requirements.txt zaktualizowany.')
finally:
    os.unlink(tmp)
```

**Dlaczego `delimiters=(':',)`:** Domyślnie `configparser` traktuje `=` jako separator klucz-wartość.
Constraint `httpx>=0.27` zawiera `=`, więc bez tej opcji zostałby rozbity na klucz `httpx>` i wartość `0.27`.
Z `delimiters=(':',)` całe `httpx>=0.27` to jeden klucz — bez wartości.

### `setup.cfg` — konfiguracja narzędzi (isort, mypy, pytest)

```ini
[isort]
profile = black
line_length = 100
known_first_party = src

[mypy]
python_version = 3.12
strict = False
warn_unused_ignores = True
warn_return_any = True
ignore_missing_imports = True
exclude = src/tests/|ui/tests/

[tool:pytest]
testpaths = src/tests ui/tests
asyncio_mode = auto
```

### `.flake8` — konfiguracja flake8 (nie czyta setup.cfg)

```ini
[flake8]
max-line-length = 100
extend-ignore =
    E203,
    W503
exclude =
    .venv,
    __pycache__,
    .git,
    data
```

### `pyproject.toml` — konfiguracja black

Black czyta konfigurację z `pyproject.toml`. Trzymamy `line-length = 100` żeby
spójnie z isort i flake8 — bez tego hook (uruchamiający `black --check` bez flag)
będzie reformatował pliki sformatowane przez `make format`.

```toml
[tool.black]
line-length = 100
target-version = ["py312"]
```

Dzięki temu `make format`, hook pre-commit i ręczne `python -m black ...` używają
tej samej konfiguracji — bez przekazywania flag w Makefile.

---

## 4. Config Management — `src/settings.py`

**Dlaczego `pydantic-settings`:** walidacja przy starcie — aplikacja failuje natychmiast
przy brakujących zmiennych, nie w połowie działania. Type hints — IDE wie typy zmiennych.

```python
# src/settings.py
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Backend API
    backend_url: str = ""
    backend_api_key: str = ""
    backend_timeout_s: int = 30

    # LiteLLM Proxy
    litellm_url: str = ""
    litellm_api_key: str = ""
    litellm_model: str = "gpt-4o"
    litellm_timeout_s: int = 60

    # Scheduler
    poll_interval_min: int = 5
    poll_overlap_s: int = 30

    # SQLite
    db_path: str = "data/alerts.db"

    # CMDB
    cmdb_file: str = "data/cmdb.json"
    cmdb_enabled: bool = True

    # Logging
    log_level: str = "INFO"


# singleton — importuj wszędzie jako: from src.settings import settings
settings = Settings()


def validate_settings() -> None:
    """Failuje wcześnie jeśli wymagane env vars są puste. Wywoływane z main()."""
    required = ("backend_url", "litellm_url", "litellm_api_key")
    missing = [f for f in required if not getattr(settings, f)]
    if missing:
        raise RuntimeError(f"Brakujące wymagane env vars: {missing}. Sprawdź .env")
```

**Dlaczego defaulty zamiast wymaganych pól:** wymagane pola (`backend_url`, `litellm_url`,
`litellm_api_key`) z defaultami `""` pozwalają zaimportować `src.settings` bez `.env`.
Dzięki temu testy modułów pure-functions (`normalize.py`) działają bez konfiguracji,
a walidacja produkcyjnych wartości odbywa się dopiero przy starcie serwisu w `main()`
przez `validate_settings()`.

**Plik `.env.example`** (commitowany do repo):

```env
# Backend
BACKEND_URL=http://backend-host/api
BACKEND_API_KEY=

# LiteLLM Proxy
LITELLM_URL=http://litellm-proxy:4000
LITELLM_API_KEY=sk-...
LITELLM_MODEL=gpt-4o

# Opcjonalne (mają defaults)
POLL_INTERVAL_MIN=5
LOG_LEVEL=INFO
```

Skopiuj do `.env` i wypełnij prawdziwymi wartościami. Plik `.env` NIE idzie do gita.

**Weryfikacja (z aktywnym venv):**
```bash
python -c "from src.settings import settings; print(settings.model_dump())"
```

---

## 5. Logging Setup — `src/logging_config.py`

```python
# src/logging_config.py
import logging
import logging.config
import sys

from src.settings import settings


_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {
            "format": "%(asctime)s %(levelname)-8s %(name)s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "stdout": {
            "class": "logging.StreamHandler",
            "stream": sys.stdout,
            "formatter": "default",
        },
    },
    "root": {
        "level": settings.log_level.upper(),
        "handlers": ["stdout"],
    },
    "loggers": {
        "httpx": {"level": "WARNING"},
        "httpcore": {"level": "WARNING"},
        "apscheduler": {"level": "WARNING"},
        "sqlalchemy.engine": {"level": "WARNING"},
        "streamlit": {"level": "WARNING"},
    },
}


def setup_logging() -> None:
    logging.config.dictConfig(_LOG_CONFIG)
```

**Użycie w każdym module:**
```python
import logging
logger = logging.getLogger(__name__)

logger.info("Fetched %d alerts", len(alerts))
logger.warning("Empty batch, skipping LLM call")
logger.error("Backend unreachable: %s", exc)
```

`setup_logging()` wywołaj jako pierwszą rzecz w `src/main.py` i `ui/app.py`.

---

## 6. Kolejność Implementacji

Zasada: buduj od wnętrza na zewnątrz. Każdy krok ma działające testy zanim przejdziesz dalej.

### Sprint 1: Fundament (dzień 1-2)

**1. `src/normalize.py` + `src/tests/test_normalize.py`**

Najłatwiejszy do testowania (pure functions, zero I/O, zero zależności od settings).
Startujesz od razu z zielonym pytestem — natychmiastowy feedback i bez potrzeby `.env`.

```python
# src/normalize.py — kluczowe funkcje
def normalize_alert(raw: dict) -> dict: ...     # mapowanie severity, fallback pola
def compute_dedup_key(alert: dict) -> str: ...  # hashlib(source+host+alert_code)
def deduplicate(alerts: list[dict]) -> list[dict]: ...  # klucz hash, repeat_count
def filter_for_prompt(alert: dict) -> dict: ...  # usuwa pola niepotrzebne LLM
```

```python
# src/tests/test_normalize.py
def test_severity_mapping_zabbix():
    raw = {"source_system": "zabbix", "severity": "Disaster", ...}
    assert normalize_alert(raw)["severity"] == "critical"

def test_dedup_removes_duplicate_increments_count():
    alerts = [alert1, alert1_copy]  # ten sam dedup_key
    result = deduplicate(alerts)
    assert len(result) == 1
    assert result[0]["repeat_count"] == 2
```

**2. `src/settings.py` + weryfikacja**

Settings ma defaulty (sekcja 4), więc import działa bez `.env`. Weryfikacja:
```bash
python -c "from src.settings import settings; print(settings.model_dump())"
```

**3. `src/logging_config.py`**

Prosty plik. Zaimportuj w smoke teście, sprawdź że `setup_logging()` + `logger.info(...)` wypisuje na stdout w oczekiwanym formacie.

**4. `src/db.py` + `src/tests/test_db.py`**

SQLite nie wymaga mocków — testuj na `:memory:`.

```python
# src/db.py
def get_engine(db_path: str = ":memory:"): ...  # parametr umożliwia test in-memory
def save_analysis(session, analysis: dict) -> int: ...
def get_last_run_timestamp(session) -> datetime | None: ...
def set_last_run_timestamp(session, ts: datetime) -> None: ...
```

```python
# src/tests/test_db.py
def test_last_run_timestamp_roundtrip():
    engine = get_engine(":memory:")
    # create tables, session, set timestamp, pobierz i porównaj
```

### Sprint 2: HTTP I/O (dzień 3-4)

**5. `src/poller.py` + `src/tests/test_poller.py`**

Pierwsze użycie `pytest-httpx`. Nigdy nie odpytuj prawdziwego backendu w testach.

```python
# src/tests/test_poller.py
from pytest_httpx import HTTPXMock

def test_fetch_alerts_success(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url="http://fake-backend/api/alerts",
        json={"alerts": [{"source_system": "zabbix", ...}]}
    )
    alerts = fetch_alerts(base_url="http://fake-backend", since=..., until=...)
    assert len(alerts) == 1

def test_fetch_alerts_backend_down(httpx_mock: HTTPXMock):
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))
    with pytest.raises(BackendUnavailableError):
        fetch_alerts(...)
```

**6. `src/cmdb.py` + `src/tests/test_cmdb.py`**

```python
def test_get_context_known_hosts(tmp_path):
    cmdb_file = tmp_path / "cmdb.json"
    cmdb_file.write_text('{"web-01": {"services": ["nginx"], "depends_on": ["db-01"]}}')
    load_cmdb(str(cmdb_file))
    ctx = get_context(["web-01", "unknown-host"])
    assert "web-01" in ctx
    assert "unknown-host" not in ctx
```

**7. `src/llm_client.py` + `src/tests/test_llm_client.py`**

Najtrudniejszy — testuj scenariusze błędów (invalid JSON, retry).

```python
def test_call_llm_invalid_json_retries(httpx_mock: HTTPXMock):
    # pierwsza odpowiedź: invalid JSON; druga: poprawna
    httpx_mock.add_response(json={"choices": [{"message": {"content": "not json"}}]})
    httpx_mock.add_response(json={"choices": [{"message": {"content": '{"summary": "ok"}'}}]})
    result = call_llm(alerts=[], cmdb_context="", max_retries=2)
    assert result["summary"] == "ok"
```

### Sprint 3: Orchestracja (dzień 5)

**8. `src/main.py`**

Skleja wszystko. Na tym etapie wszystkie moduły mają testy.

```python
# src/main.py
import logging
from apscheduler.schedulers.blocking import BlockingScheduler
from src.logging_config import setup_logging
from src.settings import settings, validate_settings
# ... pozostałe importy

setup_logging()
validate_settings()  # fail-fast jeśli wymagane env vars puste
logger = logging.getLogger(__name__)

def run_analysis_cycle() -> None:
    # fetch → normalize → dedup → cmdb context → llm → save
    ...

def main() -> None:
    load_cmdb(settings.cmdb_file)
    scheduler = BlockingScheduler()
    scheduler.add_job(run_analysis_cycle, "interval", minutes=settings.poll_interval_min)
    logger.info("Scheduler started, poll interval=%d min", settings.poll_interval_min)
    scheduler.start()

if __name__ == "__main__":
    main()
```

Test manualny: `python -m src.main` — scheduler startuje bez błędów.

### Sprint 4: UI (dzień 6-7)

**9. `ui/app.py`**

Streamlit czyta z SQLite — czyste oddzielenie UI od logiki.

```bash
streamlit run ui/app.py
# domyślny port: 8501 — upewnij się, że port jest otwarty w firewallu korporacyjnym
```

---

## 7. `.gitignore`

```gitignore
# Python
__pycache__/
*.py[cod]
.pytest_cache/
.mypy_cache/
dist/
build/

# Virtual env — NIE commituj
.venv/

# Env — NIGDY nie commituj
.env
*.env.local

# Data
data/*.db
data/cmdb.json

# requirements.txt to lockfile — commituj go do repo

# OS
.DS_Store
```

**Lockfile:** `requirements.txt` jest generowany przez `make lock` i commitowany do repo.
Pozwala odtworzyć dokładnie te same wersje na każdej maszynie.

---

## 8. Git Hook i Makefile

### Struktura

```
analityka_praca/
├── hooks/
│   └── pre-commit    # skrypt trzymany w repo, instalowany ręcznie
├── Makefile
└── ...
```

### `hooks/pre-commit` — skrypt git hooka

```bash
#!/usr/bin/env bash
set -e

PYTHON=".venv/bin/python"

if [ ! -f "$PYTHON" ]; then
    echo "ERROR: venv not found. Run: python3.12 -m venv .venv && pip install -e '.[dev]'"
    exit 1
fi

echo ">>> isort --check-only"
$PYTHON -m isort --check-only src/ ui/

echo ">>> black --check"
$PYTHON -m black --check src/ ui/

echo ">>> flake8"
$PYTHON -m flake8 src/ ui/

echo ">>> mypy"
$PYTHON -m mypy src/
```

Hook działa w trybie **check-only** (nie modyfikuje plików) — jeśli coś nie gra, commit jest
zablokowany i dostajesz komunikat co naprawić. Przed commitem odpal `make format`.

### Instalacja hooka (raz po sklonowaniu repo)

```bash
mkdir -p hooks
cp hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

Dodaj do `README.md` żeby każdy nowy developer to zrobił po klonowaniu.

### `README.md` — minimalny szkielet onboardingowy

```markdown
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
```

### `Makefile`

```makefile
# Makefile
.PHONY: lint format typecheck test check install install-hooks lock

.venv:
	python3.12 -m venv .venv

lock: .venv
	.venv/bin/python scripts/lock_deps.py

install: .venv
	.venv/bin/pip install -r requirements.txt

install-hooks:
	cp hooks/pre-commit .git/hooks/pre-commit
	chmod +x .git/hooks/pre-commit
	@echo "Git hook installed."

lint:
	python -m flake8 src/ ui/

format:
	python -m isort src/ ui/
	python -m black src/ ui/

typecheck:
	python -m mypy src/

test:
	python -m pytest

check: format lint typecheck test
```

Użycie:
```bash
make lock            # generuje requirements.txt (przy dodawaniu/zmianie deps)
make install         # instaluje z lockfile (na nowej maszynie / po pull)
make install-hooks   # raz po sklonowaniu
make format          # przed commitem — poprawi styl automatycznie
make check           # pełna weryfikacja (format + lint + typy + testy)
```

---

## 9. Cheatsheet Komend

**Na nowej maszynie / pierwszy raz:**
```bash
cp .env.example .env   # i uzupełnij wymagane wartości w edytorze
```

**Na początku każdej sesji:**
```bash
source .venv/bin/activate
# prompt zmienia się na (.venv) $
```

```bash
# Uruchomienie serwisu
python -m src.main

# Uruchomienie UI
streamlit run ui/app.py

# Testy
python -m pytest                            # wszystkie
python -m pytest src/tests/test_normalize.py   # jeden plik
python -m pytest -v -k "test_dedup"        # konkretny test
python -m pytest --tb=short                # krótki traceback

# Linting i formatting
python -m flake8 src/ ui/                  # sprawdź błędy
python -m isort src/ ui/                  # posortuj importy
python -m black src/ ui/                  # sformatuj kod

# Type checking
python -m mypy src/

# Dodanie nowej zależności
# 1. Dopisz do requirements.ini (sekcja [main] lub [dev])
# 2. Uruchom make lock — zainstaluje i odświeży requirements.txt
make lock
```

---

## 10. Typowe Pułapki

**Import paths:** `from src.normalize import ...` wymaga `src/__init__.py` i uruchamiania z katalogu projektu. Jeśli coś nie działa, sprawdź oba.

**Venv nie aktywowany:** Gdy nie widzisz `(.venv)` w prompcie, komendy idą do systemowego Pythona. Zawsze aktywuj: `source .venv/bin/activate`.

**pip.conf nie skonfigurowany pod Artifactory:** Jeśli `pip install` zawiesza się lub zwraca 403/404, sprawdź `python3.12 -m pip config list` — `index-url` musi wskazywać na Artifactory. Patrz sekcja 0.

**SSL cert Artifactory:** Jeśli `pip install` zwraca błąd SSL (`CERTIFICATE_VERIFY_FAILED`), musisz dodać korporacyjny CA cert. Zapytaj admina o ścieżkę do cert bundle, następnie: `pip config set global.cert /path/to/ca-bundle.crt`.


**APScheduler sync vs async:** Jeśli użyjesz `httpx.AsyncClient`, potrzebujesz `AsyncScheduler` z APScheduler 4.x. Na start trzymaj httpx synchroniczny — prostsze.

**SQLAlchemy 2.0 API:** Stare tutoriale (pre-2020) pokazują `session.add()` + `session.commit()` bezpośrednio. SQLAlchemy 2.0 preferuje context manager `with Session(engine) as session:`. Trzymaj się 2.0 API i dokumentacji 2.0.

**Streamlit port 8501:** Korporacyjny firewall może blokować port. Sprawdź: `curl http://localhost:8501` z tej samej maszyny. Jeśli dostęp przez przeglądarkę jest z innej maszyny, port musi być otwarty w firewallu serwera.

**black vs isort konflikt:** Jeśli uruchomisz isort bez `profile = "black"`, black natychmiast cofnie jego zmiany (różny styl formatowania importów). `profile = "black"` w `pyproject.toml` jest obowiązkowe — bez tego będą się wzajemnie nadpisywać.

**flake8 E203 / W503:** Black formatuje slice'y (`a[1 : 2]`) i line breaks przed operatorem binarnym inaczej niż flake8 tego oczekuje. Bez `extend-ignore = E203, W503` w `.flake8` będziesz dostawał błędy na każdym sformatowanym pliku.

**`pytest-httpx` wersja:** API zmieniło się między wersjami. Używaj docs dla zainstalowanej wersji: `python -c "import pytest_httpx; print(pytest_httpx.__version__)"`.

**Streamlit session state:** Streamlit rerenderuje cały skrypt przy każdej interakcji. Stan między rerenderami trzymaj w `st.session_state`, nie w zmiennych globalnych.
