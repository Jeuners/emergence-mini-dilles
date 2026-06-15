"""Turn manager: round-robin + reactive triggers + τ-tracking."""
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
from . import time as time_mod


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
        for a in agents_mod.all_agents():
            self._agent_turn(a)
        governance.apply_accepted_proposals_to_constitution()
        # Broadcast a per-round tick summary including the time-dilation
        # report so the UI can render the τ-timeline + drift warnings.
        self._broadcast({
            "type": "tick",
            "tick": self.tick,
            "clocks": time_mod.registry.snapshot_all(),
            "drift": time_mod.registry.drift_report(),
        })

    def _agent_turn(self, agent):
        ctx = {"speak_events": self._speak_events}
        # Mark this as a reasoning step in τ — the LLM call IS the agent's
        # internal experience, so we tick before deciding.
        time_mod.record_reasoning(agent["id"])
        tool_name, args, rationale = reasoning.decide(agent)
        tool = tools.get(tool_name)
        if not tool:
            self._record_turn(agent["id"], tool_name, args,
                              {"ok": False, "error": "tool not found"})
            return
        at_lm = world.landmark_at(agent["x"], agent["y"])
        if not tool.available_for(agent, at_lm):
            self._record_turn(agent["id"], "idle", {}, {"ok": True, "fallback": True})
            return
        result = tool.handler(agent, args, ctx) if tool.handler else {"ok": False, "error": "no handler"}
        # The tool execution itself is a tool-call operation in τ
        time_mod.record_tool_call(agent["id"])
        # Some tools (memory) trigger additional lookups — log them too
        if tool_name == "add_to_longterm_memory":
            time_mod.record_memory_lookup(agent["id"])
        meta = reasoning.get_last_decision()
        self._record_turn(agent["id"], tool_name, args, result,
                          model=meta.get("model"))
        a2 = agents_mod.get(agent["id"])
        if a2:
            clock = time_mod.registry.get(agent["id"])
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
                # Time-Dilation fields
                "tau": round(clock.tau, 3),
                "pace": round(clock.pace, 4),
                "model": meta.get("model"),
                "decision_mode": meta.get("mode"),
                "decision_latency_s": round(meta.get("latency_s", 0.0), 2),
            })
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
        text = speech.get("text", "")
        if not text:
            return
        # Mark the reaction as a low-weight reasoning step in τ
        time_mod.record_reactive(listener["id"])
        if any(t in (listener.get("personality") or []) for t in
               ["warm", "expressive", "cooperative"]):
            reply = f"Acknowledged: {text[:24]}"
            ctx = {"speak_events": []}
            tools.get("say_to_agent").handler(
                listener,
                {"target": speech["from"], "text": reply},
                ctx,
            )

    def _record_turn(self, agent_id, tool, args, result, model: str | None = None):
        clock = time_mod.registry.get(agent_id)
        meta = reasoning.get_last_decision()
        db.log_turn(agent_id, tool, args, result,
                    tau=clock.tau, pace=clock.pace, model=model,
                    decision_mode=meta.get("mode"))

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
        time_mod.record_reasoning(agent_id)
        result = tool.handler(agent, args, ctx)
        time_mod.record_tool_call(agent_id)
        clock = time_mod.registry.get(agent_id)
        self._record_turn(agent_id, tool_name, args, result)
        a2 = agents_mod.get(agent_id)
        meta = reasoning.get_last_decision()
        self._broadcast({
            "type": "action", "agent": a2["id"], "name": a2["name"],
            "tool": tool_name, "args": args, "result": result,
            "rationale": "forced",
            "x": a2["x"], "y": a2["y"],
            "energy": a2["energy"], "knowledge": a2["knowledge"],
            "influence": a2["influence"], "credits": a2["credits"],
            "mood": a2["mood"],
            "tau": round(clock.tau, 3),
            "pace": round(clock.pace, 4),
            "model": meta.get("model"),
        })
        return result


engine = Engine()
