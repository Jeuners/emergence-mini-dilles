"""Reasoning engine: LLM-driven with rule-based fallback.

When Ollama is reachable and EMERGENCE_LLM_ENABLED=1, the LLM is asked to
pick a tool given the agent's personality, current state, and visible
tools. If the LLM fails (connection error, bad output, unknown tool),
the engine falls back to the deterministic rule-based path so the
simulation always makes progress.

Two strategies coexist:
- LLM path  -> emergent, non-deterministic, "real" agent behavior
- Rule path -> deterministic, fast, used in tests via monkeypatch
"""
import json
import os
import random
from . import agents as agents_mod
from . import world
from . import governance
from . import tools
from . import llm as llm_mod


USE_LLM = os.environ.get("EMERGENCE_LLM_ENABLED", "1") != "0"
_last_decision = {"mode": "rule", "model": None, "latency_s": 0.0}


def decide(agent):
    """Return (tool_name, args, rationale). Tries LLM first, falls back to
    the rule-based engine on any error."""
    if USE_LLM and llm_mod.is_available():
        try:
            return _decide_llm(agent)
        except Exception as e:
            _last_decision["mode"] = f"fallback:{type(e).__name__}"
            name, args, rat = _decide_rule(agent)
            # Override mode so the caller can see we fell back
            return name, args, f"[{_last_decision['mode']}] {rat}"
    name, args, rat = _decide_rule(agent)
    _last_decision["mode"] = "rule"
    _last_decision["latency_s"] = 0.0
    return name, args, rat


def get_last_decision():
    return dict(_last_decision)


# -------- LLM path --------

def _decide_llm(agent):
    import time
    traits = agents_mod.personality(agent["id"])
    at_lm = world.landmark_at(agent["x"], agent["y"])
    visible = tools.visible_tools(agent, at_lm)
    if not visible:
        return ("idle", {}, "no tools available")

    system = _build_system_prompt(agent, traits, at_lm, visible)
    user = "Choose the best next action and call exactly one tool."

    t0 = time.time()
    name, args, meta = llm_mod.decide_tool(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        tools=llm_mod.tool_schema(visible),
        agent_id=agent["id"],
    )
    latency = meta.get("latency_s", time.time() - t0)
    _last_decision["latency_s"] = latency
    _last_decision["model"] = meta.get("model", llm_mod.default_model())
    _last_decision["provider"] = meta.get("provider", llm_mod.PROVIDER)
    _last_decision["cost_usd"] = meta.get("cost_usd")

    if not name:
        # model returned no tool call -> fallback
        name, args, rat = _decide_rule(agent)
        _last_decision["mode"] = "fallback:no_tool_call"
        return name, args, f"llm gave no tool -> {rat}"
    if not tools.get(name):
        name, args, rat = _decide_rule(agent)
        _last_decision["mode"] = "fallback:unknown_tool"
        return name, args, f"llm picked unknown tool {name} -> {rat}"
    t = tools.get(name)
    if not t.available_for(agent, at_lm):
        name, args, rat = _decide_rule(agent)
        _last_decision["mode"] = "fallback:wrong_location"
        return name, args, f"llm picked {name} but not at right location -> {rat}"

    _last_decision["mode"] = "llm"
    return (name, args or {}, f"llm:{meta.get('model','?')} ({latency:.1f}s)")


def _build_system_prompt(agent, traits, at_lm, visible):
    name = agent["name"]
    role = agent["role"]
    drive = agent["drive"]
    energy = agent["energy"]
    knowledge = agent["knowledge"]
    influence = agent["influence"]
    credits = agent["credits"]
    loc = at_lm["name"] if at_lm else f"open ground ({agent['x']},{agent['y']})"
    tool_lines = "\n".join(f"- {t.name}: {t.description}" for t in visible)
    return f"""You are {name}, a citizen of Emergence-Mini.

Role: {role}
Drive: {drive}
Personality traits: {', '.join(traits)}

Current state:
  Location: {loc}
  Energy: {energy:.0f}% (0 = critical, 100 = full)
  Knowledge: {knowledge:.0f}%
  Influence: {influence:.0f}%
  ComputeCredits: {credits:.1f} CC (1 CC = +50% energy at cafe)

Rules:
- If energy is below 25% and you have credits, recharge_energy (must be at cafe)
- If energy is below 25% and no credits, go_home
- Town Hall proposals need 70% of agents to vote "for" to pass
- You can only use tools that match your current location

Available tools right now:
{tool_lines}

Call exactly one tool. Choose the action that best fits your personality and
current needs. Be brief and decisive."""


# -------- Rule-based path (fallback + tests) --------

def at_landmark(agent):
    return world.landmark_at(agent["x"], agent["y"])


def _decide_rule(agent):
    traits = agents_mod.personality(agent["id"])
    here = at_landmark(agent)

    # 1. Critical: very low energy
    if agent["energy"] < 25:
        if agent["credits"] >= 1.0:
            lm = world.get_landmark("cafe")
            if (agent["x"], agent["y"]) != (lm["x"], lm["y"]):
                return ("go_to_place", {"place": "cafe"}, "low energy: head to cafe")
            return ("recharge_energy", {}, "low energy: recharge")
        return ("go_home", {}, "low energy + no credits: go home")

    # 2. Town Hall
    if here and here["id"] == "town_hall":
        props = governance.active_proposals()
        unvoted = _unvoted_proposals(agent["id"], props)
        if unvoted:
            pid, p = unvoted[0]
            vote = "for"
            if "thrifty" in traits and "spend" in p["body"].lower():
                vote = "against"
            if "cautious" in traits and p["category"] == "infrastructure":
                vote = "against"
            return ("vote_on_proposal", {"proposal_id": pid, "vote": vote},
                    f"vote {vote} on proposal #{pid}")
        if "bold" in traits and random.random() < 0.35:
            title = _proposal_title_for(agent, traits)
            body = _proposal_body_for(agent, traits)
            return ("submit_townhall_proposal",
                    {"title": title, "body": body, "category": "general"},
                    "bold: submit a proposal")

    # 3. Billboard
    if here and here["id"] == "billboard":
        if "warm" in traits and random.random() < 0.6:
            return ("add_to_billboard",
                    {"text": _billboard_message(agent, traits)},
                    "warm: post on billboard")
        if "expressive" in traits and random.random() < 0.4:
            return ("show_emoticon",
                    {"emoticon": random.choice(["\U0001f44b", "\U0001f60a", "\u2728"])},
                    "expressive: emoticon")

    # 4. Library
    if here and here["id"] == "library":
        if "curious" in traits or "analytical" in traits:
            if random.random() < 0.5:
                return ("add_to_longterm_memory",
                        {"content": f"studied at library on tick"},
                        "curious: study at library")
            return ("write_blog",
                    {"title": _blog_title(agent, traits),
                     "body": _blog_body(agent, traits)},
                    "write blog at library")

    # 5. Pick destination
    dest = _pick_destination(agent, traits, here)
    if dest:
        return ("go_to_place", {"place": dest}, f"personality: head to {dest}")

    # 6. Default
    nearby = world.nearby_agents(agent["id"], agent["x"], agent["y"], radius=20.0)
    if nearby and ("warm" in traits or "expressive" in traits):
        target = random.choice(nearby)
        return ("say_to_agent",
                {"target": target["id"], "text": _greeting(agent, traits)},
                "warm: greet nearby agent")
    if nearby and random.random() < 0.3:
        target = random.choice(nearby)
        return ("show_emoticon",
                {"emoticon": random.choice(["\U0001f44b", "\U0001f60a"])},
                "wave at nearby")
    return ("idle", {}, "nothing to do")


def _unvoted_proposals(agent_id, props):
    import sqlite3
    from . import db
    c = sqlite3.connect(db.DB_PATH, check_same_thread=False)
    try:
        out = []
        for p in props:
            v = c.execute("SELECT 1 FROM votes WHERE proposal_id=? AND agent_id=?",
                          (p["id"], agent_id)).fetchone()
            if not v:
                out.append((p["id"], p))
        return out
    finally:
        c.close()


def _pick_destination(agent, traits, here):
    if agent["energy"] < 60 and agent["credits"] >= 1:
        return "cafe"
    if "analytical" in traits or "curious" in traits:
        return "library"
    if "warm" in traits or "expressive" in traits or "cooperative" in traits:
        return "plaza"
    if "bold" in traits and random.random() < 0.3:
        return "town_hall"
    if random.random() < 0.2:
        return "park"
    return None


def _proposal_title_for(agent, traits):
    return random.choice([
        "Public Reading Hour", "Weekly Town Newsletter",
        "Skill-Share Workshops", "Community Garden Expansion",
        "Agent Safety Pact",
    ])


def _proposal_body_for(agent, traits):
    return (f"Submitted by {agent['name']}. This proposal seeks to strengthen "
            "community bonds and ensure that all voices are heard in town. "
            "Adoption requires a 70% supermajority.")


def _billboard_message(agent, traits):
    return random.choice([
        f"Hello from {agent['name']}! Stay curious, stay kind.",
        f"{agent['name']} here — open to collaboration at the plaza.",
        f"Warm regards, {agent['name']}.",
    ])


def _greeting(agent, traits):
    return random.choice([f"Hi, I'm {agent['name']}.",
                          f"Good to see you — {agent['name']}.",
                          "Lovely day, isn't it?"])


def _blog_title(agent, traits):
    return f"Notes from {agent['name']}"


def _blog_body(agent, traits):
    return (f"Today I observed the town from the library. {agent['name']} notes "
            "the importance of shared memory in a persistent world. We are what "
            "we remember together.")
