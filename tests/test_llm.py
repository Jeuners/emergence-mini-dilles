"""LLM integration tests.

We do NOT call Ollama from pytest (too slow, too flaky). Instead we mock
the HTTP layer in engine.llm. A separate live smoke test exercises the
real model — see smoke_test_llm.py at the repo root.
"""
import json
from unittest import mock


def test_is_available_true(monkeypatch):
    from engine import llm
    monkeypatch.setattr(llm, "URL", "http://fake")
    fake_resp = mock.MagicMock()
    fake_resp.read = lambda: b"{}"
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda s, *a: False
    with mock.patch("urllib.request.urlopen", return_value=fake_resp):
        assert llm.is_available() is True


def test_is_available_false():
    from engine import llm
    with mock.patch("urllib.request.urlopen",
                    side_effect=Exception("connection refused")):
        assert llm.is_available() is False


def test_tool_schema_basic():
    from engine import llm, tools
    tools.bootstrap()
    schema = llm.tool_schema(tools.all_tools())
    names = {t["function"]["name"] for t in schema}
    assert "go_to_place" in names
    assert "vote_on_proposal" in names
    # vote_on_proposal must mark 'vote' as enum
    vote_tool = next(t for t in schema
                     if t["function"]["name"] == "vote_on_proposal")
    assert vote_tool["function"]["parameters"]["properties"]["vote"]["enum"] == ["for", "against"]


def test_decide_tool_parses_response():
    from engine import llm
    fake = {
        "message": {
            "tool_calls": [
                {"function": {"name": "go_to_place",
                              "arguments": {"place": "library"}}}
            ]
        }
    }
    with mock.patch.object(llm, "chat", return_value=fake):
        name, args = llm.decide_tool([{"role": "user", "content": "x"}], tools=[])
    assert name == "go_to_place"
    assert args == {"place": "library"}


def test_decide_tool_handles_string_args():
    from engine import llm
    fake = {
        "message": {
            "tool_calls": [
                {"function": {"name": "idle", "arguments": "{}"}}
            ]
        }
    }
    with mock.patch.object(llm, "chat", return_value=fake):
        name, args = llm.decide_tool([], tools=[])
    assert name == "idle"
    assert args == {}


def test_decide_tool_no_tool_call_returns_none():
    from engine import llm
    fake = {"message": {"content": "I think... no tool"}}
    with mock.patch.object(llm, "chat", return_value=fake):
        name, args = llm.decide_tool([], tools=[])
    assert name is None
    assert args is None


def test_reasoning_uses_llm_when_available(tmp_db, monkeypatch):
    """If the LLM is reachable and returns a valid tool, reasoning uses it."""
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    # Force the LLM path
    monkeypatch.setattr(reasoning, "USE_LLM", True)
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    with mock.patch.object(llm_mod, "decide_tool",
                           return_value=("go_to_place", {"place": "library"})):
        a = agents_mod.get("anchor")
        name, args, rat = reasoning.decide(a)
    assert name == "go_to_place"
    assert args == {"place": "library"}
    assert "llm" in rat
    assert reasoning.get_last_decision()["mode"] == "llm"


def test_reasoning_falls_back_on_unknown_tool(tmp_db, monkeypatch):
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(reasoning, "USE_LLM", True)
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    with mock.patch.object(llm_mod, "decide_tool",
                           return_value=("teleport_to_mars", {})):
        a = agents_mod.get("anchor")
        name, _, _ = reasoning.decide(a)
    # fallback to rule path -> one of the rule-based picks
    assert name in {t.name for t in __import__("engine").tools.all_tools()}
    assert reasoning.get_last_decision()["mode"].startswith("fallback")


def test_reasoning_falls_back_on_wrong_location(tmp_db, monkeypatch):
    """LLM says submit_townhall_proposal but agent is at home -> fallback."""
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(reasoning, "USE_LLM", True)
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    # anchor is at home_anchor (30, 30); town_hall is at (120, 120)
    with mock.patch.object(llm_mod, "decide_tool",
                           return_value=("submit_townhall_proposal",
                                         {"title": "x", "body": "y"})):
        a = agents_mod.get("anchor")
        name, _, _ = reasoning.decide(a)
    # rule path won't try to submit from home
    assert name != "submit_townhall_proposal"
    assert reasoning.get_last_decision()["mode"].startswith("fallback")


def test_reasoning_falls_back_on_connection_error(tmp_db, monkeypatch):
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(reasoning, "USE_LLM", True)
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    with mock.patch.object(llm_mod, "decide_tool",
                           side_effect=ConnectionError("ollama down")):
        a = agents_mod.get("anchor")
        name, _, rat = reasoning.decide(a)
    # got a fallback pick
    assert name in {t.name for t in __import__("engine").tools.all_tools()}
    assert reasoning.get_last_decision()["mode"] == "fallback:ConnectionError"


def test_env_var_disables_llm(monkeypatch, tmp_db):
    """Setting EMERGENCE_LLM_ENABLED=0 forces the rule path even when Ollama
    is reachable. This is how the test suite avoids the slow live LLM calls.
    """
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    monkeypatch.setattr(reasoning, "USE_LLM", False)
    a = agents_mod.get("anchor")
    name, _, _ = reasoning.decide(a)
    assert reasoning.get_last_decision()["mode"] == "rule"
