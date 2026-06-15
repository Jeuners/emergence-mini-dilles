#!/usr/bin/env python3
"""Analyse the running Emergence-Mini simulation.

Reads the SQLite DB and prints a report covering:
- Time Dilation (tau, pace, gamma, drift) per agent
- Tool-usage distribution
- Decision-mode split (llm vs fallback)
- Latency stats per model
- Token / cost estimation

Usage:
    python3 analyze.py             # default DB (./emergence.db)
    python3 analyze.py --db X     # custom DB path
    python3 analyze.py --json     # machine-readable output
"""
import argparse
import json
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent / "emergence.db"

# Module-level handle, may be overridden in main()
DB = DEFAULT_DB


def query(sql, params=()):
    c = sqlite3.connect(str(DB), check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in c.execute(sql, params).fetchall()]
    finally:
        c.close()


def hr(c="-", n=70):
    print(c * n)


def section(title):
    print()
    hr("=")
    print(f"  {title}")
    hr("=")


def time_dilation():
    section("TIME DILATION . tau (Eigenzeit) & Pace")
    agents = query("SELECT id, name, personality, energy, knowledge, influence, credits FROM agents WHERE alive=1")
    clocks = {c["agent_id"]: c for c in query("SELECT * FROM agent_clocks")}
    if not clocks:
        print("  (no clock data yet - wait for a few rounds)")
        return
    print(f"  {'Agent':10s}  {'tau':>7s}  {'pace':>7s}  {'n_ops':>6s}  traits")
    for a in agents:
        c = clocks.get(a["id"], {})
        tau = c.get("tau", 0.0)
        pace = c.get("pace", 0.0)
        n = c.get("n_ops", 0)
        traits = json.loads(a["personality"])
        print(f"  {a['name']:10s}  {tau:7.2f}  {pace:7.3f}  {n:6d}  {','.join(traits)}")
    print()
    print("  Pairwise Frame-Transformation (gamma) and |dtau|:")
    items = list(clocks.items())
    for i, (a_id, a) in enumerate(items):
        for b_id, b in items[i+1:]:
            if a["pace"] > 0 and b["pace"] > 0:
                gamma = a["pace"] / b["pace"]
            else:
                gamma = 1.0
            drift = abs(a["tau"] - gamma * b["tau"])
            div = " !! DIVERGENT" if drift > 3.0 else ""
            print(f"    {a_id:8s} <-> {b_id:8s}   gamma={gamma:5.2f}   |dtau|={drift:6.2f}{div}")


def tool_usage():
    section("TOOL USAGE")
    rows = query("SELECT tool, COUNT(*) AS n FROM turn_log GROUP BY tool ORDER BY n DESC")
    if not rows:
        print("  (no data)")
        return
    total = sum(r["n"] for r in rows)
    print(f"  Total tool calls: {total}")
    print(f"  {'Tool':25s}  {'#':>5s}  {'%':>5s}")
    for r in rows:
        pct = 100.0 * r["n"] / total if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {r['tool']:25s}  {r['n']:5d}  {pct:5.1f}%  {bar}")


def decision_modes():
    section("DECISION MODES (LLM vs Fallback)")
    rows = query("SELECT decision_mode, COUNT(*) AS n FROM turn_log GROUP BY decision_mode ORDER BY n DESC")
    if not rows:
        print("  (no data)")
        return
    total = sum(r["n"] for r in rows)
    for r in rows:
        mode = r["decision_mode"] or "NULL"
        pct = 100.0 * r["n"] / total if total else 0
        print(f"  {mode:25s}  {r['n']:5d}  {pct:5.1f}%")
    print()
    print("  Per-agent LLM-Rate (mode='llm' / total):")
    agents = query("SELECT id, name FROM agents WHERE alive=1")
    for a in agents:
        n = query("SELECT COUNT(*) AS c FROM turn_log WHERE agent_id=?", (a["id"],))
        n_total = n[0]["c"] if n else 0
        n_llm = query("SELECT COUNT(*) AS c FROM turn_log WHERE agent_id=? AND decision_mode='llm'", (a["id"],))
        n_llm = n_llm[0]["c"] if n_llm else 0
        rate = 100.0 * n_llm / n_total if n_total else 0
        print(f"  {a['name']:10s}  {n_llm:3d}/{n_total:3d}  ({rate:5.1f}%)")


def latencies():
    section("LATENCIES (per model, inter-turn delta)")
    rows = query("SELECT agent_id, model, tool, ts FROM turn_log ORDER BY id")
    if len(rows) < 2:
        print("  (not enough data)")
        return
    by_model = defaultdict(list)
    last = None
    for r in rows:
        if last is not None and r["model"]:
            dt = r["ts"] - last["ts"]
            if 0 < dt < 120:
                short = r["model"].split("/")[-1].replace(":latest", "")
                by_model[short].append(dt)
        last = r
    for m, vals in sorted(by_model.items(), key=lambda x: -sum(x[1])/len(x[1])):
        if not vals:
            continue
        vals_sorted = sorted(vals)
        n = len(vals)
        avg = sum(vals) / n
        p50 = vals_sorted[n // 2]
        p95 = vals_sorted[int(n * 0.95)] if n > 1 else vals_sorted[-1]
        print(f"  {m:25s}  n={n:4d}  avg={avg:5.2f}s  p50={p50:5.2f}s  p95={p95:5.2f}s  min={min(vals):5.2f}s  max={max(vals):5.2f}s")


def texts():
    section("GENERATED TEXTS (recent)")
    bills = query("SELECT * FROM bills ORDER BY id DESC LIMIT 5")
    for b in bills:
        try:
            p = json.loads(b["body"])
        except Exception:
            p = {"title": "?", "body": str(b["body"])[:200]}
        print(f"  Blog  [{b['author']:8s}]  \"{p.get('title','')}\"")
        print(f"         {p.get('body','')[:160]}")
    events = query("SELECT * FROM events WHERE kind='billboard_post' ORDER BY id DESC LIMIT 3")
    for e in events:
        try:
            p = json.loads(e["payload"])
        except Exception:
            continue
        print(f"  Billboard [{e['actor']:8s}]  {p.get('text','')[:160]}")


def constitution():
    section("CONSTITUTION")
    rows = query("SELECT * FROM constitution ORDER BY version DESC LIMIT 1")
    if not rows:
        print("  (no constitution loaded)")
        return
    c = json.loads(rows[0]["json"])
    print(f"  Version: {rows[0]['version']}   Articles: {len(c.get('articles', []))}")
    for a in c.get("articles", []):
        print(f"    {a['id']:2d}. {a['title']:30s}  {a['body'][:90]}")
    accepted = query("SELECT id, title FROM proposals WHERE status='accepted'")
    if accepted:
        print(f"  Accepted amendments: {len(accepted)}")
        for a in accepted:
            print(f"    #{a['id']}  {a['title']}")


def cost_estimate():
    section("COST ESTIMATE (OpenRouter tokens only)")
    rows = query("""SELECT model, COUNT(*) AS n
                    FROM turn_log WHERE model LIKE '%/%' GROUP BY model""")
    if not rows:
        print("  (no OpenRouter calls in window)")
        return
    RATES = {
        "anthropic/claude-3.5-haiku": 0.0001,
        "openai/gpt-4o-mini": 0.00005,
        "default": 0.0001,
    }
    total = 0.0
    print(f"  {'Model':35s}  {'#':>5s}  {'$/call':>10s}  {'$ total':>10s}")
    for r in rows:
        rate = RATES.get(r["model"], RATES["default"])
        cost = r["n"] * rate
        total += cost
        print(f"  {r['model']:35s}  {r['n']:5d}  {rate:10.5f}  {cost:10.4f}")
    print(f"  {'Total':35s}  {'':5s}  {'':10s}  {total:10.4f}")
    if rows:
        n_total = sum(r["n"] for r in rows)
        first_ts = query("SELECT MIN(ts) AS t FROM turn_log")[0]["t"]
        last_ts = query("SELECT MAX(ts) AS t FROM turn_log")[0]["t"]
        elapsed_h = (last_ts - first_ts) / 3600.0 if last_ts > first_ts else 0
        if elapsed_h > 0:
            scale = 24.0 / elapsed_h
            print(f"  Window: {elapsed_h:.2f}h. Projected 24h cost: ${total * scale:.2f}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--db", default=str(DEFAULT_DB))
    p.add_argument("--json", action="store_true",
                   help="output as JSON instead of formatted text")
    args = p.parse_args()
    global DB
    DB = Path(args.db)
    if not DB.exists():
        print(f"DB not found: {DB}")
        sys.exit(1)

    if args.json:
        out = {}
        out["clocks"] = query("SELECT * FROM agent_clocks")
        out["tool_usage"] = query("SELECT tool, COUNT(*) AS n FROM turn_log GROUP BY tool ORDER BY n DESC")
        out["decision_modes"] = query("SELECT decision_mode, COUNT(*) AS n FROM turn_log GROUP BY decision_mode ORDER BY n DESC")
        out["models"] = query("SELECT model, COUNT(*) AS n FROM turn_log WHERE model IS NOT NULL GROUP BY model")
        out["constitution"] = query("SELECT * FROM constitution ORDER BY version DESC LIMIT 1")
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"DB: {DB}")
        time_dilation()
        tool_usage()
        decision_modes()
        latencies()
        texts()
        constitution()
        cost_estimate()


if __name__ == "__main__":
    main()
