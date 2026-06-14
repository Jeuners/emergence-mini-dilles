"""Reasoning engine tests: decision validity, personality effects."""
import pytest
from engine import tools


def test_decide_returns_valid_tool(tmp_db):
    from engine import reasoning, agents as agents_mod
    a = agents_mod.get("anchor")
    tool_name, args, rationale = reasoning.decide(a)
    assert tool_name in {t.name for t in tools.all_tools()}
    assert isinstance(args, dict)
    assert isinstance(rationale, str)
    assert rationale  # non-empty


def test_low_energy_triggers_recharge_path(tmp_db):
    from engine import reasoning, agents as agents_mod
    agents_mod.update_state("anchor", energy=10.0, credits=5.0)
    # move to cafe
    tools.get("go_to_place").handler(agents_mod.get("anchor"), {"place": "cafe"}, {})
    a = agents_mod.get("anchor")
    tool_name, args, _ = reasoning.decide(a)
    assert tool_name in ("recharge_energy", "go_home")


def test_low_energy_no_credits_goes_home(tmp_db):
    from engine import reasoning, agents as agents_mod
    agents_mod.update_state("anchor", energy=10.0, credits=0.0)
    a = agents_mod.get("anchor")
    tool_name, _, _ = reasoning.decide(a)
    assert tool_name == "go_home"


def test_curious_agent_visits_library(tmp_db):
    from engine import reasoning, agents as agents_mod
    a = agents_mod.get("anchor")  # has 'curious'
    tool_name, args, _ = reasoning.decide(a)
    if tool_name == "go_to_place":
        assert args["place"] in ("library", "plaza", "town_hall",
                                 "park", "home_anchor", "cafe")


def test_run_rounds_completes(tmp_db):
    from engine.turn import engine as sim_engine
    from engine import agents as agents_mod
    before = len(agents_mod.all_agents())
    for _ in range(3):
        sim_engine._one_round()
    after = len(agents_mod.all_agents())
    assert before == after == 4


def test_no_tool_returns_unknown():
    from engine import tools
    assert tools.get("not_a_real_tool") is None
