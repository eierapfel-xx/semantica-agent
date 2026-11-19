import json
import os
import sys
from dataclasses import replace
from datetime import date

import pytest
from case_helpers import full_args

from semantica_agent.agent.claude_code import handle_hook
from semantica_agent.agent.mcp_server import (
    SpoolBackedSession,
    call_tool_result,
    list_tools_result,
)
from semantica_agent.agent.session import tool_specs
from semantica_agent.agent.spool import Spool
from semantica_agent.agent.trace import validate_trace
from semantica_agent.core.paths import REPO_ROOT
from semantica_agent.core.settings import load_settings

SID = "11111111-2222-3333-4444-555555555555"
ENV = {"KOSEKI_SESSION_ID": SID}
LATE = "2026年11月2日生まれ、11月20日に母が届出"
SESSION = {
    "model_requested": "claude-sonnet-5-5",
    "prompt_path": "p",
    "prompt_hash": "h",
    "ontology_info": {"commit": None, "dirty": None, "version_info": None},
    "runtime": {"kind": "claude-code", "cli_version": None},
}


@pytest.fixture
def settings(tmp_path):
    return replace(load_settings({}), spool_root=tmp_path / "cc", trace_root=tmp_path / "traces")


@pytest.fixture
def sess(knowledge, settings):
    spool = Spool(settings.spool_root, SID)
    spool.write_session(SESSION)
    return SpoolBackedSession(knowledge, settings, spool, date(2026, 11, 19))


def quoted(**changes):
    args = full_args(**changes)
    return {k: {**v, "quote": "11月20日"} if "quote" in v else v for k, v in args.items()}


def hook(name, settings, **kw):
    p = {"session_id": SID, "transcript_path": None, "cwd": "/x", "hook_event_name": name, **kw}
    assert handle_hook(name, p, ENV, settings) == 0


def test_tool_list_matches_sdk(knowledge):
    tools = list_tools_result(knowledge).tools
    specs = tool_specs(knowledge)
    assert {t.name: (t.description, t.input_schema) for t in tools} == specs


async def test_call_tool_follows_spool_turn(sess, settings):
    hook("prompt", settings, prompt="出生の手順")
    out = await sess.call_tool("search_nodes", {"text": "出生"})
    assert not out.is_error
    events = sess.spool.read_events(1)
    assert [e["type"] for e in events] == ["user", "tool_result"]
    assert sess.spool.read_state(1)["judged"] is False
    assert sess.review.state.turn == 1


async def test_call_tool_without_turn_is_error(sess):
    out = await sess.call_tool("search_nodes", {"text": "出生"})
    assert out.is_error and "ターン" in out.text


async def test_call_tool_result_wraps_outcome(sess, settings):
    hook("prompt", settings, prompt="問い")
    res = await call_tool_result(sess, "describe_node", {"node_id": "NO-SUCH"})
    assert res.is_error and res.content[0].text.startswith("エラー")


async def test_two_turns_end_to_end(sess, settings):
    hook("prompt", settings, prompt=LATE)
    args = quoted(filingDate="2026-11-20")
    hook(
        "pre-tool",
        settings,
        tool_name="mcp__koseki__judge_birth_case",
        tool_input=args,
        tool_use_id="tu1",
    )
    assert not (await sess.call_tool("judge_birth_case", args)).is_error
    answer = {
        "answer": "届出期間を過ぎています。",
        "claims": [{"text": "期間", "kind": "rule", "nodes": ["RULE-BIRTH-FILING-PERIOD"]}],
    }
    await sess.call_tool("submit_answer", answer)
    hook("stop", settings, last_assistant_message="届出期間を過ぎています。")
    hook("prompt", settings, prompt="ありがとう")
    hook("stop", settings, last_assistant_message="どういたしまして")
    t1, t2 = (
        json.loads((settings.trace_root / SID / f"00{n}.json").read_text("utf-8")) for n in (1, 2)
    )
    for t in (t1, t2):
        validate_trace(t)
        assert t["runtime"]["kind"] == "claude-code"
    assert t1["judgment"] is not None and t1["answer"]["submitted"]
    assert [e["via"] for e in t1["events"] if e["type"] == "tool_call"] == ["hook"]
    assert t2["flow_initial"] == sess.review.state.last_case_states != {}
    assert (settings.trace_root / SID / "decisions.json").exists()


@pytest.mark.slow
async def test_stdio_server_answers_list_tools(tmp_path):
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    spool = Spool(tmp_path / "cc", SID)
    spool.write_session(SESSION)
    env = {
        **os.environ,
        "KOSEKI_SESSION_ID": SID,
        "KOSEKI_SPOOL_ROOT": str(tmp_path / "cc"),
        "KOSEKI_TRACE_ROOT": str(tmp_path / "traces"),
    }
    env.pop("ANTHROPIC_API_KEY", None)
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "semantica_agent.agent.mcp_server"],
        env=env,
        cwd=str(REPO_ROOT),
    )
    async with stdio_client(params) as (r, w), ClientSession(r, w) as client:
        await client.initialize()
        names = {t.name for t in (await client.list_tools()).tools}
    assert len(names) == 6 and "judge_birth_case" in names


async def test_call_tool_after_turn_done_is_refused(sess, settings):
    hook("prompt", settings, prompt="問い")
    await sess.call_tool("search_nodes", {"text": "出生"})
    hook("stop", settings, last_assistant_message="答え")
    before = sess.spool.read_events(1)
    out = await sess.call_tool("search_nodes", {"text": "出生"})  # /clear 後の別の会話から
    assert out.is_error and sess.spool.read_events(1) == before
