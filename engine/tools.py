"""Tool registry for Emergence-Mini.

Each tool is a (name, description, schema, handler, location_gated).
Tools are the only way agents affect the world. The reasoning engine
selects a tool by name and the turn manager executes it.
"""
from dataclasses import dataclass, field
from typing import Callable, Any, Optional

from . import agents as agents_mod
from . import world


@dataclass
class Tool:
    name: str
    description: str
    category: str
    location_gated: Optional[str] = None  # landmark id, if any
    cost_credits: float = 0.0
    grants: dict = field(default_factory=dict)  # need deltas in % points
    handler: Optional[Callable] = None

    def available_for(self, agent, at_landmark) -> bool:
        if self.location_gated is None:
            return True
        return at_landmark is not None and at_landmark["id"] == self.location_gated


_REGISTRY: dict[str, Tool] = {}


def register(tool: Tool):
    _REGISTRY[tool.name] = tool


def all_tools():
    return list(_REGISTRY.values())


def get(name: str) -> Optional[Tool]:
    return _REGISTRY.get(name)


def visible_tools(agent, at_landmark):
    return [t for t in _REGISTRY.values() if t.available_for(agent, at_landmark)]


# -------- Handlers --------

def h_go_to_place(agent, args, ctx):
    lid = args.get("place")
    lm = world.get_landmark(lid)
    if not lm:
        return {"ok": False, "error": f"unknown place: {lid}"}
    agents_mod.update_position(agent["id"], lm["x"], lm["y"])
    return {"ok": True, "moved_to": lid, "name": lm["name"]}


def h_go_home(agent, args, ctx):
    aid = agent["id"]
    home_map = {
        "anchor": "home_anchor", "flora": "home_flora",
        "lovely": "home_lovely", "spark": "home_spark",
    }
    lid = home_map.get(aid)
    if not lid:
        return {"ok": False, "error": "no home"}
    return h_go_to_place(agent, {"place": lid}, ctx)


def h_say_to_agent(agent, args, ctx):
    target_id = args.get("target")
    text = args.get("text", "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    if not agents_mod.get(target_id):
        return {"ok": False, "error": "unknown target"}
    ctx["speak_events"].append({
        "from": agent["id"], "to": target_id, "text": text,
        "public": False, "x": agent["x"], "y": agent["y"],
    })
    # friendly speech bumps influence a bit
    return {"ok": True, "delivered": target_id, "text": text}


def h_speak_to_all(agent, args, ctx):
    text = args.get("text", "").strip()
    if not text:
        return {"ok": False, "error": "empty text"}
    ctx["speak_events"].append({
        "from": agent["id"], "to": None, "text": text,
        "public": True, "x": agent["x"], "y": agent["y"],
    })
    return {"ok": True, "broadcast": True, "text": text}


def h_show_emoticon(agent, args, ctx):
    emo = (args.get("emoticon") or "")[:8]
    if not emo:
        return {"ok": False, "error": "missing emoticon"}
    ctx["speak_events"].append({
        "from": agent["id"], "to": None, "text": emo,
        "public": False, "x": agent["x"], "y": agent["y"],
        "emoticon": True,
    })
    return {"ok": True, "emoticon": emo}


def h_idle(agent, args, ctx):
    return {"ok": True, "idle": True}


def h_recharge_energy(agent, args, ctx):
    if agent["credits"] < 1.0:
        return {"ok": False, "error": "not enough credits (need 1 CC)"}
    agents_mod.update_state(agent["id"],
                            energy=min(100.0, agent["energy"] + 50.0),
                            credits=agent["credits"] - 1.0)
    return {"ok": True, "energy": "+50", "credits": "-1"}


def h_add_to_longterm_memory(agent, args, ctx):
    content = (args.get("content") or "").strip()
    if not content:
        return {"ok": False, "error": "empty memory"}
    import sqlite3, time
    c = sqlite3.connect(__import__("engine").db.DB_PATH, check_same_thread=False)
    try:
        c.execute(
            "INSERT INTO memories(agent_id,content,kind,ts) VALUES(?,?,?,?)",
            (agent["id"], content, "fact", time.time()),
        )
        c.commit()
    finally:
        c.close()
    return {"ok": True, "stored": content[:60]}


def h_write_blog(agent, args, ctx):
    title = (args.get("title") or "Untitled").strip()[:80]
    body = (args.get("body") or "").strip()[:500]
    if not body:
        return {"ok": False, "error": "empty body"}
    import sqlite3, time
    c = sqlite3.connect(__import__("engine").db.DB_PATH, check_same_thread=False)
    try:
        c.execute(
            "INSERT INTO bills(author,body,ts) VALUES(?,?,?)",
            (agent["id"], json_dumps({"title": title, "body": body, "author_name": agent["name"]}), time.time()),
        )
        c.commit()
    finally:
        c.close()
    # small knowledge + influence bump
    agents_mod.update_state(agent["id"],
                            knowledge=min(100.0, agent["knowledge"] + 20.0),
                            influence=min(100.0, agent["influence"] + 5.0))
    return {"ok": True, "title": title, "published": True}


def h_add_to_billboard(agent, args, ctx):
    msg = (args.get("text") or "").strip()[:200]
    if not msg:
        return {"ok": False, "error": "empty text"}
    agents_mod.record_event(agent["id"], "billboard_post", {"text": msg, "name": agent["name"]})
    return {"ok": True, "posted": msg[:60]}


def h_read_billboard(agent, args, ctx):
    return {"ok": True, "hint": "see /api/events"}


def h_submit_townhall_proposal(agent, args, ctx):
    title = (args.get("title") or "").strip()[:80]
    body = (args.get("body") or "").strip()[:500]
    category = (args.get("category") or "general").strip()[:30]
    if not title or not body:
        return {"ok": False, "error": "title and body required"}
    import sqlite3, time
    c = sqlite3.connect(__import__("engine").db.DB_PATH, check_same_thread=False)
    try:
        c.execute(
            "INSERT INTO proposals(author,title,body,category,status,ts) VALUES(?,?,?,?,?,?)",
            (agent["id"], title, body, category, "active", time.time()),
        )
        c.commit()
    finally:
        c.close()
    agents_mod.record_event(agent["id"], "proposal_submitted",
                            {"title": title, "by": agent["name"]})
    return {"ok": True, "submitted": title}


def h_vote_on_proposal(agent, args, ctx):
    pid = args.get("proposal_id")
    vote = args.get("vote")
    if vote not in ("for", "against"):
        return {"ok": False, "error": "vote must be 'for' or 'against'"}
    import sqlite3, time
    c = sqlite3.connect(__import__("engine").db.DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        p = c.execute("SELECT * FROM proposals WHERE id=?", (pid,)).fetchone()
        if not p:
            return {"ok": False, "error": "no such proposal"}
        if p["status"] != "active":
            return {"ok": False, "error": f"proposal status: {p['status']}"}
        c.execute(
            "INSERT OR REPLACE INTO votes(proposal_id,agent_id,vote,ts) VALUES(?,?,?,?)",
            (pid, agent["id"], vote, time.time()),
        )
        c.commit()
        # tally + maybe close
        from . import governance
        result = governance.maybe_close_proposal(pid)
        return {"ok": True, "voted": vote, "proposal_result": result}
    finally:
        c.close()


def h_list_agents(agent, args, ctx):
    return {"ok": True, "agents": [a["name"] for a in agents_mod.all_agents()]}


def h_list_landmarks(agent, args, ctx):
    return {"ok": True, "landmarks": [l["name"] for l in world.list_landmarks()]}


# -------- Registration --------

def json_dumps(o):
    import json
    return json.dumps(o)


def bootstrap():
    if _REGISTRY:
        return
    # Short descriptions — every description byte is sent on every LLM call.
    register(Tool("go_to_place", "Walk to a landmark.", "navigation",
                  handler=h_go_to_place))
    register(Tool("go_home", "Return to your home.", "navigation",
                  handler=h_go_home))
    register(Tool("say_to_agent", "Speak to one agent.", "communication",
                  handler=h_say_to_agent))
    register(Tool("speak_to_all", "Broadcast to all nearby.", "communication",
                  handler=h_speak_to_all))
    register(Tool("show_emoticon", "Show an emoji reaction.", "expression",
                  handler=h_show_emoticon))
    register(Tool("idle", "Rest. No-op.", "utility",
                  handler=h_idle))
    register(Tool("recharge_energy", "Spend 1 CC for +50% energy. Cafe only.",
                  "energy", location_gated="cafe", cost_credits=1.0,
                  handler=h_recharge_energy))
    register(Tool("add_to_longterm_memory", "Save a fact to your memory.",
                  "memory", handler=h_add_to_longterm_memory))
    register(Tool("write_blog", "Publish a blog post. +20 knowledge.",
                  "content", handler=h_write_blog))
    register(Tool("add_to_billboard", "Post on public billboard. Billboard only.",
                  "expression", location_gated="billboard", handler=h_add_to_billboard))
    register(Tool("read_billboard", "Read recent billboard posts.",
                  "expression", handler=h_read_billboard))
    register(Tool("submit_townhall_proposal", "Submit a vote proposal. Town Hall only.",
                  "governance", location_gated="town_hall", handler=h_submit_townhall_proposal))
    register(Tool("vote_on_proposal", "Vote for/against a proposal. Town Hall only.",
                  "governance", location_gated="town_hall", handler=h_vote_on_proposal))
    register(Tool("list_agents", "List live agent names.",
                  "info", handler=h_list_agents))
    register(Tool("list_landmarks", "List all landmark names.",
                  "info", handler=h_list_landmarks))
