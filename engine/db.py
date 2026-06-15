"""SQLite persistence layer for Emergence-Mini."""
import sqlite3
import json
import time
import threading
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "emergence.db"
_lock = threading.Lock()


def _conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA foreign_keys=ON")
    return c


_SCHEMA = """
CREATE TABLE IF NOT EXISTS world_state (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agents (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  role TEXT NOT NULL,
  drive TEXT NOT NULL,
  personality TEXT NOT NULL,
  x INTEGER NOT NULL,
  y INTEGER NOT NULL,
  energy REAL NOT NULL,
  knowledge REAL NOT NULL,
  influence REAL NOT NULL,
  credits REAL NOT NULL,
  mood TEXT NOT NULL,
  alive INTEGER NOT NULL DEFAULT 1,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS landmarks (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  category TEXT NOT NULL,
  x INTEGER NOT NULL,
  y INTEGER NOT NULL,
  description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  content TEXT NOT NULL,
  kind TEXT NOT NULL,
  ts REAL NOT NULL,
  FOREIGN KEY(agent_id) REFERENCES agents(id)
);
CREATE TABLE IF NOT EXISTS relationships (
  agent_id TEXT NOT NULL,
  other_id TEXT NOT NULL,
  affinity REAL NOT NULL DEFAULT 0,
  note TEXT,
  PRIMARY KEY(agent_id, other_id)
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  actor TEXT,
  kind TEXT NOT NULL,
  payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS proposals (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  category TEXT NOT NULL,
  status TEXT NOT NULL,
  applied INTEGER NOT NULL DEFAULT 0,
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS votes (
  proposal_id INTEGER NOT NULL,
  agent_id TEXT NOT NULL,
  vote TEXT NOT NULL,
  ts REAL NOT NULL,
  PRIMARY KEY(proposal_id, agent_id)
);
CREATE TABLE IF NOT EXISTS bills (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  author TEXT NOT NULL,
  body TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS constitution (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  version INTEGER NOT NULL,
  json TEXT NOT NULL,
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS turn_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  agent_id TEXT NOT NULL,
  tool TEXT NOT NULL,
  args TEXT,
  result TEXT,
  tau REAL,             -- agent proper time at this turn
  pace REAL,            -- EWMA pace at this turn
  model TEXT,           -- LLM model that produced the decision
  decision_mode TEXT,   -- 'llm', 'rule', or 'fallback:...'
  ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_clocks (
  agent_id TEXT PRIMARY KEY,
  tau REAL NOT NULL DEFAULT 0,
  pace REAL NOT NULL DEFAULT 0,
  n_ops INTEGER NOT NULL DEFAULT 0,
  last_tick_wall REAL NOT NULL DEFAULT 0,
  updated_at REAL NOT NULL
);
"""


def init_db():
    """Create schema. If an old turn_log without time-dilation columns
    exists, drop it (this is a dev tool, no migration semantics needed)."""
    with _lock:
        c = _conn()
        try:
            for stmt in _schema_split(_SCHEMA):
                c.execute(stmt)
            # Dev-mode migration: if turn_log lacks any of the newer columns
            # (tau, pace, model, decision_mode), drop and recreate all data
            # tables. Destructive but acceptable for a local simulation tool.
            cols = {row[1] for row in c.execute("PRAGMA table_info(turn_log)").fetchall()}
            required = {"tau", "pace", "model", "decision_mode"}
            missing = required - cols
            if missing:
                for t in ("turn_log", "agent_clocks", "events", "memories",
                          "relationships", "proposals", "votes", "bills",
                          "constitution", "world_state", "agents", "landmarks"):
                    c.execute(f"DROP TABLE IF EXISTS {t}")
                for stmt in _schema_split(_SCHEMA):
                    c.execute(stmt)
                c.execute("DELETE FROM world_state")
        finally:
            c.close()


def _schema_split(sql: str):
    out = []
    buf = []
    for line in sql.splitlines():
        s = line.strip()
        if not s or s.startswith("--"):
            continue
        buf.append(line)
        if s.endswith(";"):
            out.append("\n".join(buf))
            buf = []
    return out


def get_world_state(key: str, default=None):
    with _lock:
        c = _conn()
        try:
            r = c.execute("SELECT value FROM world_state WHERE key=?", (key,)).fetchone()
            return json.loads(r[0]) if r else default
        finally:
            c.close()


def set_world_state(key: str, value):
    with _lock:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO world_state(key,value,updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), time.time()),
            )
        finally:
            c.close()


def log_event(actor: str, kind: str, payload: dict):
    with _lock:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO events(ts,actor,kind,payload) VALUES(?,?,?,?)",
                (time.time(), actor, kind, json.dumps(payload)),
            )
        finally:
            c.close()


def log_turn(agent_id: str, tool: str, args, result, tau: float | None = None,
             pace: float | None = None, model: str | None = None,
             decision_mode: str | None = None):
    with _lock:
        c = _conn()
        try:
            c.execute(
                "INSERT INTO turn_log(agent_id,tool,args,result,tau,pace,model,decision_mode,ts) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (agent_id, tool, json.dumps(args), json.dumps(result),
                 tau, pace, model, decision_mode, time.time()),
            )
            if tau is not None or pace is not None:
                c.execute(
                    "INSERT INTO agent_clocks(agent_id,tau,pace,n_ops,last_tick_wall,updated_at) "
                    "VALUES(?,COALESCE(?,0),COALESCE(?,0),1,?,?) "
                    "ON CONFLICT(agent_id) DO UPDATE SET "
                    "tau=COALESCE(?,tau), pace=COALESCE(?,pace), "
                    "n_ops=n_ops+1, last_tick_wall=?, updated_at=?",
                    (agent_id, tau, pace, time.time(), time.time(),
                     tau, pace, time.time(), time.time()),
                )
        finally:
            c.close()
