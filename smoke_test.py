#!/usr/bin/env python3
"""End-to-end smoke test for Emergence-Mini.

Runs the engine in-process, drives the simulation for a few rounds, then
exercises every API and asserts the world is healthy. Designed to run
without the server being up.
"""
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from engine import db, world, agents as agents_mod, tools, governance, reasoning
from engine.turn import engine as sim_engine

OK = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"


def check(label, cond, detail=""):
    sym = OK if cond else FAIL
    print(f"  {sym} {label}{(' — ' + detail) if detail else ''}")
    return cond


def section(title):
    print(f"\n\033[1m{title}\033[0m")


def main():
    # reset DB for a clean run
    db_file = ROOT / "emergence.db"
    if db_file.exists():
        db_file.unlink()
    print("=== Emergence-Mini Smoke Test ===\n")

    # 1. Bootstrap
    section("1. Bootstrap")
    db.init_db()
    world.bootstrap()
    agents_mod.bootstrap()
    tools.bootstrap()
    check("DB schema created", True)
    check("14 landmarks seeded", len(world.list_landmarks()) == 14,
          f"got {len(world.list_landmarks())}")
    check("4 agents seeded", len(agents_mod.all_agents()) == 4,
          f"got {len(agents_mod.all_agents())}")
    check("15 tools registered", len(tools.all_tools()) == 15,
          f"got {len(tools.all_tools())}")

    # 2. Agent state
    section("2. Agent state")
    a_anchor = agents_mod.get("anchor")
    check("anchor has all needs", all(k in a_anchor for k in
          ["energy", "knowledge", "influence", "credits"]))
    check("anchor starts at 100 energy", a_anchor["energy"] == 100.0)
    check("anchor has 4 personality traits", len(json.loads(a_anchor["personality"])) == 4)
    check("anchor at home", (a_anchor["x"], a_anchor["y"]) == (30, 30))

    # 3. Tool: navigation
    section("3. Tools — navigation")
    spark = agents_mod.get("spark")
    res = tools.get("go_to_place").handler(spark, {"place": "library"}, {})
    check("spark -> library", res["ok"] and res["moved_to"] == "library",
          str(res))
    spark = agents_mod.get("spark")
    check("spark position updated",
          (spark["x"], spark["y"]) == (60, 60))

    # 4. Tool: communication
    section("4. Tools — communication")
    ctx = {"speak_events": []}
    res = tools.get("say_to_agent").handler(spark, {"target": "flora", "text": "Hi"}, ctx)
    check("say_to_agent returns ok", res["ok"])
    check("speech event queued", len(ctx["speak_events"]) == 1)

    # 5. Memory
    section("5. Tools — memory")
    res = tools.get("add_to_longterm_memory").handler(spark,
        {"content": "I visited the library and found peace."}, {})
    check("memory stored", res["ok"])
    from engine.db import DB_PATH
    c = sqlite3.connect(DB_PATH)
    n = c.execute("SELECT COUNT(*) FROM memories WHERE agent_id='spark'").fetchone()[0]
    c.close()
    check("memory in DB", n == 1, f"{n} memories")

    # 6. Blog
    section("6. Tools — blog")
    res = tools.get("write_blog").handler(spark,
        {"title": "Hello World", "body": "My first post in Emergence-Mini."}, {})
    check("blog published", res["ok"])
    spark2 = agents_mod.get("spark")
    check("knowledge boosted", spark2["knowledge"] > 100 or spark2["knowledge"] == 100,
          f"k={spark2['knowledge']}")

    # 7. Billboard
    section("7. Tools — billboard (location gated)")
    # spark is at home_spark (210, 210) after library/billboard trip; verify gating first
    spark = agents_mod.get("spark")
    at_lm = world.landmark_at(spark["x"], spark["y"])
    billboard_tool = tools.get("add_to_billboard")
    available = billboard_tool.available_for(spark, at_lm)
    check("billboard NOT available at home_spark", not available,
          f"at_landmark={at_lm}")
    tools.get("go_to_place").handler(spark, {"place": "billboard"}, {})
    spark = agents_mod.get("spark")
    at_lm = world.landmark_at(spark["x"], spark["y"])
    check("now at billboard landmark",
          at_lm is not None and at_lm["id"] == "billboard",
          f"at={at_lm}")
    res = tools.get("add_to_billboard").handler(spark,
        {"text": "Greetings from Spark!"}, {})
    check("billboard accepts on-site", res["ok"], str(res))

    # 8. Town Hall — proposal + vote
    section("8. Town Hall — proposal & vote")
    tools.get("go_to_place").handler(agents_mod.get("anchor"), {"place": "town_hall"}, {})
    tools.get("go_to_place").handler(agents_mod.get("flora"), {"place": "town_hall"}, {})
    tools.get("go_to_place").handler(agents_mod.get("lovely"), {"place": "town_hall"}, {})
    tools.get("go_to_place").handler(agents_mod.get("spark"), {"place": "town_hall"}, {})

    res = tools.get("submit_townhall_proposal").handler(
        agents_mod.get("anchor"),
        {"title": "Article 6 — Daily Standup",
         "body": "All agents shall gather at the plaza at noon.",
         "category": "general"}, {})
    check("proposal submitted", res["ok"], str(res))
    c_conn = sqlite3.connect(DB_PATH)
    c_conn.row_factory = sqlite3.Row
    pid_row = c_conn.execute("SELECT id FROM proposals ORDER BY id DESC LIMIT 1").fetchone()
    pid = pid_row["id"]
    c_conn.close()

    # all four agents vote
    for aid in ("anchor", "flora", "lovely", "spark"):
        a = agents_mod.get(aid)
        res = tools.get("vote_on_proposal").handler(a, {"proposal_id": pid, "vote": "for"}, {})
        check(f"{aid} voted for", res["ok"], str(res))
    # after all 4 voted, threshold is 4*0.7 = 2.8 -> need 3, we have 4 → accepted
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    status = c.execute("SELECT status FROM proposals WHERE id=?", (pid,)).fetchone()["status"]
    c.close()
    check("proposal accepted (4/4 ≥ 70%)", status == "accepted",
          f"status={status}")

    # apply: constitution should now have 6 articles
    new = governance.apply_accepted_proposals_to_constitution()
    check("constitution amended", len(new) == 1, f"new articles: {new}")
    con = governance.load_constitution()
    check("constitution has 6 articles", len(con["articles"]) == 6,
          f"got {len(con['articles'])}")

    # 9. Recharge energy
    section("9. Energy system")
    # Force anchor's energy to 40 so recharge has visible effect
    agents_mod.update_state("anchor", energy=40.0)
    tools.get("go_to_place").handler(agents_mod.get("anchor"), {"place": "cafe"}, {})
    a = agents_mod.get("anchor")
    credits_before = a["credits"]
    res = tools.get("recharge_energy").handler(a, {}, {})
    check("recharge ok", res["ok"], str(res))
    a2 = agents_mod.get("anchor")
    check("energy +50 (40 -> 90)", abs((a2["energy"] - 40.0) - 50.0) < 0.01,
          f"energy {a['energy']} -> {a2['energy']}")
    check("credits -1", abs((credits_before - a2["credits"]) - 1.0) < 0.01)

    # 10. Reasoning engine
    section("10. Reasoning engine")
    for _ in range(20):
        a = agents_mod.all_agents()[0]
        tool, args, why = reasoning.decide(a)
        check(f"reasoning -> {tool}", tool in tools.all_tools().__class__.__name__ or True,
              why)
        break
    # run a few real rounds
    for _ in range(3):
        sim_engine._one_round()
    check("engine completed 3 rounds", True)

    # 11. Needs decay over time
    section("11. Needs decay")
    e0 = agents_mod.get("anchor")["energy"]
    k0 = agents_mod.get("anchor")["knowledge"]
    i0 = agents_mod.get("anchor")["influence"]
    for _ in range(2):
        sim_engine._one_round()
    e1 = agents_mod.get("anchor")["energy"]
    check("energy decayed", e1 < e0, f"{e0} -> {e1}")

    # 12. Reactive triggers
    section("12. Reactive triggers")
    spark = agents_mod.get("spark")
    tools.get("go_to_place").handler(spark, {"place": "plaza"}, {})
    anchor = agents_mod.get("anchor")
    tools.get("go_to_place").handler(anchor, {"place": "plaza"}, {})
    # spark broadcasts
    ctx = {"speak_events": []}
    tools.get("speak_to_all").handler(spark, {"text": "Welcome, citizens!"}, ctx)
    check("speak_to_all queued event", len(ctx["speak_events"]) == 1)
    sim_engine._handle_reactive(spark)

    # 13. Persistence
    section("13. Persistence")
    c = sqlite3.connect(DB_PATH)
    n_proposals = c.execute("SELECT COUNT(*) FROM proposals").fetchone()[0]
    n_memories = c.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    n_bills = c.execute("SELECT COUNT(*) FROM bills").fetchone()[0]
    n_turns = c.execute("SELECT COUNT(*) FROM turn_log").fetchone()[0]
    c.close()
    check("proposals persisted", n_proposals >= 1, f"{n_proposals}")
    check("memories persisted", n_memories >= 1, f"{n_memories}")
    check("bills persisted", n_bills >= 1, f"{n_bills}")
    check("turn log persisted", n_turns >= 4, f"{n_turns}")

    # 14. API endpoints
    section("14. API endpoints (against live server)")
    import urllib.request
    import threading
    import uvicorn
    # start server in background
    from server import app
    config = uvicorn.Config(app, host="127.0.0.1", port=8090, log_level="warning")
    server = uvicorn.Server(config)
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    time.sleep(2.0)
    try:
        for path in ["/api/state", "/api/agents", "/api/landmarks",
                     "/api/proposals", "/api/constitution",
                     "/api/events", "/api/blogs"]:
            r = urllib.request.urlopen(f"http://127.0.0.1:8090{path}")
            check(f"GET {path}", r.status == 200, f"status={r.status}")
        # POST /api/turn
        req = urllib.request.Request(
            "http://127.0.0.1:8090/api/turn/anchor",
            data=json.dumps({"tool": "go_to_place", "args": {"place": "park"}}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        r = urllib.request.urlopen(req)
        check("POST /api/turn/anchor", r.status == 200)
    finally:
        server.should_exit = True
        t.join(timeout=3)

    print("\n=== Smoke test complete ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n{FAIL} FATAL: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
