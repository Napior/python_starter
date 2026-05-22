# Serwis analityczny alertów — Brainstorming architektoniczny

## Kontekst

Operatorzy w centrum operacyjnym ręcznie korelują alerty z wielu systemów monitoringu
(Zabbix, SCOM, Splunk, Pingdom, Monit24). Backend normalizuje te alerty do JSON i
przekazuje je z szyny zdarzeń. Chcemy zautomatyzować korelację i wykrywanie root cause
za pomocą LLM działającego przez proxy LiteLLM (wewnętrzne, OpenAI-compatible).

**Output:** UI dla operatorów pokazujące zgrupowane incydenty z hipotezą root cause.

---

## Architektura (komponenty i przepływ danych)

**Kluczowa decyzja: POLLING, nie push webhook.**
Serwis aktywnie odpytuje backend co 5 minut LUB operator triggeruje analizę on-demand.
Eliminuje to potrzebę Ingest API i Redis Streams — znaczące uproszczenie.

```
Monitoring systems (Zabbix/SCOM/Splunk/Pingdom/Monit24)
        │
        ▼  (istniejący backend + szyna zdarzeń → JSON)
┌──────────────────────────────────────────────────────────────┐
│                  ALERT CORRELATION SERVICE                   │
│                                                              │
│  ┌─────────────────────────────────────────────────────┐    │
│  │  Alert Poller                                        │    │
│  │  • co 5 min (scheduler) → GET /backend/alerts?since= │    │
│  │  • on-demand → operator klika "Analizuj teraz"      │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                          │                                   │
│                          ▼                                   │
│  [Normalizacja + deduplication]                              │
│   • mapowanie severity per system                            │
│   • hash dedup_key, repeat_count                             │
│   • sortowanie po timestamp                                  │
│                          │                                   │
│                          ▼                                   │
│  [Analysis Pipeline]                                         │
│   • CMDB Retriever (Chroma RAG) ← opcjonalnie                │
│   • LLM Client (httpx → LiteLLM proxy)                       │
│   • parsowanie JSON odpowiedzi z retry                       │
│                          │                                   │
│                          ▼                                   │
│  [Results Store] (SQLite)                                    │
└──────────────────────────┬───────────────────────────────────┘
                           │
                           ▼
               [Operator UI] (Streamlit)
               • lista analiz (historia)
               • ostatni wynik LLM
               • przycisk "Analizuj teraz"
               • tabela surowych alertów z batchu
```

### Przepływ danych krok po kroku

1. Scheduler odpala co 5 minut (lub operator klika "Analizuj teraz")
2. Alert Poller pobiera z backendu alerty z ostatnich N minut (`?since=<timestamp>`)
3. Normalizacja: mapowanie severity, ustawianie fallback pól, dedup
4. Jeśli batch pusty → skip (loguj, nie wywołuj LLM)
5. CMDB Retriever: hosty z batchu → Chroma → inject topology context
6. LLM Client: buduje prompt, wywołuje LiteLLM proxy, parsuje JSON
7. Wynik zapisywany do SQLite
8. UI odświeża się (Streamlit auto-refresh / przycisk)

---

## Kluczowe decyzje projektowe

### 1. Strategia pobierania alertów — POLLING

**Tryb automatyczny:** scheduler co 5 minut pobiera alerty z backendu.
```
GET /backend/api/alerts?since=<last_run_timestamp>&until=<now>
```
- `last_run_timestamp` zapisywany po każdej udanej analizie (w SQLite)
- Pierwsze uruchomienie: `since = now - 5min`
- Okno nakłada się o 30s (overlap) żeby nie zgubić alertów na granicy

**Tryb on-demand:** operator klika przycisk w UI → natychmiastowy pull z ostatnich N minut.
- Konfigurowalny parametr: 2, 5, 10, 15 minut wstecz
- Przydatny gdy incident właśnie trwa i operator chce analizę "tu i teraz"

**Skip logic:** jeśli batch pusty (0 alertów) → skip LLM, zaloguj, czekaj na następny cykl.

### 2. Deduplication

Klucz: `hash(source_system + host + alert_code)`. Zachowaj pierwsze wystąpienie + pole `repeat_count`.
LLM wie, że `repeat_count > 1` = alert trwał przez cały czas okna, nie jest nowym zdarzeniem.

### 3. Schemat alertu (canonical internal schema)

```json
{
  "alert_id": "uuid (generowany przez ingest jeśli brak w źródle)",
  "source_system": "zabbix|scom|splunk|pingdom|monit24|unknown",
  "timestamp": "ISO 8601 UTC",
  "received_at": "ISO 8601 UTC (fallback jeśli timestamp brakuje)",
  "severity": "critical|high|medium|low|info|unknown",
  "host": "hostname lub null",
  "component": "nginx|oracle-db|vpn-gateway lub null",
  "environment": "production|staging|test|null",
  "message": "oryginalna treść (PL lub EN)",
  "alert_code": "trigger ID ze źródła lub null",
  "metric": {"name": "", "value": 0, "unit": "", "threshold": 0},
  "tags": {"original_severity": "..."},
  "url": "link do alertu w systemie źródłowym lub null",
  "repeat_count": 1,
  "dedup_key": "hash lub null",
  "raw": {}
}
```

**Severity mapping (normalizacja):**

| Źródło | Poziom źródłowy | → Normalny |
|--------|----------------|------------|
| Zabbix | Disaster | critical |
| Zabbix | High | high |
| Zabbix | Average | medium |
| Zabbix | Warning | low |
| Zabbix | Information | info |
| SCOM | Critical | critical |
| SCOM | Error | high |
| SCOM | Warning | medium |
| SCOM | Informational | info |
| Splunk | CRITICAL | critical |
| Splunk | ERROR | high |
| Splunk | WARN | medium |
| Splunk | INFO | info |
| Pingdom | Down | critical |
| Pingdom | Up | info |
| Monit24 | (dopasować do skali) | — |

Jeśli severity nie da się zmapować: `"unknown"`, oryginał w `tags.original_severity`.

### 4. LLM Prompt Design

**System prompt — rola Senior SRE / root cause analyst:**

```
You are a senior Site Reliability Engineer and root cause analyst working in a
corporate IT operations center. You specialize in correlating alerts from multiple
monitoring systems (Zabbix, SCOM, Splunk, Pingdom, Monit24) to identify incidents
and their root causes.

RULES:
1. Respond ONLY with valid JSON matching the output schema. No prose outside JSON.
2. Alerts may be in Polish or English. Reason in English.
3. If evidence is insufficient, say so explicitly in the hypothesis.
4. Alerts within 30 seconds on related systems are likely correlated.
5. A single failure triggers alerts across multiple monitoring systems simultaneously.
6. Distinguish root cause (originating failure) from symptoms (downstream effects).
7. If no correlation exists, say so clearly.
```

**Output schema z LLM:**
```json
{
  "analysis_id": "...",
  "analyzed_at": "ISO 8601 UTC",
  "summary": "1-2 zdania co się stało",
  "incident_groups": [{
    "group_id": "G1",
    "name": "krótka nazwa incydentu",
    "alert_ids": ["..."],
    "timeline": [{"timestamp": "...", "alert_id": "...", "event": "krótki opis"}],
    "affected_systems": ["host-A", "service-X"],
    "root_cause_hypothesis": "konkretna hipoteza z uzasadnieniem",
    "confidence": "high|medium|low",
    "confidence_reasoning": "dlaczego taki poziom pewności",
    "recommended_action": "co operator powinien zrobić jako pierwsze"
  }],
  "unrelated_alerts": ["alert_id_1", "..."],
  "topology_notes": "obserwacje z CMDB jeśli był context",
  "data_quality_issues": "brakujące pola, podejrzane timestampy, luki"
}
```

**Do prompta idzie compact JSON alertów** (bez pola `raw`), sortowane po timestamp.
Pola: `alert_id, source_system, timestamp, severity, host, component, message, repeat_count`.

**Budget tokenów:** ~3000 na alerty, 500 na system prompt + CMDB context, 1500 na odpowiedź.
Jeśli batch przekracza limit → split po klastrach hostów lub oknie czasowym.

### 5. CMDB — dict lookup + inject do promptu (bez embeddingów, bez Chroma)

Chroma i embeddingi odpada — nie ma lokalnych modeli, a `/embeddings` w proxy niepewne.
Zamiast semantic search: **keyword lookup po hostname** — hosty i tak znamy z alertów,
więc vector search niczego tu nie wnosi.

**Approach:**
1. Jednorazowy eksport CMDB → JSON/CSV
2. Przy starcie serwisu: załaduj do pamięci jako `dict[hostname → {services, depends_on, owner, criticality}]`
3. Przy każdej analizie: hosty z batchu → dict lookup → zbierz wpisy
4. Wstrzyknij jako blok tekstowy do promptu LLM

```python
# cmdb.py
CMDB: dict = {}  # załadowany przy starcie z pliku

def get_context(hosts: list[str]) -> str:
    entries = [CMDB[h] for h in hosts if h in CMDB]
    if not entries:
        return ""
    lines = [f"- {e['host']}: runs {e['services']}, depends on {e['depends_on']}" for e in entries]
    return "INFRASTRUCTURE CONTEXT:\n" + "\n".join(lines)
```

**Dlaczego to wystarczy:**
- CMDB jest ustrukturyzowany — wiesz dokładnie po jakim kluczu szukać (hostname)
- Semantic search byłby potrzebny gdybyś szukał po opisach tekstowych, nie po nazwie hosta
- LLM i tak robi semantyczne wnioskowanie na wstrzykniętym tekście

**Refresh:** podmień plik JSON + restart (lub `cmdb.reload()` bez restartu).

**Limit tokenów:** jeśli batch ma 50 hostów × ~50 tokenów na wpis = 2500 tokenów.
Jeśli za dużo: ogranicz do hostów z `severity >= high`.

### 6. Tech Stack

Polling upraszcza stack — odpada Redis Streams i Ingest API.

| Warstwa | Wybór | Uzasadnienie |
|---------|-------|--------------|
| Scheduler | APScheduler (in-process) | polling co 5 min, zero infra, jeden proces |
| HTTP client | httpx | polling backendu + wywołania LiteLLM proxy |
| Normalizacja | plain Python dicts | backend już normalizuje; severity mapping = dict lookup; dedup = hashlib |
| LLM client | httpx bezpośrednio do LiteLLM proxy | pełna kontrola, łatwość debugowania |
| Results | SQLite | zero infra; zapis wyników + `last_run_timestamp` |
| CMDB | dict w pamięci (JSON file) | hostname lookup, inject do promptu; zero embeddingów |
| UI | Streamlit | szybkie demo; przycisk "Analizuj teraz" = on-demand trigger |

**Co odpada (vs pierwotna wersja):**
- Redis Streams — polling zastępuje push buffer
- FastAPI Ingest API — brak webhook receivera
- WebSocket broadcaster — Streamlit auto-refresh wystarczy
- Pydantic — plain dicts wystarczą
- Chroma + sentence-transformers + /embeddings — dict lookup po hostname wystarczy

---

## Plan implementacji (fazy)

### Faza 1: MVP core
- `normalize.py`: severity mapping dicts per system, dedup via `hashlib`, filter fields for prompt
- `AlertPoller`: httpx → `GET /backend/api/alerts?since=&until=`, wywołaj normalize, dedup
- APScheduler: poll co 5 minut, zapis `last_run_timestamp` do SQLite
- LLM client: httpx → LiteLLM proxy, prompt builder, JSON parser z retry
- SQLite: wyniki analiz + `last_run_timestamp`
- Streamlit UI:
  - przycisk "Analizuj teraz" (on-demand, wybór okna: 2/5/10/15 min)
  - ostatnia analiza (summary, incydenty, affected systems, confidence)
  - tabela surowych alertów z batchu
  - historia analiz

**Kamień milowy:** scheduler triggeruje → alerty pobrane → LLM analysis widoczny w UI

### Faza 2: CMDB + jakość
- `cmdb.py`: load JSON/CSV przy starcie, dict lookup, `get_context(hosts)`
- Config flag: enable/disable CMDB context w prompcie
- Token counting przed LLM call, ogranicz CMDB context do hostów severity >= high
- Error handling: timeout, malformed JSON, dead letter log

### Faza 3: Rozszerzenia
- Operator feedback (correct/incorrect hypothesis)
- Refinement promptów na podstawie feedbacku
- Lepsza UI jeśli Streamlit niewystarczający

---

## Ryzyka i mitygacje

| Ryzyko | Prawdopod. | Mitygacja |
|--------|------------|-----------|
| LLM nie zwraca valid JSON | Średnie | Retry z "fix the JSON" promptem; 2x fail → store raw text, nie blokuj pipeline |
| Rate limits LiteLLM proxy | Średnie | Exponential backoff 3x retry; ustalić SLA z właścicielem proxy |
| Zbyt duży batch > token budget | Wysokie | Token count przed wywołaniem; split po klastrach hostów |
| Backend alerts API niedostępny | Średnie | Loguj błąd, pomiń cykl; UI pokazuje status ostatniego poll |
| Stale CMDB | Wysokie | CMDB jako supplementary; prompt mówi LLM żeby notował sprzeczności |
| Operatorzy nie ufają LLM | Średnie-Wysokie | Confidence badge, surowe alerty obok, `recommended_action` jako CTA |
| Nakładające się okna polling | Niskie | 30s overlap + dedup_key eliminuje duplikaty między cyklami |

---

## Otwarte pytania

1. ~~**Sposób odbierania alertów:**~~ **RESOLVED** → polling co 5 min + on-demand
2. **Backend alerts API:** jaki dokładnie endpoint? Parametry filtrowania (`since`, `until`, `severity`)?
   Wymagana auth?
3. **CMDB:** czy da się uzyskać jednorazowy export (CSV/JSON/Excel)?
4. **LiteLLM proxy:** jaki model? Limity RPM/TPM? Endpoint embeddingowy?
5. **Środowisko deploymentu:** VM, kontener, lokalna maszyna?
6. **Języki alertów:** proporcja PL vs EN?

---

## Struktura plików projektu

```
analityka_praca/
├── src/
│   ├── normalize.py          # severity mapping dicts, dedup via hashlib, field filter
│   ├── poller.py             # httpx → backend API, wywołuje normalize
│   ├── llm_client.py         # httpx → LiteLLM proxy, prompt builder, json.loads z retry
│   ├── cmdb.py               # load JSON/CSV → dict, get_context(hosts) → str
│   ├── db.py                 # SQLite: zapis wyników, last_run_timestamp
│   └── main.py               # APScheduler setup, entry point
├── ui/
│   └── app.py                # Streamlit UI z przyciskiem on-demand
├── cmdb_rebuild.py           # CMDB export → Chroma (jednorazowy/cron)
├── pyproject.toml
└── plan.md                   # ten plik
```
