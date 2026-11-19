import json
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from semantica_agent.core.settings import load_settings
from semantica_agent.web import app as web


class FakeSession:
    count = 0

    def __init__(self, events):
        FakeSession.count += 1
        self.session_id = f"fake{FakeSession.count}"
        self.events = events
        self.closed = False
        self.busy = False

    async def ask(self, text):
        for e in self.events:
            yield e

    async def close(self):
        self.closed = True


EVENTS = [
    {"seq": 1, "type": "user", "text": "q"},
    {"seq": 2, "type": "tool_result", "tool": "run_cq", "nodes": ["BIRTH-S7"],
     "flow": {"referenced": ["BIRTH-S7"]}},
    {"type": "turn_end", "trace_path": "x", "trace": {"flow_initial": {}}},
]  # fmt: skip


@pytest.fixture
def settings(tmp_path):
    return replace(load_settings({}), trace_root=tmp_path)


@pytest.fixture
def client(knowledge, settings):
    app = web.create_app(knowledge, settings, lambda: FakeSession(EVENTS))
    return TestClient(app)


def sse(client, sid, text="質問"):
    with client.stream("POST", f"/api/sessions/{sid}/messages", json={"text": text}) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[5:]) for line in r.iter_lines() if line.startswith("data:")]


def test_flow_endpoint(client):
    assert [s["number"] for s in client.get("/api/flow/birth").json()["steps"]] == list(range(1, 8))


def test_flow_unknown_business(client):
    assert client.get("/api/flow/adoption").status_code == 404


def test_message_streams_events_with_view(client):
    sid = client.post("/api/sessions").json()["session_id"]
    events = sse(client, sid)
    assert [e["type"] for e in events] == ["user", "tool_result", "turn_end"]
    view = events[1]["view"]
    assert view["flow"]["BIRTH-S7"]["state"] == "referenced"
    assert view["steps"]["birth"]["BIRTH-S7"] == "referenced"
    assert view["business"] == "birth"


def test_empty_text_rejected(client):
    sid = client.post("/api/sessions").json()["session_id"]
    assert client.post(f"/api/sessions/{sid}/messages", json={"text": " "}).status_code == 422


def test_busy_session_returns_409(client):
    sid = client.post("/api/sessions").json()["session_id"]
    client.app.state.sessions[sid].busy = True
    assert client.post(f"/api/sessions/{sid}/messages", json={"text": "q"}).status_code == 409


def test_unknown_session_404(client):
    assert client.post("/api/sessions/nope/messages", json={"text": "q"}).status_code == 404


def test_delete_session_closes(client):
    sid = client.post("/api/sessions").json()["session_id"]
    sess = client.app.state.sessions[sid]
    assert client.delete(f"/api/sessions/{sid}").status_code == 204
    assert sess.closed and sid not in client.app.state.sessions


def test_node_endpoint(client):
    assert client.get("/api/nodes/BIRTH-S2-I11").json()["label"] == "届出期間内の届出か。"
    assert client.get("/api/nodes/NOPE-1").status_code == 404


def _save(tmp_path, sid="s1", turn=1):
    events = [{"seq": 1, "time": "t", "type": "tool_result", "nodes": ["BIRTH-S7"],
               "flow": {"referenced": ["BIRTH-S7"]}}]  # fmt: skip
    trace = {
        "session_id": sid, "turn": turn, "question": "質問", "started": "2026-11-17T00:00:00",
        "status": "ok", "judgment": {"decision": "pending"}, "events": events,
        "flow_initial": {}, "business": "birth",
    }  # fmt: skip
    (tmp_path / sid).mkdir(exist_ok=True)
    (tmp_path / sid / f"{turn:03d}.json").write_text(json.dumps(trace), "utf-8")


def test_traces_list_and_get(client, tmp_path):
    _save(tmp_path)
    items = client.get("/api/traces").json()
    expected = {
        "session_id": "s1", "turn": 1, "question": "質問", "started": "2026-11-17T00:00:00",
        "status": "ok", "decision": "pending",
    }  # fmt: skip
    assert items == [expected]
    t = client.get("/api/traces/s1/1").json()
    assert t["timeline"][0]["flow"]["BIRTH-S7"]["state"] == "referenced"
    assert client.get("/api/traces/s1/9").status_code == 404


@pytest.mark.parametrize("sid", ["..", "a.b", "%2e%2e"])
def test_trace_path_traversal_rejected(client, sid):
    assert client.get(f"/api/traces/{sid}/1").status_code in (400, 404)


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "<title>" in r.text


def test_main_stops_on_missing_ontology(tmp_path, monkeypatch):
    monkeypatch.setattr(web.uvicorn, "run", lambda *a, **k: pytest.fail("起動してはいけない"))
    assert web.main(["--root", str(tmp_path)]) == 1


def test_main_stops_on_integrity_failure(monkeypatch):
    monkeypatch.setattr(web, "validate_integrity", lambda p: (False, "違反あり"))
    monkeypatch.setattr(web.uvicorn, "run", lambda *a, **k: pytest.fail("起動してはいけない"))
    assert web.main([]) == 1


def test_main_stops_on_api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert web.main([]) == 1


def test_binds_localhost_only(monkeypatch):
    seen = {}
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(web, "validate_integrity", lambda p: (True, ""))
    monkeypatch.setattr(web.uvicorn, "run", lambda app, **kw: seen.update(kw))
    assert web.main([]) == 0
    assert seen["host"] == "127.0.0.1" and seen["port"] == 8765


def test_index_references_local_assets_only(client):
    html = client.get("/").text
    assert "/static/app.js" in html and "/static/style.css" in html
    assert "http://" not in html and "https://" not in html


@pytest.mark.parametrize("name", ["app.js", "style.css"])
def test_static_assets_have_no_external_urls(client, name):
    r = client.get(f"/static/{name}")
    assert r.status_code == 200 and "http://" not in r.text and "https://" not in r.text


def test_saved_trace_fixture_replays(client, tmp_path):
    from semantica_agent.agent.trace import validate_trace

    src = json.loads((Path(__file__).parent / "fixtures/traces/demo-001.json").read_text("utf-8"))
    validate_trace(src)
    (tmp_path / "demo").mkdir()
    (tmp_path / "demo" / "001.json").write_text(json.dumps(src), "utf-8")
    t = client.get("/api/traces/demo/1").json()
    assert t["timeline"][-1]["flow"] == src["flow"]
    assert t["timeline"][-1]["steps"]["birth"]["BIRTH-S2"] == "finding"


def test_old_sessions_are_closed_over_limit(client, monkeypatch):
    monkeypatch.setattr(web, "MAX_SESSIONS", 2)
    ids = [client.post("/api/sessions").json()["session_id"] for _ in range(3)]
    sessions = client.app.state.sessions
    assert ids[0] not in sessions and set(ids[1:]) <= set(sessions)
