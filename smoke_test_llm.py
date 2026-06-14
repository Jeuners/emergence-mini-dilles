#!/usr/bin/env python3
"""Live smoke test against a real Ollama instance.

This is NOT part of the regular pytest suite — it is slow (10-30s per turn
because llama3.2:3b has to think) and requires a running Ollama server with
at least one chat-capable model pulled.

Usage:
    python3 smoke_test_llm.py                # uses default model
    EMERGENCE_LLM_MODEL=qwen2.5-coder:7b python3 smoke_test_llm.py
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# fresh DB
db_file = ROOT / "emergence_llm_smoke.db"
if db_file.exists():
    db_file.unlink()
os.environ["EMERGENCE_LLM_ENABLED"] = "1"

from engine import db, world, agents as agents_mod, tools, llm as llm_mod
from engine import reasoning

OK = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"


def main():
    print("=== Emergence-Mini · Live LLM Smoke Test ===\n")
    print(f"Model:  {llm_mod.DEFAULT_MODEL}")
    print(f"URL:    {llm_mod.URL}")
    print(f"Timeout:{llm_mod.TIMEOUT}s\n")

    if not llm_mod.is_available():
        print(f"{FAIL} Ollama nicht erreichbar unter {llm_mod.URL}")
        print("Starte Ollama: ollama serve")
        print(f"Ziehe das Modell: ollama pull {llm_mod.DEFAULT_MODEL}")
        sys.exit(1)
    print(f"{OK} Ollama erreichbar\n")

    db.init_db()
    db.set_world_state("landmarks_seeded", False)
    db.set_world_state("agents_seeded", False)
    world.bootstrap()
    agents_mod.bootstrap()
    tools.bootstrap()
    print(f"{OK} Welt + 4 Agenten gebootet\n")

    print("--- 4 Decisions ---\n")
    successes = 0
    for aid in ("anchor", "flora", "lovely", "spark"):
        a = agents_mod.get(aid)
        print(f"  [{a['name']:8s}] @ ({a['x']:3d},{a['y']:3d}) E={a['energy']:.0f} K={a['knowledge']:.0f} I={a['influence']:.0f} {a['credits']:.0f}CC")
        t0 = time.time()
        name, args, rat = reasoning.decide(a)
        dt = time.time() - t0
        mode = reasoning.get_last_decision()
        marker = OK if mode["mode"] == "llm" else WARN
        print(f"    {marker} tool={name!r:30s} args={args!r:30s}")
        print(f"        mode={mode['mode']:18s} latency={dt:.1f}s")
        print(f"        rationale: {rat}\n")
        if mode["mode"] == "llm":
            successes += 1

    print(f"\n=== Resultat: {successes}/4 LLM-Decisions erfolgreich ===")
    if successes >= 3:
        print(f"{OK} Live-LLM-Integration funktioniert")
    else:
        print(f"{FAIL} Zu viele Fallbacks — Modell oder Schema pruefen")


if __name__ == "__main__":
    main()
