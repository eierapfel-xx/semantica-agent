from dataclasses import replace
from datetime import date

import pytest

from semantica_agent.agent.session import (
    TOOL_NAMES,
    ReviewSession,
    fallback_answer,
    render_prompt,
    tool_specs,
)
from semantica_agent.agent.trace import validate_trace
from semantica_agent.core.settings import load_settings

SDK_RUNTIME = {"kind": "agent-sdk", "cli_version": None}


@pytest.fixture
def settings(tmp_path):
    return replace(load_settings({}), trace_root=tmp_path)


def make(knowledge, settings, **kw):
    return ReviewSession(knowledge, settings, "s1", date(2026, 11, 19), SDK_RUNTIME, **kw)


async def test_call_tool_records_call_and_result(knowledge, settings):
    s = make(knowledge, settings)
    s.start_turn("問い")
    out = await s.call_tool("search_nodes", {"text": "出生"})
    assert not out.is_error
    assert [e["type"] for e in s.recorder.events] == ["user", "tool_call", "tool_result"]
    assert s.recorder.events[1]["via"] == "handler"


async def test_record_tool_calls_false_skips_handler_call(knowledge, settings):
    s = make(knowledge, settings, record_tool_calls=False)
    s.start_turn("問い")
    await s.call_tool("search_nodes", {"text": "出生"})
    assert [e["type"] for e in s.recorder.events] == ["user", "tool_result"]


async def test_start_turn_without_user_event(knowledge, settings):
    s = make(knowledge, settings)
    s.start_turn("問い", record_user=False)
    assert s.recorder.events == [] and s.state.turn == 1


async def test_hook_call_is_not_duplicated(knowledge, settings):
    s = make(knowledge, settings)
    s.start_turn("問い")
    s.record_tool_call("search_nodes", {"text": "出生"}, "tu1", "hook")
    await s.call_tool("search_nodes", {"text": "出生"})
    calls = [e for e in s.recorder.events if e["type"] == "tool_call"]
    assert len(calls) == 1 and calls[0]["via"] == "hook"


async def test_on_event_receives_every_event(knowledge, settings):
    got = []
    s = make(knowledge, settings, on_event=got.append)
    s.start_turn("問い")
    await s.call_tool("search_nodes", {"text": "出生"})
    assert got == s.recorder.events


async def test_tool_error_is_recorded(knowledge, settings):
    s = make(knowledge, settings)
    s.start_turn("問い")
    out = await s.call_tool("describe_node", {"node_id": "NO-SUCH-NODE"})
    assert out.is_error
    assert s.recorder.events[-1]["type"] == "tool_result" and s.recorder.events[-1]["is_error"]


def test_finish_turn_includes_runtime(knowledge, settings):
    s = make(knowledge, settings)
    s.start_turn("問い")
    trace = s.finish_turn(["答え"], "claude-sonnet-5-5", "ok")
    assert trace["runtime"] == SDK_RUNTIME
    validate_trace(trace)
    assert s.save_turn(trace).exists()


def test_tool_specs_match_tool_names(knowledge):
    specs = tool_specs(knowledge)
    assert set(specs) == set(TOOL_NAMES)
    assert all(isinstance(d, str) and s["type"] == "object" for d, s in specs.values())


def test_render_prompt_inserts_today():
    assert render_prompt("今日は {today}", date(2026, 11, 19)) == "今日は 2026-11-19"


def test_fallback_answer_is_speculation():
    a = fallback_answer(["前", "最後"])
    assert a["answer"] == "最後" and not a["submitted"]
    assert a["claims"][0]["kind"] == "speculation"
