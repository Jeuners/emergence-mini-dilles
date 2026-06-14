"""LLM client for Emergence-Mini.

Supports Ollama's /api/chat endpoint with native tool-calling.
If the model does not support tool-calling, the client falls back to a
JSON-mode call where the model is asked to emit a single JSON object.

Configuration via environment variables:
- EMERGENCE_LLM_URL       (default: http://127.0.0.1:11434)
- EMERGENCE_LLM_MODEL     (default: llama3.2:3b)
- EMERGENCE_LLM_TIMEOUT   (default: 30 seconds)
- EMERGENCE_LLM_ENABLED   (default: 1) - set to 0 to disable and force the
                          rule-based engine even when reasoning.py is asked
                          for the LLM path.
"""
import json
import os
import time
import urllib.error
import urllib.request

URL = os.environ.get("EMERGENCE_LLM_URL", "http://127.0.0.1:11434")
DEFAULT_MODEL = os.environ.get("EMERGENCE_LLM_MODEL", "llama3.2:3b")
TIMEOUT = float(os.environ.get("EMERGENCE_LLM_TIMEOUT", "30"))
ENABLED = os.environ.get("EMERGENCE_LLM_ENABLED", "1") != "0"


def tool_schema(tools):
    """Convert the engine's Tool dataclasses to Ollama's tool-calling schema.

    The format follows OpenAI's function-calling spec, which Ollama accepts.
    """
    out = []
    for t in tools:
        props = _args_schema(t)
        out.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": [k for k, v in props.items() if "default" not in v],
                },
            },
        })
    return out


def _args_schema(tool):
    """Best-effort JSON schema for the args each tool accepts. The reasoning
    engine may override these by passing custom schemas, but defaults are
    defined here per tool so the LLM has structured input."""
    schemas = {
        "go_to_place": {"place": {"type": "string", "description": "Landmark id"}},
        "go_home": {},
        "say_to_agent": {
            "target": {"type": "string", "description": "Agent id"},
            "text": {"type": "string", "description": "Message text"},
        },
        "speak_to_all": {"text": {"type": "string", "description": "Broadcast text"}},
        "show_emoticon": {"emoticon": {"type": "string", "description": "Emoji"}},
        "idle": {},
        "recharge_energy": {},
        "add_to_longterm_memory": {"content": {"type": "string", "description": "Memory text"}},
        "write_blog": {
            "title": {"type": "string"},
            "body": {"type": "string"},
        },
        "add_to_billboard": {"text": {"type": "string"}},
        "read_billboard": {},
        "submit_townhall_proposal": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "category": {"type": "string", "default": "general"},
        },
        "vote_on_proposal": {
            "proposal_id": {"type": "integer"},
            "vote": {"type": "string", "enum": ["for", "against"]},
        },
        "list_agents": {},
        "list_landmarks": {},
    }
    return schemas.get(tool.name, {})


def is_available(url=None):
    """Check whether the Ollama server is reachable."""
    url = url or URL
    try:
        req = urllib.request.Request(f"{url}/api/tags", method="GET")
        urllib.request.urlopen(req, timeout=2)
        return True
    except Exception:
        return False


def chat(messages, tools=None, model=None, url=None, timeout=None, temperature=0.2):
    """Send a chat request to Ollama. Returns parsed JSON dict from the API.

    Raises urllib.error.URLError on connection failure, ValueError on parse
    failure.
    """
    url = url or URL
    model = model or DEFAULT_MODEL
    timeout = timeout or TIMEOUT
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": temperature},
    }
    if tools:
        payload["tools"] = tools
        payload["format"] = "json"  # hint for tool output
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def decide_tool(messages, tools=None, model=None, url=None, timeout=None, temperature=0.2):
    """High-level helper: send a chat, return (tool_name, args_dict) or None.

    Returns None if the model produces no tool calls. Raises on connection
    failure.
    """
    response = chat(messages, tools=tools, model=model, url=url,
                    timeout=timeout, temperature=temperature)
    msg = response.get("message", {})
    calls = msg.get("tool_calls") or []
    if calls:
        fn = calls[0].get("function", {})
        name = fn.get("name")
        args = fn.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {}
        return name, args
    return None, None
