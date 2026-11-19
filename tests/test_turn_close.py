import json
from pathlib import Path

from semantica.context import ContextGraph

from semantica_agent.agent.spool import Spool
from semantica_agent.agent.trace import validate_trace
from semantica_agent.agent.turn_close import INTERRUPTED_MESSAGE, close_turn
from semantica_agent.review.flow import replay

SESSION = {
    "model_requested": "claude-sonnet-5-5",
    "prompt_path": "src/semantica_agent/agent/prompts/agent.md",
    "prompt_hash": "abc",
    "ontology_info": {"commit": None, "dirty": None, "version_info": None},
    "runtime": {"kind": "claude-code", "cli_version": "2.1.325"},
}
ANSWER = {
    "answer": "答え",
    "claims": [
        {"text": "答え", "kind": "fact", "nodes": ["MARRIAGE-S8"], "downgraded_reason": None}
    ],
    "submitted": True,
}


def transcript(tmp_path: Path, lines: list[tuple[str, str, str]]) -> Path:
    p = tmp_path / "t.jsonl"
    rows = [
        {
            "type": "assistant",
            "timestamp": ts,
            "message": {"model": "claude-sonnet-5-5", "content": [{"type": kind, kind: text}]},
        }
        for ts, kind, text in lines
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), "utf-8")
    return p


def setup(tmp_path, *, with_state=True, tx=None):
    s = Spool(tmp_path / "cc", "sid")
    s.write_session(SESSION)
    turn = s.begin_turn("問い", str(tx) if tx else None)
    info = {**s.current_turn(), "started": "2026-11-19T01:59:00+00:00"}
    (s.dir / "turn.json").write_text(json.dumps(info), "utf-8")  # 発言の時刻を固定する
    s.append_event(turn, {"type": "user", "text": "問い", "time": "2026-11-19T02:00:00+00:00"})
    if with_state:
        s.append_event(
            turn,
            {
                "type": "tool_call",
                "tool": "run_cq",
                "args": {"number": 1},
                "tool_use_id": "tu1",
                "via": "hook",
                "time": "2026-11-19T02:00:02+00:00",
            },
        )
        s.append_event(
            turn,
            {
                "seq": 1,
                "type": "tool_result",
                "tool": "run_cq",
                "result": {},
                "nodes": ["MARRIAGE-S8"],
                "flow": {"referenced": ["MARRIAGE-S8"]},
                "is_error": False,
                "time": "2026-11-19T02:00:03+00:00",
            },
        )
        s.write_state(
            turn,
            {
                "judged": False,
                "judgment": None,
                "case": None,
                "answer": ANSWER,
                "case_states": {},
                "initial_case_states": {},
            },
        )
    return s, turn


def test_close_turn_builds_valid_trace(tmp_path):
    tx = transcript(tmp_path, [("2026-11-19T02:00:05Z", "text", "答え")])
    s, turn = setup(tmp_path, tx=tx)
    path = close_turn(s, turn, tmp_path / "traces")
    trace = json.loads(path.read_text("utf-8"))
    validate_trace(trace)
    assert trace["runtime"]["kind"] == "claude-code"
    assert [e["seq"] for e in trace["events"]] == list(range(1, len(trace["events"]) + 1))
    assert trace["model"] == {"requested": "claude-sonnet-5-5", "responded": "claude-sonnet-5-5"}
    assert trace["answer"]["submitted"] and trace["status"] == "ok"


def test_close_turn_orders_by_time(tmp_path):
    tx = transcript(
        tmp_path,
        [("2026-11-19T02:00:01Z", "thinking", "考え"), ("2026-11-19T02:00:05Z", "text", "答え")],
    )
    s, turn = setup(tmp_path, tx=tx)
    trace = json.loads(close_turn(s, turn, tmp_path / "traces").read_text("utf-8"))
    types = [e["type"] for e in trace["events"]]
    assert types == ["user", "thinking", "tool_call", "tool_result", "assistant_text"]


def test_close_turn_without_tool_calls(tmp_path):
    s, turn = setup(tmp_path)
    prev = {"BIRTH-S2-I8": {"state": "finding"}}
    s.write_state(turn, {**s.read_state(turn), "case_states": prev})
    close_turn(s, turn, tmp_path / "traces")
    t2 = s.begin_turn("聞き返し", None)
    s.append_event(t2, {"type": "user", "text": "聞き返し", "time": "2026-11-19T03:00:00+00:00"})
    path = close_turn(s, t2, tmp_path / "traces", last_message="何日ですか")
    trace = json.loads(path.read_text("utf-8"))
    assert trace["answer"]["submitted"] is False and trace["answer"]["answer"] == "何日ですか"
    assert trace["flow_initial"] == prev and trace["status"] == "ok"


def test_interrupted_turn_is_error(tmp_path):
    s, turn = setup(tmp_path)
    trace = json.loads(
        close_turn(s, turn, tmp_path / "traces", interrupted=True).read_text("utf-8")
    )
    assert trace["status"] == "error"
    assert trace["events"][-1] == {
        **trace["events"][-1],
        "type": "error",
        "message": INTERRUPTED_MESSAGE,
    }


def test_close_turn_twice_saves_once(tmp_path):
    s, turn = setup(tmp_path)
    assert close_turn(s, turn, tmp_path / "traces") is not None
    assert s.is_done(turn)
    assert close_turn(s, turn, tmp_path / "traces") is None


def test_existing_decisions_are_loaded(tmp_path, monkeypatch):
    loaded = []
    real = ContextGraph.load_from_file

    def spy(self, path):
        loaded.append(path)
        return real(self, path)

    monkeypatch.setattr(ContextGraph, "load_from_file", spy)
    s, turn = setup(tmp_path)
    folder = tmp_path / "traces/sid"
    folder.mkdir(parents=True)
    ContextGraph().save_to_file(str(folder / "decisions.json"))
    close_turn(s, turn, tmp_path / "traces")
    assert loaded == [str(folder / "decisions.json")]


def test_falls_back_to_last_message(tmp_path):
    s, turn = setup(tmp_path)
    s.write_state(turn, {**s.read_state(turn), "answer": None})
    trace = json.loads(
        close_turn(s, turn, tmp_path / "traces", last_message="最後").read_text("utf-8")
    )
    texts = [e["text"] for e in trace["events"] if e["type"] == "assistant_text"]
    assert texts == ["最後"] and trace["answer"]["answer"] == "最後"


def test_replayed_flow_matches(tmp_path):
    s, turn = setup(tmp_path)
    trace = json.loads(close_turn(s, turn, tmp_path / "traces").read_text("utf-8"))
    assert replay(trace["events"], trace["flow_initial"]) == trace["flow"]
    assert trace["flow"]["MARRIAGE-S8"]["state"] == "referenced"


def test_last_message_added_when_transcript_lacks_it(tmp_path):
    tx = transcript(tmp_path, [("2026-11-19T02:00:01Z", "text", "途中")])
    s, turn = setup(tmp_path, tx=tx)
    trace = json.loads(
        close_turn(s, turn, tmp_path / "traces", last_message="最後").read_text("utf-8")
    )
    texts = [e["text"] for e in trace["events"] if e["type"] == "assistant_text"]
    assert texts == ["途中", "最後"]


def test_last_message_not_duplicated(tmp_path):
    tx = transcript(tmp_path, [("2026-11-19T02:00:05Z", "text", "最後")])
    s, turn = setup(tmp_path, tx=tx)
    trace = json.loads(
        close_turn(s, turn, tmp_path / "traces", last_message="最後").read_text("utf-8")
    )
    assert [e["text"] for e in trace["events"] if e["type"] == "assistant_text"] == ["最後"]
