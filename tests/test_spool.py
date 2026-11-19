from semantica_agent.agent.spool import Spool


def spool(tmp_path):
    return Spool(tmp_path, "sid")


def test_begin_turn_counts_up(tmp_path):
    s = spool(tmp_path)
    assert s.current_turn() is None
    assert s.begin_turn("一", "/t.jsonl") == 1
    assert s.begin_turn("二", None) == 2
    cur = s.current_turn()
    assert cur["turn"] == 2 and cur["question"] == "二" and cur["started"]
    assert cur["transcript_path"] is None


def test_session_round_trip(tmp_path):
    s = spool(tmp_path)
    s.write_session({"model_requested": "m"})
    assert s.read_session() == {"model_requested": "m"}


def test_events_round_trip(tmp_path):
    s = spool(tmp_path)
    s.append_event(1, {"type": "user", "text": "あ"})
    s.append_event(1, {"type": "tool_call", "tool": "run_cq"})
    assert [e["type"] for e in s.read_events(1)] == ["user", "tool_call"]
    assert s.read_events(2) == []


def test_open_turns_and_done(tmp_path):
    s = spool(tmp_path)
    s.append_event(1, {"type": "user"})
    s.append_event(2, {"type": "user"})
    s.mark_done(1)
    assert s.is_done(1) and not s.is_done(2)
    assert s.open_turns() == [2]


def test_state_and_last_case_states(tmp_path):
    s = spool(tmp_path)
    assert s.read_state(1) is None
    s.write_state(1, {"case_states": {"A": {"state": "finding"}}})
    assert s.read_state(1)["case_states"] == {"A": {"state": "finding"}}
    assert s.last_case_states(3) == {"A": {"state": "finding"}}
    assert s.last_case_states(1) == {}


def test_log_error_appends(tmp_path):
    s = spool(tmp_path)
    s.log_error("一")
    s.log_error("二")
    text = (s.dir / "hook-errors.log").read_text("utf-8")
    assert "一" in text and "二" in text
