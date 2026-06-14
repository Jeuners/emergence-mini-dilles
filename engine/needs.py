"""Needs system: Energy / Knowledge / Influence decay.

Decay is accelerated relative to the real Emergence World so the
simulation produces visible behaviour in seconds, not days.
"""
import sqlite3

from . import agents

# Hours to drain fully. Real Emergence: 30h/24h/36h.
# We compress to: 6h/5h/7h in sim time. A tick = 1 sim-minute.
ENERGY_FULL_HOURS = 6.0
KNOWLEDGE_FULL_HOURS = 5.0
INFLUENCE_FULL_HOURS = 7.0

TICK_MINUTES = 1.0  # 1 sim minute per tick

# How many sim hours each behaviour costs / grants.
RECHARGE_HOURS = 4.0      # recharge_energy -> +50% energy, costs 1 CC
RESEARCH_HOURS = 1.0      # write_blog / research -> +20% knowledge
SOCIAL_HOURS = 0.5        # say_to_agent / speak_to_all / show_emoticon -> +5% influence


def decay_per_tick():
    return {
        "energy": 100.0 / (ENERGY_FULL_HOURS * 60.0 / TICK_MINUTES),
        "knowledge": 100.0 / (KNOWLEDGE_FULL_HOURS * 60.0 / TICK_MINUTES),
        "influence": 100.0 / (INFLUENCE_FULL_HOURS * 60.0 / TICK_MINUTES),
    }


def decay_all():
    d = decay_per_tick()
    c = sqlite3.connect(__import__("engine").db.DB_PATH, check_same_thread=False)
    try:
        c.execute(
            "UPDATE agents SET energy=MAX(0,energy-?), "
            "knowledge=MAX(0,knowledge-?), influence=MAX(0,influence-?) WHERE alive=1",
            (d["energy"], d["knowledge"], d["influence"]),
        )
        c.commit()
    finally:
        c.close()


def tick_all_needs():
    decay_all()
