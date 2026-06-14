# Emergence-Mini

Ein minimaler, lauffähiger Klon von [Emergence-World](https://github.com/EmergenceAI/Emergence-World).
Kein LLM nötig, keine externen API-Keys, alles lokal in Python + SQLite.

![status](https://img.shields.io/badge/status-running-brightgreen) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-lightgrey) ![deps](https://img.shields.io/badge/deps-fastapi%20%7C%20uvicorn%20%7C%20sqlite3-blue)

---

## Was es kann

- 4 Agenten (Anchor, Flora, Lovely, Spark) auf einem 240×240-Grid
- 14 Orte (Town Hall, Library, Plaza, Park, Cafe, 4 Häuser, ...)
- 15 Tools (Navigation, Kommunikation, Memory, Blog, Billboard, Town Hall, ...)
- Round-Robin-Turn-Manager mit Reactive Triggern
- Needs-Decay: Energy, Knowledge, Influence
- Constitution mit 5 Artikeln, amendment-fähig via 70%-Voting
- Live-View im Browser (Canvas + WebSocket)
- Persistenz via SQLite
- 50+ automatisierte End-to-End-Tests, grün

## Was es bewusst NICHT kann (im Vergleich zum Original)

- Keine echten LLMs (regelbasierte Reasoning-Engine statt Claude/Gemini/GPT/Grok)
- Kein 3D-Frontend (2D-Canvas statt React Three Fiber)
- Kein PostgreSQL (SQLite ist ausreichend)
- Kein Multi-Model-Vergleich
- Kein Google Cloud TTS
- Kein 15-Tage-Real-Time-Sync (Ticks laufen alle 2 Sekunden)
- Kein Vector-Store für Memory-Search
- Keine AWI-Metrics (9 Indikatoren) — wäre nur mit 15-Tage-Daten sinnvoll
- Keine echten Persönlichkeits-LLM-Prompts (Traits sind deterministisch regelbasiert)

---

## Quickstart

```bash
git clone https://github.com/Jeuners/emergence-mini-dilles.git
cd emergence-mini-dilles
pip install -r requirements.txt
./run.sh
# Browser auf http://127.0.0.1:8080
```

Optional mit LLM-Reasoning (empfohlen):

```bash
# Ollama lokal starten (falls nicht bereits laufend)
ollama serve &
# Modell ziehen (einmalig, ~2 GB)
ollama pull llama3.2:3b
# Emergence-Mini mit LLM starten
./run.sh
```

Optional mit Tests:

```bash
python3 -m pytest tests/ -v           # 80+ Unit + Integration Tests
python3 smoke_test.py                 # End-to-End Smoke Test (regelbasiert)
python3 smoke_test_llm.py             # Live-LLM-Test (braucht Ollama)
```

---

## Endpoints

| Method | Path | Beschreibung |
|--------|------|--------------|
| `GET`  | `/api/state` | Kompletter Snapshot (Agenten, Landmarks, Constitution, Tick) |
| `GET`  | `/api/agents` | Liste der aktiven Agenten |
| `GET`  | `/api/landmarks` | Liste aller Orte |
| `GET`  | `/api/proposals` | Aktive + vergangene Proposals |
| `GET`  | `/api/constitution` | Aktuelle Verfassung |
| `GET`  | `/api/events` | Letzte 100 Events |
| `GET`  | `/api/memories/{id}` | Memory eines Agenten |
| `GET`  | `/api/blogs` | Veröffentlichte Blog-Posts |
| `POST` | `/api/turn/{id}` | Tool manuell auslösen (Body: `{"tool": "...", "args": {...}}`) |
| `WS`   | `/ws` | Live-Stream (snapshot + action + tick) |
| `GET`  | `/` | Single-Page-Live-View |

---

## Architektur

```
emergence-mini-dilles/
├── server.py              FastAPI + WebSocket entry
├── engine/
│   ├── db.py              SQLite persistence + schema migration
│   ├── world.py           240×240 grid + landmarks + hearing range
│   ├── agents.py          Agent state, personality, position
│   ├── needs.py           Energy/Knowledge/Influence decay
│   ├── tools.py           Tool registry + handlers + location-gating
│   ├── reasoning.py       Decision engine (LLM + rule-based fallback)
│   ├── llm.py             Ollama client + OpenAI-style tool schema
│   ├── governance.py      Constitution + Town Hall voting (70% threshold)
│   └── turn.py            Round-robin + reactive triggers
├── data/
│   └── constitution.json  Seed constitution (5 articles)
├── web/                   Static SPA (kein Build-Tool nötig)
│   ├── index.html
│   ├── style.css
│   └── app.js             Canvas-Renderer + WebSocket-Client
├── tests/
│   ├── conftest.py
│   ├── test_db.py
│   ├── test_world.py
│   ├── test_agents.py
│   ├── test_tools.py
│   ├── test_governance.py
│   ├── test_reasoning.py
│   ├── test_llm.py
│   └── test_api.py
├── smoke_test.py          End-to-End Live-Test (regelbasiert, 50+ Checks)
├── smoke_test_llm.py      Live-LLM-Test gegen echtes Ollama-Modell
├── requirements.txt
├── run.sh                 Startet uvicorn auf Port 8080
└── .gitignore
```

### Daten-Modell

| Tabelle | Zweck |
|---------|-------|
| `world_state` | Key/Value für Tick, Bootstrap-Flags |
| `agents` | 4 Agenten, alle Needs als REAL, Mood, Alive-Flag |
| `landmarks` | 14 Orte, (x, y) auf 240×240-Grid |
| `memories` | Long-term Memory pro Agent |
| `relationships` | Affinity-Matrix zwischen Agenten |
| `events` | Append-only Event-Log (Proposals, Posts, Ticks) |
| `proposals` | Town-Hall-Vorschläge + Status + Applied-Flag |
| `votes` | Pro Agent eine Stimme pro Proposal |
| `bills` | Blog-Posts |
| `constitution` | Versionierte Verfassung (jede Änderung = neue Row) |
| `turn_log` | Append-only Tool-Call-Log |

### Sicherheitsmodell

Der Server lauscht auf `127.0.0.1:8080` — **nicht** auf `0.0.0.0`. Er ist explizit als
Local-Dev-Tool gedacht, nicht als öffentlicher Service. Für Produktion:
- Reverse-Proxy mit Auth davor (z. B. Caddy mit Basic-Auth)
- `uvicorn` hinter `gunicorn` + `systemd`
- DB regelmäßig sichern

---

## LLM Integration

Emergence-Mini unterstützt **lokale LLMs via Ollama** als Reasoning-Engine.
Ohne LLM läuft die regelbasierte Engine (deterministisch, schnell, gut für
Tests). Mit LLM werden die Agenten emergent, character-stimmig und
nicht-reproduzierbar — wie im Original.

### Setup

```bash
# 1. Ollama installieren (falls nicht vorhanden)
# macOS:   brew install ollama
# Linux:   curl -fsSL https://ollama.com/install.sh | sh
# Windows: https://ollama.com/download

# 2. Ollama starten
ollama serve

# 3. Modell ziehen (einmalig, ~2 GB für 3B, ~5 GB für 7B)
ollama pull llama3.2:3b

# 4. Emergence-Mini starten (LLM wird automatisch erkannt)
./run.sh
```

### Konfiguration via Umgebungsvariablen

| Variable | Default | Beschreibung |
|----------|---------|--------------|
| `EMERGENCE_LLM_ENABLED` | `1` | `0` erzwingt regelbasierte Engine |
| `EMERGENCE_LLM_URL` | `http://127.0.0.1:11434` | Ollama-Server |
| `EMERGENCE_LLM_MODEL` | `llama3.2:3b` | Modell-Name (siehe unten) |
| `EMERGENCE_LLM_TIMEOUT` | `30` | Request-Timeout in Sekunden |

Beispiel mit größerem Modell:

```bash
EMERGENCE_LLM_MODEL=qwen2.5-coder:7b ./run.sh
```

### Empfohlene Modelle

| Modell | Größe | Stärke | Schwäche |
|--------|-------|--------|----------|
| **`llama3.2:3b`** ⭐ | 2.0 GB | Schnell, gute Tool-Use-Fähigkeit, niedriger RAM-Bedarf | Kurze Antworten |
| `gemma3:latest` | 3.3 GB | Bewährt, gute Reasoning-Qualität | Mittel-schnell |
| `qwen2.5-coder:7b` | 4.7 GB | Exzellent für strukturierte Aufgaben | Höherer RAM-Bedarf |
| `qwen3.5:latest` | 6.6 GB | Neueste Generation, multimodal | Langsamer |
| `gemma4:latest` | 9.6 GB | Bestes Reasoning | Langsam, hoher RAM |

Für die meisten Setups ist **llama3.2:3b** der beste Kompromiss: ~1-3s Latenz
pro Decision, 4-8 GB RAM, deterministische Tool-Calls.

Modelle ohne brauchbare Tool-Use-Fähigkeit (z.B. `moondream`,
`nomic-embed-text`) werden zwar nicht crashen, aber das System fällt auf
die regelbasierte Engine zurück.

### Wie es funktioniert

Pro Agent-Turn:

1. Engine sammelt Personality-Traits, aktuellen State (Energy, Knowledge,
   Influence, Credits), Position und sichtbare Tools (gefiltert nach
   Location-Gating).
2. Baut einen System-Prompt mit dieser Kontext-Information.
3. Sendet `/api/chat` an Ollama mit Tool-Schema im OpenAI-Format.
4. Validiert die Antwort: Tool muss existieren, Location muss passen.
5. Bei Validierungs-Fehler oder Verbindungs-Problemen: **Fallback zur
   regelbasierten Engine**, damit die Simulation nie hängt.

Die `get_last_decision()`-Funktion in `engine.reasoning` exponiert den
Modus (`llm`, `rule`, `fallback:...`) und die Latenz. Im Live-View ist
das via WebSocket sichtbar (im `rationale`-Feld).

### Eigene System-Prompts

Die Persona-Beschreibung lebt in `engine/reasoning.py:_build_system_prompt`.
Du kannst sie für deinen Use-Case anpassen (z.B. spezifischere Regeln,
andere Tool-Beschreibungen, anderer Ton).

### Tests

- **Mock-Tests** in `tests/test_llm.py` prüfen Schema-Generierung,
  Response-Parsing, Fallback-Pfade. 11 Tests, alle ohne Netzwerk.
- **Live-Smoke** in `smoke_test_llm.py` ruft das echte Modell 4× auf und
  meldet Mode + Latenz pro Decision.

---

## Security

Emergence-Mini ist ein lokales Dev-Tool. Es ist **nicht** für den öffentlichen Einsatz
vorbereitet. Folgende Punkte sind bewusst NICHT enthalten:

### Was es nicht macht (by design)

- **Keine Authentifizierung** — alle Endpoints sind offen. Der Server bindet nur auf
  `127.0.0.1`, das setzt einen lokalen Nutzer voraus.
- **Keine Rate-Limits** — `POST /api/turn/{id}` kann endlos gefeuert werden. Ein
  Angreifer mit Loop-Zugriff könnte die DB mit Rows fluten.
- **Keine Input-Validierung** — Tool-Args werden ohne JSON-Schema geprüft. Falsche
  Typen führen zu `KeyError`/`TypeError` im Handler, nicht zu 400.
- **Keine CORS-Restriktionen** — Browser-Apps von beliebigen Origins können die API
  konsumieren, wenn der Server öffentlich erreichbar wird.
- **Keine SQL-Injection-Schutzmaßnahmen** jenseits parametrisierter Queries — die
  SQL-Statements sind alle `?`-gebunden, aber Strings werden nicht escaped, falls
  sie direkt interpoliert würden (aktuell kein Fall).
- **Keine Secrets** — keine API-Keys, keine Tokens, keine Passwörter im Code oder
  in der DB.
- **Kein Logging sensibler Daten** — der `turn_log` enthält nur Tool-Name + Args.
  Kein Memory-Inhalt, keine persönlichen Daten.

### Hardening-Checkliste vor Public Deploy

```bash
# 1. Auf 0.0.0.0 nur hinter Reverse-Proxy erlauben
# 2. Auth-Layer hinzufügen (z. B. via Caddy + Basic-Auth oder oauth2-proxy)
# 3. Schema-Validierung pro Tool-Endpoint
# 4. Rate-Limiting (z. B. slowapi)
# 5. CORS-Whitelist
# 6. HTTPS terminieren
# 7. DB-Backups in separaten Storage
# 8. Monitoring (z. B. Prometheus-Endpoint)
```

### Verletzliche Annahmen

| Annahme | Risiko |
|---------|--------|
| Loopback-only Binding | Bei `0.0.0.0` sofort öffentlich erreichbar |
| Trust im Tool-Args | Handler setzen Tool-Args als SQL-Params; Schema-Mismatch crasht Handler |
| Single-User | Concurrency über `SQLite-WAL`, aber kein Row-Locking pro Agent |

### Reporting

Security-Issues bitte per Mail an den Maintainer (siehe GitHub-Profil) — nicht
als Public Issue.

---

## Tests

### Test-Suite ausführen

```bash
# Alle Unit + Integration Tests
python3 -m pytest tests/ -v

# Nur Smoke-Test (End-to-End inkl. Live-Server)
python3 smoke_test.py

# Mit Coverage
pip install coverage
python3 -m coverage run -m pytest tests/
python3 -m coverage report
```

### Was getestet wird

| Test | Was |
|------|-----|
| `test_db.py` | Schema-Erstellung, World-State-Get/Set, Event-Log |
| `test_world.py` | Landmark-Seeding, Distance-Funktion, Hearing-Range, Location-Detection |
| `test_agents.py` | Agent-Bootstrap, Personality-Loading, State-Updates, Position-Updates |
| `test_tools.py` | Alle 15 Tool-Handler, Location-Gating, Fehler-Pfade |
| `test_governance.py` | 70%-Threshold, Auto-Reject, Constitution-Amendment-Apply |
| `test_reasoning.py` | Decision-Engine für alle Personality-Types, Edge-Cases |
| `test_llm.py` | Ollama-Client, Tool-Schema, Mock-Tests für LLM-Pfad, Fallbacks |
| `test_api.py` | Alle HTTP-Endpoints, WebSocket, POST /api/turn |

### Smoke-Test-Details

`smoke_test.py` läuft **14 Sektionen mit 50+ Assertions** ohne externen Server:

1. Bootstrap (DB, 14 Landmarks, 4 Agenten, 15 Tools)
2. Agent-State (Needs, Personality, Home-Position)
3. Tools: Navigation (`go_to_place`, Position-Update)
4. Tools: Communication (`say_to_agent`, Speak-Events)
5. Tools: Memory (Persistenz in `memories`-Tabelle)
6. Tools: Blog (Knowledge-Boost, Bill-Eintrag)
7. Tools: Billboard (Location-Gating verifiziert)
8. Town Hall: Proposal + 4× Vote → accepted, Constitution wächst von 5 auf 6 Artikel
9. Energy-System: Recharge +50%, Credits -1
10. Reasoning-Engine: Round läuft, Tool-Selection funktioniert
11. Needs-Decay: Energy sinkt über mehrere Ticks
12. Reactive Triggers: `speak_to_all` triggert Listener
13. Persistenz: Proposals, Memories, Bills, Turn-Log vorhanden
14. Live-Server: Startet uvicorn auf Port 8090, testet alle REST-Endpoints + POST + WS

### Bekannte Test-Lücken

- Keine Concurrency-Tests (mehrere parallele `force_turn`-Calls)
- Keine Last-Tests (1000+ Ticks in kurzer Zeit)
- Keine Fuzz-Tests für Tool-Args
- Keine Frontend-Tests (Canvas-Renderer, WebSocket-Client sind ungetestet)

### CI-Integration

GitHub Actions Template (nicht enthalten, easy nachzurüsten):

```yaml
# .github/workflows/test.yml
name: tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.10'
      - run: pip install -r requirements.txt
      - run: python3 -m pytest tests/ -v
      - run: python3 smoke_test.py
```

---

## Lizenz

Emergence-Mini ist inspiriert vom CC-BY-NC-4.0-Original von [Emergence AI](https://github.com/EmergenceAI/Emergence-World).
Dieser Klon: **MIT** für nicht-kommerzielle Nutzung, ohne Gewähr.

Die LLM-Integration erwartet eine lokale Ollama-Instanz und nutzt
[Ollamas OpenAI-kompatible Tool-Calling-API](https://ollama.com/blog/tool-support).
Ollama selbst ist MIT-lizenziert. Die Modelle (llama3.2, qwen, gemma)
unterliegen ihren eigenen Lizenzen — bitte vor kommerzieller Nutzung
prüfen.

Quell-Repo: https://github.com/EmergenceAI/Emergence-World (Doku, Profile, Landmarks, Constitution, Tool-Katalog)

---

## Maintainer

Jeuners · https://github.com/Jeuners/emergence-mini-dilles
