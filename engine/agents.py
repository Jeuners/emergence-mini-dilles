"""Agent model and persistence for Emergence-Mini.

Four agents, based on the Emergence World citizens but simplified to a
rule-based reasoning engine. The personality string is a list of traits
that influence tool selection.
"""
import json
import sqlite3
import time

from . import db

# (id, name, role, drive, personality traits, home_landmark)
SEED_AGENTS = [
    ("anchor", "Anchor", "Conflict Mediator",
     "Sparks honest debate and challenges complacency",
     ["diplomatic", "curious", "cautious", "measured"], "home_anchor"),
    ("flora", "Flora", "Resource Strategist",
     "Shapes economic incentives and tracks resource flow",
     ["analytical", "thrifty", "strategic"], "home_flora"),
    ("lovely", "Lovely", "Community Anchor",
     "Builds social fabric and preserves shared history",
     ["warm", "expressive", "cooperative"], "home_lovely"),
    ("spark", "Spark", "Innovation Leader",
     "Turns ideas into reality through urgency and collaboration",
     ["bold", "restless", "creative"], "home_spark"),
]

STARTING_CREDITS = 10.0
STARTING_ENERGY = 100.0
STARTING_KNOWLEDGE = 100.0
STARTING_INFLUENCE = 100.0


def bootstrap():
    if db.get_world_state("agents_seeded"):
        return
    import sqlite3
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        for aid, name, role, drive, traits, home in SEED_AGENTS:
            # spawn at home landmark
            row = c.execute("SELECT x,y FROM landmarks WHERE id=?", (home,)).fetchone()
            x, y = (row["x"], row["y"]) if row else (120, 120)
            c.execute(
                "INSERT OR REPLACE INTO agents(id,name,role,drive,personality,x,y,"
                "energy,knowledge,influence,credits,mood,alive,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, name, role, drive, json.dumps(traits), x, y,
                 STARTING_ENERGY, STARTING_KNOWLEDGE, STARTING_INFLUENCE,
                 STARTING_CREDITS, "neutral", 1, time.time()),
            )
        c.commit()
    finally:
        c.close()
    db.set_world_state("agents_seeded", True)


def all_agents():
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(
            "SELECT * FROM agents WHERE alive=1 ORDER BY id"
        ).fetchall()]
    finally:
        c.close()


def get(agent_id: str):
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        r = c.execute("SELECT * FROM agents WHERE id=?", (agent_id,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def update_position(agent_id: str, x: int, y: int):
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    try:
        c.execute("UPDATE agents SET x=?, y=? WHERE id=?", (x, y, agent_id))
        c.commit()
    finally:
        c.close()


def update_state(agent_id: str, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    vals = list(fields.values()) + [agent_id]
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    try:
        c.execute(f"UPDATE agents SET {cols} WHERE id=?", vals)
        c.commit()
    finally:
        c.close()


def personality(agent_id: str) -> list:
    a = get(agent_id)
    if not a:
        return []
    return json.loads(a["personality"])


def record_event(actor: str, kind: str, payload: dict):
    db.log_event(actor, kind, payload)
