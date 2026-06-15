"""LLM integration tests.

We do NOT call Ollama or OpenRouter from pytest (slow, flaky, costs money).
We mock the HTTP layer. A separate live smoke test exercises the real
model — see smoke_test_llm.py.
"""
import json
from unittest import mock


def test_is_available_true(monkeypatch):
    from engine import llm
    monkeypatch.setattr(llm, "OLLAMA_URL", "http://fake")
    monkeypatch.setattr(llm, "_openrouter_key", lambda: "")
    monkeypatch.setattr(llm, "PROVIDER", "ollama")
    fake_resp = mock.MagicMock()
    fake_resp.read = lambda: b"{}"
    fake_resp.__enter__ = lambda s: s
    fake_resp.__exit__ = lambda s, *a: False
    with mock.patch("urllib.request.urlopen", return_value=fake_resp):
        assert llm.is_available() is True


def test_is_available_false_ollama(monkeypatch):
    from engine import llm
    monkeypatch.setattr(llm, "PROVIDER", "ollama")
    monkeypatch.setattr(llm, "OLLAMA_URL", "http://fake")
    monkeypatch.setattr(llm, "_openrouter_key", lambda: "")
    with mock.patch("urllib.request.urlopen",
                    side_effect=Exception("connection refused")):
        assert llm.is_available() is False


def test_is_available_openrouter(monkeypatch):
    from engine import llm
    monkeypatch.setattr(llm, "PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "_openrouter_key", lambda: "sk-or-test")
    assert llm.is_available() is True
    monkeypatch.setattr(llm, "_openrouter_key", lambda: "")
    assert llm.is_available() is False


def test_tool_schema_basic():
    from engine import llm, tools
    tools.bootstrap()
    schema = llm.tool_schema(tools.all_tools())
    names = {t["function"]["name"] for t in schema}
    assert "go_to_place" in names
    assert "vote_on_proposal" in names
    vote_tool = next(t for t in schema
                     if t["function"]["name"] == "vote_on_proposal")
    assert vote_tool["function"]["parameters"]["properties"]["vote"]["enum"] == ["for", "against"]


def test_decide_tool_parses_response(monkeypatch):
    from engine import llm
    fake = {
        "message": {
            "tool_calls": [
                {"function": {"name": "go_to_place",
                              "arguments": {"place": "library"}}}
            ]
        }
    }
    monkeypatch.setattr(llm, "PROVIDER", "ollama")
    with mock.patch.object(llm, "chat_ollama", return_value=fake):
        name, args, meta = llm.decide_tool(
            [{"role": "user", "content": "x"}], tools=[],
            agent_id="anchor",
        )
    assert name == "go_to_place"
    assert args == {"place": "library"}
    assert meta["provider"] == "ollama"


def test_decide_tool_handles_string_args(monkeypatch):
    from engine import llm
    fake = {"message": {"tool_calls": [
        {"function": {"name": "idle", "arguments": "{}"}}
    ]}}
    monkeypatch.setattr(llm, "PROVIDER", "ollama")
    with mock.patch.object(llm, "chat_ollama", return_value=fake):
        name, args, _ = llm.decide_tool([], tools=[], agent_id="anchor")
    assert name == "idle"
    assert args == {}


def test_decide_tool_no_tool_call_returns_none(monkeypatch):
    from engine import llm
    fake = {"message": {"content": "I think... no tool"}}
    monkeypatch.setattr(llm, "PROVIDER", "ollama")
    with mock.patch.object(llm, "chat_ollama", return_value=fake):
        name, args, _ = llm.decide_tool([], tools=[], agent_id="anchor")
    assert name is None
    assert args is None


def test_decide_tool_openrouter_response(monkeypatch):
    from engine import llm
    fake = {
        "choices": [{"message": {"tool_calls": [
            {"function": {"name": "go_to_place", "arguments": {"place": "town_hall"}}}
        ]}}],
        "usage": {"total_tokens": 50, "cost": 0.0001},
    }
    monkeypatch.setattr(llm, "PROVIDER", "openrouter")
    with mock.patch.object(llm, "chat_openrouter", return_value=fake):
        name, args, meta = llm.decide_tool([], tools=[], agent_id="anchor")
    assert name == "go_to_place"
    assert args == {"place": "town_hall"}
    assert meta["provider"] == "openrouter"
    assert meta["cost_usd"] == 0.0001


def test_per_agent_model_override(monkeypatch):
    """EMERGENCE_AGENT_<ID>_MODEL env var overrides the default."""
    from engine import llm
    # Wipe any per-agent env vars that .env may have set
    for aid in ("ANCHOR", "FLORA", "LOVELY", "SPARK"):
        monkeypatch.delenv(f"EMERGENCE_AGENT_{aid}_MODEL", raising=False)
    monkeypatch.setattr(llm, "PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "OPENROUTER_MODEL", "anthropic/claude-3.5-haiku")
    monkeypatch.setenv("EMERGENCE_AGENT_ANCHOR_MODEL", "openai/gpt-4o-mini")
    assert llm.model_for_agent("anchor") == "openai/gpt-4o-mini"
    assert llm.model_for_agent("flora") == "anthropic/claude-3.5-haiku"


def test_provider_info(monkeypatch):
    from engine import llm
    monkeypatch.setattr(llm, "PROVIDER", "openrouter")
    monkeypatch.setattr(llm, "OPENROUTER_MODEL", "anthropic/claude-3.5-haiku")
    monkeypatch.setattr(llm, "_openrouter_key", lambda: "sk-or-x")
    info = llm.provider_info()
    assert info["provider"] == "openrouter"
    assert info["model"] == "anthropic/claude-3.5-haiku"
    assert info["openrouter_configured"] is True


def test_reasoning_uses_llm_when_available(tmp_db, monkeypatch):
    """If the LLM is reachable and returns a valid tool, reasoning uses it."""
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(reasoning, "USE_LLM", True)
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    with mock.patch.object(
        llm_mod, "decide_tool",
        return_value=("go_to_place", {"place": "library"},
                     {"provider": "ollama", "model": "llama3.2:3b",
                      "latency_s": 1.2, "cost_usd": None}),
    ):
        a = agents_mod.get("anchor")
        name, args, rat = reasoning.decide(a)
    assert name == "go_to_place"
    assert args == {"place": "library"}
    assert "llm" in rat
    last = reasoning.get_last_decision()
    assert last["mode"] == "llm"
    assert last["model"] == "llama3.2:3b"


def test_reasoning_falls_back_on_unknown_tool(tmp_db, monkeypatch):
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(reasoning, "USE_LLM", True)
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    with mock.patch.object(
        llm_mod, "decide_tool",
        return_value=("teleport_to_mars", {}, {"provider": "x", "model": "x", "latency_s": 0}),
    ):
        a = agents_mod.get("anchor")
        name, _, _ = reasoning.decide(a)
    assert name in {t.name for t in __import__("engine").tools.all_tools()}
    assert reasoning.get_last_decision()["mode"].startswith("fallback")


def test_reasoning_falls_back_on_wrong_location(tmp_db, monkeypatch):
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(reasoning, "USE_LLM", True)
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    with mock.patch.object(
        llm_mod, "decide_tool",
        return_value=("submit_townhall_proposal", {"title": "x", "body": "y"},
                     {"provider": "x", "model": "x", "latency_s": 0}),
    ):
        a = agents_mod.get("anchor")
        name, _, _ = reasoning.decide(a)
    assert name != "submit_townhall_proposal"
    assert reasoning.get_last_decision()["mode"].startswith("fallback")


def test_reasoning_falls_back_on_connection_error(tmp_db, monkeypatch):
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(reasoning, "USE_LLM", True)
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    with mock.patch.object(
        llm_mod, "decide_tool",
        side_effect=ConnectionError("ollama down"),
    ):
        a = agents_mod.get("anchor")
        name, _, _ = reasoning.decide(a)
    assert name in {t.name for t in __import__("engine").tools.all_tools()}


def test_env_var_disables_llm(monkeypatch, tmp_db):
    from engine import reasoning, agents as agents_mod, llm as llm_mod
    monkeypatch.setattr(llm_mod, "is_available", lambda: True)
    monkeypatch.setattr(reasoning, "USE_LLM", False)
    a = agents_mod.get("anchor")
    name, _, _ = reasoning.decide(a)
    assert reasoning.get_last_decision()["mode"] == "rule"
