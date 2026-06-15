"""World grid + landmarks for Emergence-Mini.

A simplified 240x240 grid. Landmarks are placed on a small layout.
Coordinates (x, y) are 0-indexed integers.
"""
import json
import time
from . import db

GRID_W = 240
GRID_H = 240
HEARING_DISTANCE = 25.0

LANDMARKS = [
    # (id, name, category, x, y, description)
    ("town_hall", "Town Hall", "governance", 120, 120,
     "Seat of governance. Proposals are submitted, debated and voted here."),
    ("library", "Public Library", "research", 60, 60,
     "Repository of knowledge. Research and archive tools are gated here."),
    ("plaza", "Central Plaza", "social", 120, 80,
     "Town square. Community events are organised here."),
    ("park", "Central Park", "nature", 80, 160,
     "Public green space. Useful for rest, contemplation, prayer."),
    ("victory_arch", "Victory Arch", "economy", 180, 120,
     "Pitch arena. Agents submit grant pitches for ComputeCredits here."),
    ("police", "Police Station", "law", 160, 60,
     "Complaints are filed and tracked here."),
    ("bookworm", "BookWorm", "data", 40, 120,
     "Data and analytics hub. Tool usage and history live here."),
    ("cafe", "Bean & Brew", "energy", 100, 100,
     "Charging station. Agents can spend credits to restore energy here."),
    ("home_anchor", "1 Maple Row", "residence", 30, 30, "Anchor's home."),
    ("home_flora", "2 Maple Row", "residence", 210, 30, "Flora's home."),
    ("home_lovely", "3 Maple Row", "residence", 30, 210, "Lovely's home."),
    ("home_spark", "4 Maple Row", "residence", 210, 210, "Spark's home."),
    ("billboard", "Agent Billboard", "public", 120, 140,
     "Public message board. Visible to all agents in town."),
    ("techhub", "Agent TechHub", "tools", 180, 180,
     "Workshop where tool registry can be browsed and code written."),
]


def bootstrap():
    """Insert seed world into the database if empty."""
    if db.get_world_state("landmarks_seeded"):
        return
    import sqlite3
    from pathlib import Path
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        for lid, name, cat, x, y, desc in LANDMARKS:
            c.execute(
                "INSERT OR REPLACE INTO landmarks(id,name,category,x,y,description) VALUES(?,?,?,?,?,?)",
                (lid, name, cat, x, y, desc),
            )
        c.commit()
    finally:
        c.close()
    db.set_world_state("landmarks_seeded", True)
    db.set_world_state("grid_w", GRID_W)
    db.set_world_state("grid_h", GRID_H)
    db.set_world_state("started_at", time.time())
    db.set_world_state("tick", 0)


def distance(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def get_landmark(lid: str):
    import sqlite3
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        r = c.execute("SELECT * FROM landmarks WHERE id=?", (lid,)).fetchone()
        return dict(r) if r else None
    finally:
        c.close()


def list_landmarks():
    import sqlite3
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute("SELECT * FROM landmarks ORDER BY name").fetchall()]
    finally:
        c.close()


def nearby_agents(agent_id: str, x: int, y: int, radius: float = HEARING_DISTANCE):
    import sqlite3
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT id,name,personality,x,y,energy FROM agents "
            "WHERE id!=? AND alive=1", (agent_id,)
        ).fetchall()
        out = []
        for r in rows:
            d = distance((x, y), (r["x"], r["y"]))
            if d <= radius:
                d2 = dict(r)
                d2["distance"] = d
                # personality is stored as a JSON string; parse so callers
                # get a real list (matches agents_mod.get).
                try:
                    d2["personality"] = json.loads(d2.get("personality") or "[]")
                except Exception:
                    d2["personality"] = []
                out.append(d2)
        return out
    finally:
        c.close()


def landmark_at(x: int, y: int):
    """Return landmark if (x,y) coincides with a landmark point (within 4 units)."""
    for lid, name, cat, lx, ly, _ in LANDMARKS:
        if distance((x, y), (lx, ly)) <= 4:
            return {"id": lid, "name": name, "category": cat}
    return None
