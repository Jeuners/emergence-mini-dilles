"""LLM client for Emergence-Mini.

Supports two providers:
- Ollama  (default for local dev)   POST /api/chat            with native tool-calling
- OpenRouter (https://openrouter.ai) POST /api/v1/chat/completions  OpenAI-compatible

Auto mode picks OpenRouter when OPENROUTER_API_KEY is set, otherwise Ollama.
Per-agent model assignment is configured in `models_for_agent()` and read from
env vars of the form EMERGENCE_AGENT_<ID>_MODEL.

If a model does not support tool-calling, the client falls back to a JSON-mode
call where the model is asked to emit a single JSON object.

Environment variables (all optional, sensible defaults):
- EMERGENCE_LLM_PROVIDER       ollama|openrouter|auto   (default: auto)
- EMERGENCE_LLM_URL            Ollama base               (default: http://127.0.0.1:11434)
- EMERGENCE_OLLAMA_MODEL       default Ollama model      (default: llama3.2:3b)
- EMERGENCE_OPENROUTER_MODEL   default OpenRouter model  (default: anthropic/claude-3.5-haiku)
- EMERGENCE_OPENROUTER_KEY     OpenRouter API key        (or OPENROUTER_API_KEY)
- EMERGENCE_LLM_TIMEOUT        seconds                   (default: 30)
- EMERGENCE_LLM_ENABLED        0 disables the LLM path   (default: 1)
"""
import json
import os
import time
import urllib.error
import urllib.request

# Load .env if present (so EMERGENCE_LLM_* work without manual export)
def _load_dotenv():
    from pathlib import Path
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            v = v.strip()
            # skip empty values; an empty .env line should not blank out a
            # value already provided by the shell.
            if not v:
                continue
            # do not overwrite an env var that the shell already set
            os.environ.setdefault(k.strip(), v)
_load_dotenv()


def _provider():
    p = os.environ.get("EMERGENCE_LLM_PROVIDER", "auto").lower()
    if p == "auto":
        if os.environ.get("OPENROUTER_API_KEY") or os.environ.get("EMERGENCE_OPENROUTER_KEY"):
            return "openrouter"
        return "ollama"
    return p if p in ("ollama", "openrouter") else "ollama"


PROVIDER = _provider()
OLLAMA_URL = os.environ.get("EMERGENCE_OLLAMA_URL",
                            os.environ.get("EMERGENCE_LLM_URL", "http://127.0.0.1:11434"))
OLLAMA_FALLBACK_URL = os.environ.get("EMERGENCE_OLLAMA_FALLBACK_URL", OLLAMA_URL)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
OLLAMA_MODEL = os.environ.get("EMERGENCE_OLLAMA_MODEL", "llama3.2:3b")
OPENROUTER_MODEL = os.environ.get("EMERGENCE_OPENROUTER_MODEL", "anthropic/claude-3.5-haiku")
TIMEOUT = float(os.environ.get("EMERGENCE_LLM_TIMEOUT", "30"))
ENABLED = os.environ.get("EMERGENCE_LLM_ENABLED", "1") != "0"


def _openrouter_key():
    return (os.environ.get("EMERGENCE_OPENROUTER_KEY")
            or os.environ.get("OPENROUTER_API_KEY") or "")


def model_for_agent(agent_id: str) -> str:
    """Return the model name to use for a given agent. Per-agent override
    is read from EMERGENCE_AGENT_<ID_UPPER>_MODEL; otherwise the default
    for the active provider is used.
    """
    env_key = f"EMERGENCE_AGENT_{agent_id.upper()}_MODEL"
    override = os.environ.get(env_key)
    if override:
        return override
    return OPENROUTER_MODEL if PROVIDER == "openrouter" else OLLAMA_MODEL


def provider_for_model(model: str) -> str:
    """Heuristic: a model name containing '/' is an OpenRouter-style slug
    (org/model). Bare names without '/' (llama3.2:3b, gemma3, mistral) are
    served by Ollama.
    """
    if "/" in model:
        return "openrouter"
    return "ollama"


def provider_for_agent(agent_id: str) -> str:
    """Pick the provider for a specific agent based on its model name.
    Falls back to the global PROVIDER if the model name is ambiguous.
    """
    model = model_for_agent(agent_id)
    return provider_for_model(model)


def default_model() -> str:
    return model_for_agent("default")


def tool_schema(tools):
    """Convert the engine's Tool dataclasses to OpenAI/Ollama's tool-calling
    schema. The format is identical for both providers."""
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
    """Compact JSON schema for each tool's args. The schema is sent on
    every LLM call, so we keep descriptions short.
    """
    schemas = {
        "go_to_place": {"place": {"type": "string"}},
        "go_home": {},
        "say_to_agent": {"target": {"type": "string"}, "text": {"type": "string"}},
        "speak_to_all": {"text": {"type": "string"}},
        "show_emoticon": {"emoticon": {"type": "string"}},
        "idle": {},
        "recharge_energy": {},
        "add_to_longterm_memory": {"content": {"type": "string"}},
        "write_blog": {"title": {"type": "string"}, "body": {"type": "string"}},
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


# -------- Provider availability --------

def is_available():
    if PROVIDER == "openrouter":
        return bool(_openrouter_key())
    # Try primary Ollama, then fallback
    for url in (OLLAMA_URL, OLLAMA_FALLBACK_URL):
        if not url:
            continue
        try:
            req = urllib.request.Request(f"{url}/api/tags", method="GET")
            urllib.request.urlopen(req, timeout=2)
            return True
        except Exception:
            continue
    return False


# -------- Chat calls --------

def chat_ollama(messages, tools, model, timeout):
    last_err = None
    for url in (OLLAMA_URL, OLLAMA_FALLBACK_URL):
        if not url or url == OLLAMA_URL and OLLAMA_FALLBACK_URL == OLLAMA_URL:
            urls = [url]
        else:
            urls = [url]
        # Try primary, then fallback (if different)
        pass
    # Try each URL in order
    for url in (OLLAMA_URL, OLLAMA_FALLBACK_URL):
        if not url:
            continue
        try:
            payload = {
                "model": model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": 0.2},
            }
            if tools:
                payload["tools"] = tools
                payload["format"] = "json"
            req = urllib.request.Request(
                f"{url}/api/chat",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            last_err = e
            continue
    raise last_err or RuntimeError("no Ollama URL configured")


def chat_openrouter(messages, tools, model, timeout):
    key = _openrouter_key()
    if not key:
        raise RuntimeError("OPENROUTER_API_KEY not set")
    payload = {
        "model": model,
        "messages": messages,
        # Tight token budget — tool calls need only ~30 tokens; reasoning
        # text before the tool call is usually 20-60 tokens. 256 is plenty.
        "max_tokens": 256,
        "temperature": 0.2,
    }
    if tools:
        payload["tools"] = tools
    req = urllib.request.Request(
        OPENROUTER_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
            "HTTP-Referer": "https://github.com/Jeuners/emergence-mini-dilles",
            "X-Title": "Emergence-Mini",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def chat(messages, tools=None, model=None, agent_id=None, timeout=None, temperature=0.2):
    """Send a chat request. Returns parsed JSON dict from the provider API.

    Raises on connection failure or non-2xx HTTP.
    """
    timeout = timeout or TIMEOUT
    model = model or (model_for_agent(agent_id) if agent_id else default_model())
    if PROVIDER == "openrouter":
        return chat_openrouter(messages, tools or [], model, timeout)
    return chat_ollama(messages, tools or [], model, timeout)


def decide_tool(messages, tools=None, agent_id=None, model=None, timeout=None):
    """High-level helper. Returns (tool_name, args_dict, meta) or (None, None, meta).

    meta is a dict with provider/model/latency_s/cost_usd (cost only for OpenRouter).
    """
    t0 = time.time()
    model = model or (model_for_agent(agent_id) if agent_id else default_model())
    # Per-agent provider: if the model name looks like an OpenRouter slug
    # ('org/model'), route to OpenRouter regardless of the global PROVIDER.
    provider = provider_for_model(model)
    if provider == "openrouter" and not _openrouter_key():
        return None, None, {"error": "OPENROUTER_API_KEY not set", "provider": provider,
                            "model": model, "latency_s": time.time() - t0}
    try:
        if provider == "openrouter":
            response = chat_openrouter(messages, tools or [], model, timeout or TIMEOUT)
        else:
            response = chat_ollama(messages, tools or [], model, timeout or TIMEOUT)
    except Exception as e:
        return None, None, {"error": str(e), "provider": provider, "model": model,
                            "latency_s": time.time() - t0}
    latency = time.time() - t0

    cost = None
    if provider == "openrouter":
        cost = response.get("usage", {}).get("cost")

    if provider == "openrouter":
        msg = response.get("choices", [{}])[0].get("message", {})
    else:
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
        return name, args, {"provider": provider, "model": model,
                            "latency_s": latency, "cost_usd": cost}
    return None, None, {"provider": provider, "model": model,
                        "latency_s": latency, "cost_usd": cost}
    return None, None, {"provider": PROVIDER, "model": model,
                        "latency_s": latency, "cost_usd": cost}


def provider_info():
    """Return a short summary of the active provider for /api/state and the UI."""
    return {
        "provider": PROVIDER,
        "model": default_model(),
        "openrouter_configured": bool(_openrouter_key()),
        "ollama_url": OLLAMA_URL,
        "ollama_fallback_url": OLLAMA_FALLBACK_URL,
    }
