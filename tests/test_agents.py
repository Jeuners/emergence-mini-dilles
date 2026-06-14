"""Agent module tests: bootstrap, state, personality."""
import json


def test_bootstrap_creates_4_agents(tmp_db):
    from engine import agents as agents_mod
    agents = agents_mod.all_agents()
    assert len(agents) == 4
    ids = {a["id"] for a in agents}
    assert ids == {"anchor", "flora", "lovely", "spark"}


def test_initial_state(tmp_db):
    from engine import agents as agents_mod
    a = agents_mod.get("anchor")
    assert a["energy"] == 100.0
    assert a["knowledge"] == 100.0
    assert a["influence"] == 100.0
    assert a["credits"] == 10.0
    assert a["alive"] == 1
    # anchor has 4 personality traits
    traits = json.loads(a["personality"])
    assert len(traits) == 4
    assert "diplomatic" in traits


def test_agents_spawn_at_home(tmp_db):
    from engine import agents as agents_mod
    spawns = {
        "anchor": (30, 30),   # home_anchor
        "flora":  (210, 30),  # home_flora
        "lovely": (30, 210),  # home_lovely
        "spark":  (210, 210), # home_spark
    }
    for aid, (x, y) in spawns.items():
        a = agents_mod.get(aid)
        assert (a["x"], a["y"]) == (x, y), f"{aid} not at home"


def test_update_position(tmp_db):
    from engine import agents as agents_mod
    agents_mod.update_position("anchor", 100, 100)
    a = agents_mod.get("anchor")
    assert (a["x"], a["y"]) == (100, 100)


def test_update_state(tmp_db):
    from engine import agents as agents_mod
    agents_mod.update_state("anchor", energy=42.0, mood="happy")
    a = agents_mod.get("anchor")
    assert a["energy"] == 42.0
    assert a["mood"] == "happy"
    # other fields unchanged
    assert a["knowledge"] == 100.0


def test_personality_loader(tmp_db):
    from engine import agents as agents_mod
    traits = agents_mod.personality("spark")
    assert "bold" in traits
    assert "creative" in traits
    # Unknown agent -> empty list
    assert agents_mod.personality("nope") == []


def test_get_unknown_agent(tmp_db):
    from engine import agents as agents_mod
    assert agents_mod.get("does_not_exist") is None
