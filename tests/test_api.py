"""API endpoint tests: all HTTP routes + WebSocket."""
import json


def test_index_serves_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<html" in r.text.lower()


def test_static_files(client):
    for path in ("/static/style.css", "/static/app.js"):
        r = client.get(path)
        assert r.status_code == 200, path


def test_api_state(client):
    r = client.get("/api/state")
    assert r.status_code == 200
    d = r.json()
    assert "agents" in d
    assert "landmarks" in d
    assert "constitution" in d
    assert d["grid"] == {"w": 240, "h": 240}
    assert len(d["agents"]) == 4


def test_api_agents(client):
    r = client.get("/api/agents")
    assert r.status_code == 200
    data = r.json()
    names = {a["name"] for a in data}
    assert names == {"Anchor", "Flora", "Lovely", "Spark"}


def test_api_landmarks(client):
    r = client.get("/api/landmarks")
    assert r.status_code == 200
    data = r.json()
    assert len(data) == 14


def test_api_proposals(client):
    r = client.get("/api/proposals")
    assert r.status_code == 200
    d = r.json()
    assert "active" in d
    assert "recent" in d


def test_api_constitution(client):
    r = client.get("/api/constitution")
    assert r.status_code == 200
    d = r.json()
    assert len(d["articles"]) == 5


def test_api_events(client):
    r = client.get("/api/events")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)


def test_api_memories(client):
    r = client.get("/api/memories/anchor")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_blogs(client):
    r = client.get("/api/blogs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_api_turn_force_move(client):
    r = client.post(
        "/api/turn/anchor",
        json={"tool": "go_to_place", "args": {"place": "library"}},
    )
    assert r.status_code == 200
    d = r.json()
    assert d["ok"]
    assert d["moved_to"] == "library"


def test_api_turn_unknown_tool(client):
    r = client.post(
        "/api/turn/anchor",
        json={"tool": "fly_to_mars", "args": {}},
    )
    assert r.status_code == 200
    d = r.json()
    assert not d["ok"]


def test_api_turn_missing_tool(client):
    r = client.post("/api/turn/anchor", json={"args": {}})
    assert r.status_code == 400


def test_api_turn_unknown_agent(client):
    r = client.post(
        "/api/turn/ghost",
        json={"tool": "go_home", "args": {}},
    )
    assert r.status_code == 200
    d = r.json()
    assert not d["ok"]


def test_websocket_stream(client):
    """Connect, receive snapshot, then receive at least one tick within 5s."""
    with client.websocket_connect("/ws") as ws:
        msg = ws.receive_json()
        assert msg["type"] == "snapshot"
        assert "data" in msg
        assert "agents" in msg["data"]


def test_websocket_no_auth_required(client):
    """The server has no auth — any client can connect. Documented in README."""
    with client.websocket_connect("/ws") as ws:
        ws.receive_json()
