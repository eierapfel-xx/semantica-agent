from pathlib import Path

from semantica_agent.agent.transcript import TurnMessages, read_turn_messages

FIXTURE = Path(__file__).parent / "fixtures/claude_code/transcript.jsonl"
SINCE = "2026-11-19T01:59:59+00:00"


def test_reads_text_and_thinking_after_since():
    m = read_turn_messages(FIXTURE, SINCE)
    got = [(i.type, i.text) for i in m.items]
    assert got == [("thinking", "考え"), ("assistant_text", "今の答え")]
    assert m.model == "claude-sonnet-5-5"
    assert m.items[0].time == "2026-11-19T02:00:01+00:00"


def test_reads_unknown_lines_safely():
    m = read_turn_messages(FIXTURE, "2026-11-19T00:00:00+00:00")
    assert [i.text for i in m.items] == ["前のターンの答え", "考え", "今の答え"]


def test_missing_file_is_empty(tmp_path):
    assert read_turn_messages(tmp_path / "none.jsonl", SINCE) == TurnMessages([], None)
    assert read_turn_messages(None, SINCE) == TurnMessages([], None)
