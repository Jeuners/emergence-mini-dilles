"""Turn manager: round-robin + reactive triggers."""
import json
import time
import threading
import queue

from . import agents as agents_mod
from . import needs
from . import tools
from . import world
from . import reasoning
from . import governance
from . import db


class Engine:
    """Holds the simulation loop and a state-change broadcast queue."""

    def __init__(self):
        self.tick = 0
        self.broadcasts: "queue.Queue[dict]" = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._speak_events: list[dict] = []

    # -------- Loop control --------

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    # -------- Main loop --------

    def _run(self):
        tools.bootstrap()
        while not self._stop.is_set():
            self._one_round()
            time.sleep(2.0)  # 2s per tick

    def _one_round(self):
        self.tick += 1
        db.set_world_state("tick", self.tick)
        needs.tick_all_needs()
        # round-robin over live agents
        for a in agents_mod.all_agents():
            self._agent_turn(a)
        governance.apply_accepted_proposals_to_constitution()
        self._broadcast({"type": "tick", "tick": self.tick})

    def _agent_turn(self, agent):
        ctx = {"speak_events": self._speak_events}
        tool_name, args, rationale = reasoning.decide(agent)
        tool = tools.get(tool_name)
        if not tool:
            self._record_turn(agent["id"], tool_name, args,
                              {"ok": False, "error": "tool not found"})
            return
        at_lm = world.landmark_at(agent["x"], agent["y"])
        if not tool.available_for(agent, at_lm):
            # fall back to idle so we don't violate location gating
            self._record_turn(agent["id"], "idle", {}, {"ok": True, "fallback": True})
            return
        result = tool.handler(agent, args, ctx) if tool.handler else {"ok": False, "error": "no handler"}
        self._record_turn(agent["id"], tool_name, args, result)
        # refresh agent after possible state change
        a2 = agents_mod.get(agent["id"])
        if a2:
            self._broadcast({
                "type": "action",
                "agent": a2["id"],
                "name": a2["name"],
                "tool": tool_name,
                "args": args,
                "result": result,
                "rationale": rationale,
                "x": a2["x"], "y": a2["y"],
                "energy": a2["energy"], "knowledge": a2["knowledge"],
                "influence": a2["influence"], "credits": a2["credits"],
                "mood": a2["mood"],
            })
        # reactive triggers
        self._handle_reactive(a2 or agent)

    def _handle_reactive(self, speaker):
        events = list(self._speak_events)
        self._speak_events.clear()
        if not events:
            return
        for ev in events:
            if not ev.get("public") and ev.get("to") is None:
                continue
            nearby = world.nearby_agents(speaker["id"], ev["x"], ev["y"])
            for listener in nearby[:4]:
                self._reaction_turn(listener, ev)

    def _reaction_turn(self, listener, speech):
        # Lightweight: maybe respond with a short greeting or emoticon
        text = speech.get("text", "")
        if not text:
            return
        if any(t in listener["personality"] for t in ["warm", "expressive", "cooperative"]):
            reply = f"Acknowledged: {text[:24]}"
            ctx = {"speak_events": []}
            tools.get("say_to_agent").handler(
                listener,
                {"target": speech["from"], "text": reply},
                ctx,
            )

    def _record_turn(self, agent_id, tool, args, result):
        import sqlite3
        c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
        try:
            c.execute(
                "INSERT INTO turn_log(agent_id,tool,args,result,ts) VALUES(?,?,?,?,?)",
                (agent_id, tool, json.dumps(args), json.dumps(result), time.time()),
            )
            c.commit()
        finally:
            c.close()

    def _broadcast(self, message: dict):
        self.broadcasts.put(message)
        db.log_event("engine", message.get("type", "info"), message)

    # -------- Manual trigger (for tests / forced turns) --------

    def force_turn(self, agent_id: str, tool_name: str, args: dict):
        agent = agents_mod.get(agent_id)
        if not agent:
            return {"ok": False, "error": "no such agent"}
        tool = tools.get(tool_name)
        if not tool:
            return {"ok": False, "error": "no such tool"}
        ctx = {"speak_events": self._speak_events}
        result = tool.handler(agent, args, ctx)
        self._record_turn(agent_id, tool_name, args, result)
        a2 = agents_mod.get(agent_id)
        self._broadcast({
            "type": "action", "agent": a2["id"], "name": a2["name"],
            "tool": tool_name, "args": args, "result": result,
            "rationale": "forced",
            "x": a2["x"], "y": a2["y"],
            "energy": a2["energy"], "knowledge": a2["knowledge"],
            "influence": a2["influence"], "credits": a2["credits"],
            "mood": a2["mood"],
        })
        return result


engine = Engine()
