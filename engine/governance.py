"""Constitution + Town Hall proposal lifecycle."""
import json
import sqlite3
import time
from pathlib import Path

from . import db

PASS_THRESHOLD = 0.7  # 70%


def load_constitution():
    """Load constitution. Prefer the latest saved version from the DB; fall
    back to the seed JSON file on disk."""
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        r = c.execute(
            "SELECT json FROM constitution ORDER BY version DESC LIMIT 1"
        ).fetchone()
        if r:
            return json.loads(r["json"])
    finally:
        c.close()
    path = Path(__file__).resolve().parent.parent / "data" / "constitution.json"
    return json.loads(path.read_text())


def save_constitution(c: dict):
    con = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    try:
        version = con.execute("SELECT COALESCE(MAX(version),0)+1 AS v FROM constitution").fetchone()[0]
        con.execute("INSERT INTO constitution(version,json,ts) VALUES(?,?,?)",
                    (version, json.dumps(c), time.time()))
        con.commit()
        return version
    finally:
        con.close()


def active_proposals():
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT p.*, COUNT(v.agent_id) AS votes "
            "FROM proposals p LEFT JOIN votes v ON v.proposal_id=p.id "
            "WHERE p.status='active' GROUP BY p.id ORDER BY p.id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        c.close()


def all_proposals():
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(
            "SELECT * FROM proposals ORDER BY id DESC LIMIT 50"
        ).fetchall()]
    finally:
        c.close()


def live_agent_count() -> int:
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    try:
        return c.execute("SELECT COUNT(*) FROM agents WHERE alive=1").fetchone()[0]
    finally:
        c.close()


def vote_counts(proposal_id: int):
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    try:
        f = c.execute("SELECT COUNT(*) FROM votes WHERE proposal_id=? AND vote='for'",
                      (proposal_id,)).fetchone()[0]
        a = c.execute("SELECT COUNT(*) FROM votes WHERE proposal_id=? AND vote='against'",
                      (proposal_id,)).fetchone()[0]
        return f, a
    finally:
        c.close()


def maybe_close_proposal(proposal_id: int):
    """If all live agents have voted, or threshold is unreachable, close the proposal."""
    total_live = live_agent_count()
    f, a = vote_counts(proposal_id)
    cast = f + a
    remaining = total_live - cast
    if cast < total_live:
        # threshold unreachable?
        if (f + remaining) < int(total_live * PASS_THRESHOLD) + 1:
            _close(proposal_id, "rejected")
            return {"status": "rejected", "reason": "threshold unreachable"}
        return {"status": "active", "for": f, "against": a, "remaining": remaining}
    # all voted
    pct = f / total_live if total_live else 0
    if pct >= PASS_THRESHOLD:
        _close(proposal_id, "accepted")
        return {"status": "accepted", "for": f, "against": a, "pct": pct}
    _close(proposal_id, "rejected")
    return {"status": "rejected", "for": f, "against": a, "pct": pct}


def _close(proposal_id: int, status: str):
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    try:
        c.execute("UPDATE proposals SET status=? WHERE id=?", (status, proposal_id))
        c.commit()
    finally:
        c.close()
    db.log_event("system", f"proposal_{status}", {"proposal_id": proposal_id})


def apply_accepted_proposals_to_constitution():
    """If a proposal is about amending the constitution and was accepted, apply it.

    For demo: any accepted proposal is logged. If the title begins with
    'Article' the article is appended to the current constitution and a
    new version is written.
    """
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        rows = c.execute(
            "SELECT * FROM proposals WHERE status='accepted' AND applied=0"
        ).fetchall()
    finally:
        c.close()
    if not rows:
        return []
    con = load_constitution()
    new_ids = []
    for r in rows:
        title = r["title"]
        body = r["body"]
        if title.lower().startswith("article"):
            next_id = max(a["id"] for a in con["articles"]) + 1
            con["articles"].append({"id": next_id, "title": title, "body": body})
            new_ids.append(next_id)
        # mark applied
        c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
        try:
            c.execute("UPDATE proposals SET applied=1 WHERE id=?", (r["id"],))
            c.commit()
        finally:
            c.close()
    if new_ids:
        save_constitution(con)
    return new_ids
