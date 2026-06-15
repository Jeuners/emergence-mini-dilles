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

from engine import db, world, agents as agents_mod, governance, tools
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
    return {
        "tick": db.get_world_state("tick", 0),
        "started_at": db.get_world_state("started_at"),
        "grid": {"w": world.GRID_W, "h": world.GRID_H},
        "agents": agents_mod.all_agents(),
        "landmarks": world.list_landmarks(),
        "constitution": governance.load_constitution(),
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
