"""Tool registry tests: all 15 tools, location-gating, handlers."""
import pytest


def test_registry_has_15_tools():
    from engine import tools
    tools.bootstrap()  # idempotent
    assert len(tools.all_tools()) == 15


def test_all_tool_names():
    from engine import tools
    tools.bootstrap()
    names = {t.name for t in tools.all_tools()}
    expected = {
        "go_to_place", "go_home", "say_to_agent", "speak_to_all",
        "show_emoticon", "idle", "recharge_energy", "add_to_longterm_memory",
        "write_blog", "add_to_billboard", "read_billboard",
        "submit_townhall_proposal", "vote_on_proposal", "list_agents",
        "list_landmarks",
    }
    assert expected.issubset(names), f"missing: {expected - names}"


def test_go_to_place_moves_agent(tmp_db):
    from engine import tools, agents as agents_mod
    spark = agents_mod.get("spark")
    res = tools.get("go_to_place").handler(spark, {"place": "library"}, {})
    assert res["ok"]
    spark2 = agents_mod.get("spark")
    assert (spark2["x"], spark2["y"]) == (60, 60)


def test_go_to_place_unknown_place(tmp_db):
    from engine import tools, agents as agents_mod
    spark = agents_mod.get("spark")
    res = tools.get("go_to_place").handler(spark, {"place": "atlantis"}, {})
    assert not res["ok"]
    assert "unknown" in res["error"]


def test_go_home(tmp_db):
    from engine import tools, agents as agents_mod
    # move spark away
    tools.get("go_to_place").handler(agents_mod.get("spark"), {"place": "plaza"}, {})
    res = tools.get("go_home").handler(agents_mod.get("spark"), {}, {})
    assert res["ok"]
    a = agents_mod.get("spark")
    assert (a["x"], a["y"]) == (210, 210)


def test_say_to_agent_queues_event(tmp_db):
    from engine import tools, agents as agents_mod
    spark = agents_mod.get("spark")
    ctx = {"speak_events": []}
    res = tools.get("say_to_agent").handler(
        spark, {"target": "flora", "text": "hello"}, ctx
    )
    assert res["ok"]
    assert len(ctx["speak_events"]) == 1
    assert ctx["speak_events"][0]["to"] == "flora"


def test_say_to_agent_empty_text(tmp_db):
    from engine import tools, agents as agents_mod
    spark = agents_mod.get("spark")
    ctx = {"speak_events": []}
    res = tools.get("say_to_agent").handler(
        spark, {"target": "flora", "text": "   "}, ctx
    )
    assert not res["ok"]


def test_say_to_agent_unknown_target(tmp_db):
    from engine import tools, agents as agents_mod
    spark = agents_mod.get("spark")
    res = tools.get("say_to_agent").handler(
        spark, {"target": "ghost", "text": "boo"}, {}
    )
    assert not res["ok"]


def test_speak_to_all(tmp_db):
    from engine import tools, agents as agents_mod
    spark = agents_mod.get("spark")
    ctx = {"speak_events": []}
    res = tools.get("speak_to_all").handler(spark, {"text": "Hello town!"}, ctx)
    assert res["ok"]
    assert res["broadcast"]
    assert len(ctx["speak_events"]) == 1


def test_show_emoticon(tmp_db):
    from engine import tools, agents as agents_mod
    spark = agents_mod.get("spark")
    ctx = {"speak_events": []}
    res = tools.get("show_emoticon").handler(spark, {"emoticon": "👋"}, ctx)
    assert res["ok"]
    assert res["emoticon"] == "👋"
    assert len(ctx["speak_events"]) == 1


def test_idle(tmp_db):
    from engine import tools, agents as agents_mod
    res = tools.get("idle").handler(agents_mod.get("anchor"), {}, {})
    assert res["ok"]
    assert res["idle"]


def test_recharge_costs_credit(tmp_db):
    from engine import tools, agents as agents_mod
    # Set energy low, credits ok
    agents_mod.update_state("anchor", energy=20.0, credits=5.0)
    # Move to cafe
    tools.get("go_to_place").handler(agents_mod.get("anchor"), {"place": "cafe"}, {})
    res = tools.get("recharge_energy").handler(agents_mod.get("anchor"), {}, {})
    assert res["ok"]
    a = agents_mod.get("anchor")
    assert a["energy"] == 70.0  # 20 + 50
    assert a["credits"] == 4.0   # 5 - 1


def test_recharge_fails_without_credits(tmp_db):
    from engine import tools, agents as agents_mod
    agents_mod.update_state("anchor", energy=20.0, credits=0.0)
    tools.get("go_to_place").handler(agents_mod.get("anchor"), {"place": "cafe"}, {})
    res = tools.get("recharge_energy").handler(agents_mod.get("anchor"), {}, {})
    assert not res["ok"]
    assert "credits" in res["error"]


def test_recharge_caps_at_100(tmp_db):
    from engine import tools, agents as agents_mod
    agents_mod.update_state("anchor", energy=80.0, credits=5.0)
    tools.get("go_to_place").handler(agents_mod.get("anchor"), {"place": "cafe"}, {})
    tools.get("recharge_energy").handler(agents_mod.get("anchor"), {}, {})
    a = agents_mod.get("anchor")
    assert a["energy"] == 100.0  # capped


def test_recharge_not_available_off_site(tmp_db):
    from engine import tools, world, agents as agents_mod
    spark = agents_mod.get("spark")
    at_lm = world.landmark_at(spark["x"], spark["y"])
    # spark spawns at home_spark, not cafe
    assert not tools.get("recharge_energy").available_for(spark, at_lm)


def test_add_to_longterm_memory(tmp_db):
    from engine import tools, agents as agents_mod
    res = tools.get("add_to_longterm_memory").handler(
        agents_mod.get("anchor"),
        {"content": "today I learned something"},
        {}
    )
    assert res["ok"]


def test_add_to_longterm_memory_empty(tmp_db):
    from engine import tools, agents as agents_mod
    res = tools.get("add_to_longterm_memory").handler(
        agents_mod.get("anchor"), {"content": ""}, {}
    )
    assert not res["ok"]


def test_write_blog_boosts_knowledge(tmp_db):
    from engine import tools, agents as agents_mod
    agents_mod.update_state("anchor", knowledge=50.0)
    res = tools.get("write_blog").handler(
        agents_mod.get("anchor"),
        {"title": "Hi", "body": "body text"},
        {}
    )
    assert res["ok"]
    a = agents_mod.get("anchor")
    assert a["knowledge"] == 70.0  # 50 + 20


def test_add_to_billboard_gated(tmp_db):
    from engine import tools, world, agents as agents_mod
    spark = agents_mod.get("spark")
    at_lm = world.landmark_at(spark["x"], spark["y"])
    # spark at home_spark — not at billboard
    assert not tools.get("add_to_billboard").available_for(spark, at_lm)
    # Move to billboard
    tools.get("go_to_place").handler(spark, {"place": "billboard"}, {})
    spark = agents_mod.get("spark")
    at_lm = world.landmark_at(spark["x"], spark["y"])
    assert tools.get("add_to_billboard").available_for(spark, at_lm)


def test_submit_proposal_gated_to_town_hall(tmp_db):
    from engine import tools, world, agents as agents_mod
    a = agents_mod.get("anchor")
    at_lm = world.landmark_at(a["x"], a["y"])
    assert not tools.get("submit_townhall_proposal").available_for(a, at_lm)
    tools.get("go_to_place").handler(a, {"place": "town_hall"}, {})
    a = agents_mod.get("anchor")
    at_lm = world.landmark_at(a["x"], a["y"])
    assert tools.get("submit_townhall_proposal").available_for(a, at_lm)


def test_submit_proposal_requires_title_and_body(tmp_db):
    from engine import tools, agents as agents_mod
    tools.get("go_to_place").handler(agents_mod.get("anchor"), {"place": "town_hall"}, {})
    res = tools.get("submit_townhall_proposal").handler(
        agents_mod.get("anchor"), {"title": "", "body": "x"}, {}
    )
    assert not res["ok"]


def test_list_agents_and_landmarks(tmp_db):
    from engine import tools, agents as agents_mod
    res = tools.get("list_agents").handler(agents_mod.get("anchor"), {}, {})
    assert res["ok"]
    assert "Anchor" in res["agents"]
    res = tools.get("list_landmarks").handler(agents_mod.get("anchor"), {}, {})
    assert res["ok"]
    assert "Town Hall" in res["landmarks"]
