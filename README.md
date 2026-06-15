# Emergence-Mini

Ein lauffähiger Klon von [Emergence-World](https://github.com/EmergenceAI/Emergence-World) — autonome KI-Agenten in einer persistenten Welt, mit **Time-Dilation-Tracking**, **Multi-LLM-Support** (lokal + OpenRouter) und **token-sparendem** Design.

Default-Modus: **Ollama lokal** (free, 0 Tokens). Optional OpenRouter.

![status](https://img.shields.io/badge/status-running-brightgreen) ![tests](https://img.shields.io/badge/tests-99%20passing-brightgreen) ![python](https://img.shields.io/badge/python-3.10%2B-blue) ![license](https://img.shields.io/badge/license-MIT-lightgrey) ![provider](https://img.shields.io/badge/LLM-Ollama%20%7C%20OpenRouter-blue) ![cost](https://img.shields.io/badge/cost-zero%20with%20Ollama-success)

---

## Highlights

| | |
|---|---|
| 🤖 **4 Agenten** | Anchor, Flora, Lovely, Spark — eigene Persönlichkeit, Rollen, Ziele |
| 🌐 **240×240 Grid** | 14 Orte, Location-Gated Tools, Hearing-Range |
| ⚖️ **Self-Governance** | 5-Artikel-Constitution, amendment-fähig via 70%-Voting |
| 🧠 **Time Dilation (τ)** | Per-Agent Eigenzeit, EWMA-Pace, Causal-Dilation Clock, Drift-Detection |
| 🔌 **Multi-LLM** | Ollama (default, free) + OpenRouter (opt-in); per-Agent-Modelle |
| 💸 **Token-sparend** | Kompakter System-Prompt (~150 T), max_tokens=256, kurze Tool-Desc |
| 🖥️ **Live-View** | Canvas-Grid + WebSocket + τ-Timeline + Drift-Warnung im Browser |
| ✅ **99 Tests** | Unit + Integration + Mock-LLM, alle grün |

## Inhalt

- [Quickstart](#quickstart)
- [Architektur](#architektur)
- [Endpoints](#endpoints)
- [Time Dilation (τ)](#time-dilation-τ)
- [LLM Provider](#llm-provider)
- [Tests](#tests)
- [Security](#security)
- [Was fehlt gegenüber dem Original](#was-fehlt-gegenüber-dem-original)
- [Lizenz](#lizenz)

---

## Quickstart

### 0. Tokens, ohne LLM (deterministisch, free)

```bash
git clone https://github.com/Jeuners/emergence-mini-dilles.git
cd emergence-mini-dilles
pip install -r requirements.txt
EMERGENCE_LLM_ENABLED=0 ./run.sh
# http://127.0.0.1:8080
```

### 1. Lokal mit Ollama (empfohlen, **0 Tokens**)

```bash
# Ollama installieren (https://ollama.com)
ollama serve &
ollama pull llama3.2:3b   # ~2 GB

# Emergence-Mini starten
./run.sh
```

`.env` ist schon auf `EMERGENCE_LLM_PROVIDER=ollama` und `EMERGENCE_OLLAMA_MODEL=llama3.2:3b` vorkonfiguriert.

### 2. Cloud via OpenRouter (opt-in, kostenpflichtig)

```bash
# Key in .env setzen
echo "OPENROUTER_API_KEY=sk-or-v1-..." >> .env
echo "EMERGENCE_LLM_PROVIDER=openrouter" >> .env

./run.sh
```

Per-Agent-Modelle setzen (für Time-Dilation-Experimente):

```bash
# in .env
EMERGENCE_AGENT_ANCHOR_MODEL=anthropic/claude-3.5-haiku
EMERGENCE_AGENT_FLORA_MODEL=openai/gpt-4o-mini
EMERGENCE_AGENT_LOVELY_MODEL=meta-llama/llama-3.3-70b-instruct
EMERGENCE_AGENT_SPARK_MODEL=google/gemma-3-4b-it
```

### 3. Tests laufen lassen

```bash
python3 -m pytest tests/ -v   # 99 Tests, ~60s
python3 smoke_test.py         # End-to-End regelbasiert
```

---

## Architektur

```
emergence-mini-dilles/
├── server.py                 FastAPI + WebSocket entry
├── engine/
│   ├── time.py               τ-Tracker, Pace-EWMA, Causal-Dilation Clock
│   ├── llm.py                Ollama + OpenRouter clients, Tool-Schema
│   ├── reasoning.py          LLM-Decision-Engine (mit rule-basiertem Fallback)
│   ├── tools.py              15 Tools, Location-Gating, Handler
│   ├── turn.py               Round-Robin + Reactive Triggers
│   ├── agents.py             Agent-Model (Persönlichkeit, Needs, Mood)
│   ├── world.py              240×240 Grid, Landmarks, Hearing-Range
│   ├── needs.py              Energy/Knowledge/Influence decay
│   ├── governance.py         Constitution + 70%-Voting
│   └── db.py                 SQLite + Schema-Migration
├── data/constitution.json    5-Artikel Seed-Constitution
├── web/                      SPA (kein Build-Tool)
│   ├── index.html            Layout + τ-Timeline + Drift-Indicator
│   ├── app.js                Canvas + WebSocket + τ-Bars
│   └── style.css
├── tests/                    99 Unit + Integration + Mock-LLM
├── smoke_test.py             End-to-End (regelbasiert)
├── .env / .env.example       Konfiguration (git-ignored: .env)
├── requirements.txt
└── run.sh                    Startet uvicorn auf 127.0.0.1:8080
```

### Daten-Modell (12 Tabellen)

| Tabelle | Zweck |
|---------|-------|
| `agents` | 4 Agenten mit Needs, Mood, Personality-JSON |
| `landmarks` | 14 Orte mit (x, y) auf dem Grid |
| `memories` | Long-term Memory pro Agent |
| `relationships` | Affinity-Matrix (für spätere Erweiterung) |
| `events` | Append-only Event-Log (Proposals, Posts, Ticks) |
| `proposals` | Town-Hall-Vorschläge + Status + Applied-Flag |
| `votes` | Pro Agent eine Stimme pro Proposal |
| `bills` | Blog-Posts |
| `constitution` | Versionierte Verfassung |
| `turn_log` | **Append-only Tool-Call-Log mit τ, Pace, Model** |
| `agent_clocks` | Persistierte τ-/Pace-Stände |
| `world_state` | Key/Value (Tick, Bootstrap-Flags) |

---

## Endpoints

| Method | Path | Beschreibung |
|--------|------|--------------|
| `GET`  | `/api/state` | Komplett-Snapshot (Agents, Landmarks, Constitution, **τ, Drift**, LLM-Info) |
| `GET`  | `/api/agents` | Aktive Agenten |
| `GET`  | `/api/landmarks` | Alle Orte |
| `GET`  | `/api/proposals` | Aktive + vergangene Proposals |
| `GET`  | `/api/constitution` | Aktuelle Verfassung |
| `GET`  | `/api/events` | Letzte 100 Events |
| `GET`  | `/api/memories/{id}` | Memory eines Agenten |
| `GET`  | `/api/blogs` | Blog-Posts |
| `POST` | `/api/turn/{id}` | Tool manuell auslösen |
| `WS`   | `/ws` | Live-Stream (snapshot + action + tick + **τ-Broadcast**) |
| `GET`  | `/` | Single-Page-Live-View |

---

## Time Dilation (τ)

Implementiert die Kern-Konzepte aus [Time Dilation in LLM Agent Systems](https://github.com/Jeuners/Time_Dilation_in_LLM_Agent_Systems) (Dillenberg 2026).

### Konzepte

- **Eigenzeit τ** (proper time) — pro Agent kumulativ. Advanced per Reasoning-Step (+1.0), Tool-Call (+0.5), Memory-Lookup (+0.2), Reactive-Ack (+0.3). Monoton wachsend.
- **Pace** — EWMA (α=0.3) der Operations-Rate pro Agent.
- **Causal-Dilation Clock (CDC)** — Paar aus (vector, dilation-vector) pro Aktion. Jede WebSocket-Message trägt `tau` und `pace`.
- **Frame-Transformation Φ** — Φ_{src→dst}(τ) = γ · τ, mit γ = pace(src) / pace(dst).
- **Drift-Detection** — `|τ_a − Φ(τ_b)| > 3.0` triggert eine Warnung im UI.

### Live-Validierung

4 verschiedene OpenRouter-Modelle parallel, gemessen über mehrere Rounds:

```
spark    τ=18.0  pace=6.07 op/s  google/gemma-3-4b-it
lovely   τ=18.0  pace=6.07 op/s  meta-llama/llama-3.3-70b-instruct
flora    τ=19.2  pace=6.07 op/s  openai/gpt-4o-mini
anchor   τ=19.2  pace=6.07 op/s  anthropic/claude-3.5-haiku
```

**Erkenntnis:** γ ≈ 1.00 über alle Paare. Die explizite Round-Robin + `sleep(2)`-Sync hält die Frames kohärent. Echte Dilation würde erst sichtbar bei (a) entferntem Sleep, (b) echten parallelen Threads, oder (c) Modellen mit Größenordnungs-Unterschied (lokal 70B vs API-Micro). Siehe §5.4 des Original-Papers für ein analoges Experiment.

### Wo es lebt

| Datei | Inhalt |
|-------|--------|
| `engine/time.py` | `AgentClock`, `ClockRegistry`, τ, Pace-EWMA, Drift-Report |
| `engine/turn.py` | `record_reasoning` / `record_tool_call` pro Tick |
| `engine/db.py` | `turn_log.tau`, `turn_log.pace`, `turn_log.model`, `agent_clocks` |
| `web/index.html` | "Time Dilation · Eigenzeit τ" Sektion + Drift-Indicator |
| `web/app.js` | `refreshClocks()`, `refreshDrift()` |

---

## LLM Provider

### Default: Ollama (lokal, **free**, 0 Tokens)

```ini
EMERGENCE_LLM_PROVIDER=ollama
EMERGENCE_OLLAMA_MODEL=llama3.2:3b
```

Vorteile:
- Komplett offline
- Keine API-Keys, keine Kosten
- Volle Kontrolle über Modelle
- Funktioniert auf Laptops ab 8 GB RAM

### Optional: OpenRouter (Cloud, kostenpflichtig)

```ini
EMERGENCE_LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=sk-or-v1-...
EMERGENCE_OPENROUTER_MODEL=anthropic/claude-3.5-haiku
```

Für "Mixed World" Experimente (verschiedene Modelle pro Agent), siehe [Time Dilation](#time-dilation-τ).

**Wichtig:** Nicht alle Free-Modelle auf OpenRouter unterstützen Tool-Calling. Funktionierende Modelle (Stand 06/2026):

| Modell | Tool-Use | Kosten (ca.) |
|--------|----------|--------------|
| `anthropic/claude-3.5-haiku` | ✓ | $0.80/$4 pro 1M Tokens |
| `openai/gpt-4o-mini` | ✓ | $0.15/$0.60 pro 1M |
| `meta-llama/llama-3.3-70b-instruct` | ✓ | $0.59/$0.79 pro 1M |
| `meta-llama/llama-3.2-3b-instruct:free` | ✗ | free |
| `qwen/qwen-2.5-7b-instruct:free` | ✗ | free |
| `google/gemma-3-4b-it:free` | ✗ | free |

Modelle ohne Tool-Use fallen automatisch auf die regelbasierte Engine zurück.

### Token-Spar-Design

| Stellschraube | Wert | Effekt |
|---------------|------|--------|
| System-Prompt | ~150 Tokens | kompakt, nicht-überladen |
| `max_tokens` (OR) | 256 | reicht für Tool-Calls, kein Spuern |
| Tool-Beschreibungen | 3-8 Wörter | minimal |
| `ENABLED=0` | 0 LLM-Calls | komplett regelbasiert |
| `Ollama llama3.2:3b` | ~2 GB RAM | kleinstes Modell mit gutem Tool-Use |

**Kosten-Beispiel** (OpenRouter, claude-haiku, 4 Agenten × 24h):

```
~3.000 Tool-Calls/Tag  ×  ~150 Tokens/Call  =  ~450.000 Tokens
Bei $0.80/1M Input  =  $0.36/Tag  ≈  $11/Monat  (für 4 Agenten Dauerlauf)
```

Mit Ollama: **$0.00**, dafür lokale Hardware-Last (~2-4 GB RAM).

---

## Tests

```bash
python3 -m pytest tests/ -v          # 99 Tests, ~60s
python3 -m coverage run -m pytest    # Coverage-Report
python3 smoke_test.py                # End-to-End (regelbasiert, 50+ Checks)
```

### Test-Suiten

| Datei | Anzahl | Was |
|-------|--------|-----|
| `test_db.py` | 4 | Schema, world_state, log_event, WAL-Mode |
| `test_world.py` | 6 | Landmarks, Distance, Hearing-Range, Location-Detection |
| `test_agents.py` | 7 | Bootstrap, Personality, State-Updates |
| `test_tools.py` | 22 | Alle 15 Tools + Location-Gating + Fehler-Pfade |
| `test_governance.py` | 11 | 70%-Threshold, Auto-Reject, Constitution-Amendment |
| `test_reasoning.py` | 6 | Rule-Path, Edge-Cases, Engine-Loop |
| `test_time.py` | 14 | τ, Pace-EWMA, γ-Transformation, Drift-Detection |
| `test_llm.py` | 15 | Ollama + OpenRouter, Schema, Mock-Decisions, Fallbacks |
| `test_api.py` | 14 | Alle HTTP-Endpoints + WebSocket + POST /api/turn |

**Total: 99 Tests, alle grün.**

### Bekannte Test-Lücken

- Keine Concurrency-Tests (parallele force_turn-Calls)
- Keine Last-Tests (>1000 Ticks in kurzer Zeit)
- Keine Fuzz-Tests für Tool-Args
- Keine Frontend-Tests (Canvas-Renderer ungetestet)
- Live-LLM-Tests (Ollama/OpenRouter) NICHT in pytest — siehe `smoke_test_llm.py` für manuelles Live-Testing

---

## Security

Emergence-Mini ist ein **lokales Dev-Tool**. Der Server bindet auf `127.0.0.1:8080`, nicht `0.0.0.0`.

### Bewusst NICHT enthalten

- **Keine Authentifizierung** — alle Endpoints offen
- **Keine Rate-Limits** — `POST /api/turn/{id}` ungedrosselt
- **Keine Input-Validierung** für Tool-Args (kann zu Crashes führen)
- **Keine CORS-Restriktionen** — bei Public-Exposure sofort offen
- **Keine Secrets im Code** — API-Keys ausschließlich in `.env` (git-ignored)

### Secret-Handling

```bash
# .env wird automatisch geladen, ist git-ignored, niemals committed.
cat .gitignore
# ... .env  ✓ blockiert
# ... .env.local  ✓
# ... *.key, *.pem  ✓
```

### Vor Public Deploy

- Reverse-Proxy mit Auth (Caddy + Basic-Auth)
- Schema-Validierung pro Tool-Endpoint
- Rate-Limiting (slowapi)
- CORS-Whitelist
- HTTPS terminieren
- DB-Backups automatisieren

---

## Was fehlt gegenüber dem Original

Emergence-World ist ein 15-Tage-Multi-Agent-Forschungsprojekt mit 4 Welten, 10 Agenten, 120+ Tools, React-Three-Fiber-Frontend, PostgreSQL, AWI-Metrics. Emergence-Mini ist eine **komprimierte Lern-Version**. Was bewusst weggelassen wurde:

| Feature | Original | Mini | Begründung |
|---------|----------|-----|------------|
| 3D-Frontend | React Three Fiber | 2D-Canvas | Aufwand 1 Tag → 1h |
| Datenbank | PostgreSQL 15+ | SQLite | reicht für 4 Agenten |
| Anzahl Tools | 120+ | 15 | die wichtigsten |
| Anzahl Agenten | 10 | 4 | Demo-tauglich |
| Anzahl Landmarks | 38+ | 14 | reicht für Time-Dilation-Test |
| AWI-Metrics | 9 Indikatoren | 0 | braucht 15-Tage-Daten |
| Multi-Model-Vergleich | ja (5 Welten) | ja (per-Agent) | Time-Dilation-Feature |
| Echtes NYC-Weather | ja | nein | braucht externe API |
| 15-Tage-Real-Time | ja | nein (2s/tick) | Demo-tempo |
| Vector-Memory | Qdrant | SQLite JSON | reicht für Demo |
| Heartbeat / Dream-Cycle | asynchron | sequenziell | komplexität |

**Was wir aber haben, was das Original nicht hat:** Time-Dilation-Tracking mit Causal-Dilation-Clock ist in der Original-Doku nur konzeptionell — bei uns läuft es produktiv.

---

## Lizenz

MIT für nicht-kommerzielle Nutzung, ohne Gewähr.

Inspiriert von [Emergence AI's Emergence-World](https://github.com/EmergenceAI/Emergence-World) (CC-BY-NC-4.0).

LLM-Modelle unterliegen ihren eigenen Lizenzen — bitte vor kommerzieller Nutzung prüfen.

---

## Maintainer

Jeuners · https://github.com/Jeuners/emergence-mini-dilles
