"""FastAPI server for Emergence-Mini.

Endpoints:
- GET  /api/state        -> full world snapshot
- GET  /api/agents       -> list agents
- GET  /api/landmarks    -> list landmarks
- GET  /api/proposals    -> active + recent proposals
- GET  /api/constitution -> current constitution
- GET  /api/events       -> recent events (billboard, blog, etc.)
- GET  /api/memories/{agent_id} -> an agent's memories
- GET  /api/blogs        -> recent blog posts
- POST /api/turn/{agent_id}  -> force a tool call (manual control)
- WS   /ws               -> live state stream
- GET  /                 -> serves the SPA
"""
import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from engine import db, world, agents as agents_mod, governance, tools, llm as llm_mod
from engine.turn import engine as sim_engine

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"

app = FastAPI(title="Emergence-Mini", version="0.1.0")


def _bootstrap():
    db.init_db()
    world.bootstrap()
    agents_mod.bootstrap()
    tools.bootstrap()


@app.on_event("startup")
async def on_startup():
    _bootstrap()
    if not os.environ.get("EMERGENCE_TEST_MODE"):
        sim_engine.start()


@app.on_event("shutdown")
async def on_shutdown():
    sim_engine.stop()


# -------- Static / SPA --------

app.mount("/static", StaticFiles(directory=str(WEB)), name="static")


@app.get("/")
async def index():
    return FileResponse(str(WEB / "index.html"))


# -------- Helpers --------

def _query(sql: str, params=()):
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()


# -------- API --------

@app.get("/api/state")
async def state():
    from engine import time as time_mod
    return {
        "tick": db.get_world_state("tick", 0),
        "started_at": db.get_world_state("started_at"),
        "grid": {"w": world.GRID_W, "h": world.GRID_H},
        "agents": agents_mod.all_agents(),
        "landmarks": world.list_landmarks(),
        "constitution": governance.load_constitution(),
        "llm": llm_mod.provider_info(),
        "clocks": time_mod.registry.snapshot_all(),
        "drift": time_mod.registry.drift_report(),
    }


@app.get("/api/agents")
async def agents():
    return agents_mod.all_agents()


@app.get("/api/landmarks")
async def landmarks():
    return world.list_landmarks()


@app.get("/api/proposals")
async def proposals():
    return {
        "active": governance.active_proposals(),
        "recent": governance.all_proposals(),
    }


@app.get("/api/constitution")
async def constitution():
    return governance.load_constitution()


@app.get("/api/events")
async def events():
    return _query("SELECT * FROM events ORDER BY id DESC LIMIT 100")


@app.get("/api/memories/{agent_id}")
async def memories(agent_id: str):
    return _query(
        "SELECT * FROM memories WHERE agent_id=? ORDER BY id DESC LIMIT 50",
        (agent_id,),
    )


@app.get("/api/blogs")
async def blogs():
    rows = _query("SELECT * FROM bills ORDER BY id DESC LIMIT 50")
    out = []
    for r in rows:
        try:
            payload = json.loads(r["body"])
            out.append({"id": r["id"], "ts": r["ts"], **payload})
        except Exception:
            out.append({"id": r["id"], "ts": r["ts"], "title": "Untitled", "body": r["body"]})
    return out


@app.get("/api/texts")
async def texts(limit: int = 20):
    """Return recent texts produced by agents (blogs, billboards, speech,
    memories) with the model that produced them.

    Each row has: {agent, model, kind, body, ts, source}
    source: 'llm' (tool call from LLM) or 'fallback' (rule-based default)
    """
    import sqlite3
    out: list[dict] = []
    # blogs
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        for r in c.execute("SELECT * FROM bills ORDER BY id DESC LIMIT ?", (limit,)):
            try:
                p = json.loads(r["body"])
            except Exception:
                p = {"title": "Untitled", "body": str(r["body"])[:500]}
            tmodel = c.execute("SELECT model FROM turn_log WHERE agent_id=? AND tool='write_blog' ORDER BY id DESC LIMIT 1",
                              (r["author"],)).fetchone()
            out.append({
                "agent": r["author"],
                "model": tmodel["model"] if tmodel else "?",
                "kind": "blog",
                "body": (p.get("title", "") + " — " + p.get("body", ""))[:600],
                "ts": r["ts"],
                "source": "llm" if tmodel and tmodel["model"] else "fallback",
            })
        # billboard posts
        for r in c.execute("SELECT * FROM events WHERE kind='billboard_post' ORDER BY id DESC LIMIT ?", (limit,)):
            try:
                p = json.loads(r["payload"])
            except Exception:
                p = {"text": str(r["payload"])[:200]}
            tmodel = c.execute("SELECT model FROM turn_log WHERE agent_id=? AND tool='add_to_billboard' ORDER BY id DESC LIMIT 1",
                              (r["actor"],)).fetchone()
            out.append({
                "agent": r["actor"],
                "model": tmodel["model"] if tmodel else "?",
                "kind": "billboard",
                "body": p.get("text", "")[:400],
                "ts": r["ts"],
                "source": "llm" if tmodel and tmodel["model"] else "fallback",
            })
        # memories
        for r in c.execute("SELECT * FROM memories ORDER BY id DESC LIMIT ?", (limit,)):
            tmodel = c.execute("SELECT model FROM turn_log WHERE agent_id=? AND tool='add_to_longterm_memory' ORDER BY id DESC LIMIT 1",
                              (r["agent_id"],)).fetchone()
            out.append({
                "agent": r["agent_id"],
                "model": tmodel["model"] if tmodel else "?",
                "kind": "memory",
                "body": str(r["content"])[:400],
                "ts": r["ts"],
                "source": "llm" if tmodel and tmodel["model"] else "fallback",
            })
        # speak_to_all / say_to_agent (from turn_log args)
        for r in c.execute("SELECT * FROM turn_log WHERE tool IN ('speak_to_all','say_to_agent') ORDER BY id DESC LIMIT ?", (limit,)):
            try:
                a = json.loads(r["args"])
            except Exception:
                continue
            text = a.get("text", "")
            if not text:
                continue
            out.append({
                "agent": r["agent_id"],
                "model": r["model"] or "?",
                "kind": r["tool"].replace("_", " "),
                "body": text[:400],
                "ts": r["ts"],
                "source": "llm" if r["model"] and "/" in r["model"] else "llm",
            })
    finally:
        c.close()
    out.sort(key=lambda x: -x["ts"])
    return out[:limit]


@app.post("/api/turn/{agent_id}")
async def force_turn(agent_id: str, body: dict):
    tool_name = body.get("tool")
    args = body.get("args", {})
    if not tool_name:
        return JSONResponse({"ok": False, "error": "tool required"}, status_code=400)
    result = sim_engine.force_turn(agent_id, tool_name, args)
    # If a voting turn just closed a proposal, apply it to the constitution
    if tool_name == "vote_on_proposal":
        from engine import governance
        governance.apply_accepted_proposals_to_constitution()
    return result


# -------- WebSocket --------

@app.websocket("/ws")
async def ws(ws: WebSocket):
    await ws.accept()
    queue = sim_engine.broadcasts
    try:
        # initial snapshot
        await ws.send_json({"type": "snapshot", "data": await state()})
        while True:
            try:
                msg = await asyncio.to_thread(queue.get, timeout=30.0)
                await ws.send_json(msg)
            except WebSocketDisconnect:
                break
            except Exception:
                # client went away — stop sending
                break
    except WebSocketDisconnect:
        pass
