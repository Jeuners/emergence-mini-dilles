"""DB layer tests: schema, world_state, log_event."""
import json
import time


def test_init_db_creates_schema(tmp_db):
    import sqlite3
    c = sqlite3.connect(str(tmp_db))
    tables = {r[0] for r in c.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    expected = {"world_state", "agents", "landmarks", "memories",
                "relationships", "events", "proposals", "votes",
                "bills", "constitution", "turn_log"}
    assert expected.issubset(tables), f"missing tables: {expected - tables}"
    c.close()


def test_world_state_roundtrip(tmp_db):
    from engine import db
    assert db.get_world_state("nope", "default") == "default"
    db.set_world_state("foo", {"a": 1, "b": [1, 2, 3]})
    assert db.get_world_state("foo") == {"a": 1, "b": [1, 2, 3]}
    db.set_world_state("foo", "string")
    assert db.get_world_state("foo") == "string"


def test_log_event(tmp_db):
    from engine import db
    import sqlite3
    db.log_event("actor1", "test_kind", {"key": "value"})
    c = sqlite3.connect(str(tmp_db))
    c.row_factory = sqlite3.Row
    n = c.execute("SELECT COUNT(*) FROM events WHERE kind='test_kind'").fetchone()[0]
    assert n == 1
    row = c.execute("SELECT * FROM events WHERE kind='test_kind'").fetchone()
    payload = json.loads(row["payload"])
    assert payload == {"key": "value"}
    assert row["actor"] == "actor1"
    c.close()


def test_db_wal_mode(tmp_db):
    import sqlite3
    c = sqlite3.connect(str(tmp_db))
    mode = c.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    c.close()
