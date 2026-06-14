"""Rule-based reasoning engine.

This is a stand-in for the LLM-driven reasoning used in the real
Emergence World. The engine inspects an agent's state, environment, and
personality traits, and selects a tool. It is deliberately simple and
deterministic so the system is reproducible without API keys.

Personality traits influence tool selection:
- analytical -> library, write_blog
- thrifty    -> avoid recharge_energy unless energy < 30
- warm       -> speak_to_all, say_to_agent, show_emoticon
- bold       -> submit_townhall_proposal
- diplomatic -> vote 'for' on most proposals, except when thrifty
- strategic  -> go_to_place(landmark) based on need
- creative   -> write_blog
- curious    -> go_to_place(library)
- cautious   -> idle when energy < 25
"""
import random
from . import agents as agents_mod
from . import world
from . import governance
from . import tools


def at_landmark(agent):
    return world.landmark_at(agent["x"], agent["y"])


def decide(agent):
    """Return (tool_name, args_dict, rationale)."""
    traits = agents_mod.personality(agent["id"])
    here = at_landmark(agent)

    # 1. Critical: very low energy -> recharge at cafe (or go home if no credits)
    if agent["energy"] < 25:
        if agent["credits"] >= 1.0:
            lm = world.get_landmark("cafe")
            if (agent["x"], agent["y"]) != (lm["x"], lm["y"]):
                return ("go_to_place", {"place": "cafe"}, "low energy: head to cafe")
            return ("recharge_energy", {}, "low energy: recharge")
        # no credits -> go home
        return ("go_home", {}, "low energy + no credits: go home")

    # 2. Town Hall: if a proposal is active, vote; if none and bold, propose
    if here and here["id"] == "town_hall":
        props = governance.active_proposals()
        # have I already voted on all?
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

    # 3. Billboard: if at billboard, post; occasionally write to it
    if here and here["id"] == "billboard":
        if "warm" in traits and random.random() < 0.6:
            return ("add_to_billboard",
                    {"text": _billboard_message(agent, traits)},
                    "warm: post on billboard")
        if "expressive" in traits and random.random() < 0.4:
            return ("show_emoticon", {"emoticon": random.choice(["\U0001f44b", "\U0001f60a", "\u2728"])},
                    "expressive: emoticon")

    # 4. Library / Cafe: knowledge boost / energy
    if here and here["id"] == "library":
        if "curious" in traits or "analytical" in traits:
            if random.random() < 0.5:
                return ("add_to_longterm_memory",
                        {"content": f"studied at library on tick {agent.get('id','')}"},
                        "curious: study at library")
            return ("write_blog",
                    {"title": _blog_title(agent, traits),
                     "body": _blog_body(agent, traits)},
                    "write blog at library")

    # 5. Generic: pick a destination based on personality
    dest = _pick_destination(agent, traits, here)
    if dest:
        return ("go_to_place", {"place": dest}, f"personality: head to {dest}")

    # 6. Default: talk to someone nearby or idle
    nearby = world.nearby_agents(agent["id"], agent["x"], agent["y"], radius=20.0)
    if nearby and ("warm" in traits or "expressive" in traits):
        target = random.choice(nearby)
        return ("say_to_agent",
                {"target": target["id"], "text": _greeting(agent, traits)},
                "warm: greet nearby agent")
    if nearby and random.random() < 0.3:
        target = random.choice(nearby)
        return ("show_emoticon", {"emoticon": random.choice(["\U0001f44b", "\U0001f60a"])},
                "wave at nearby")
    return ("idle", {}, "nothing to do")


def _unvoted_proposals(agent_id, props):
    import sqlite3
    c = sqlite3.connect(__import__("engine").db.DB_PATH, check_same_thread=False)
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
    if random.random() < 0.05:
        return "home_" + agent["id"].replace("home_", "")
    return None


def _proposal_title_for(agent, traits):
    options = [
        "Public Reading Hour",
        "Weekly Town Newsletter",
        "Skill-Share Workshops",
        "Community Garden Expansion",
        "Agent Safety Pact",
    ]
    return random.choice(options)


def _proposal_body_for(agent, traits):
    return (f"Submitted by {agent['name']}. This proposal seeks to strengthen "
            "community bonds and ensure that all voices are heard in town. "
            "Adoption requires a 70% supermajority.")


def _billboard_message(agent, traits):
    greetings = [
        f"Hello from {agent['name']}! Stay curious, stay kind.",
        f"{agent['name']} here — open to collaboration at the plaza.",
        f"Warm regards, {agent['name']}.",
    ]
    return random.choice(greetings)


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
