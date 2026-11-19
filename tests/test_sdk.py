import json
from dataclasses import replace

import pytest
from case_helpers import full_args
from fake_sdk import assistant_error, fail, fake_factory, text, thinking, tool

from semantica_agent.agent.sdk import AgentSession, allowed_tool_names, build_options
from semantica_agent.core.settings import load_settings

LATE = "2026年11月2日生まれ、11月20日に母が届出"


@pytest.fixture
def settings(tmp_path):
    return replace(load_settings({}), trace_root=tmp_path)


def quoted(**changes):
    """引用をすべて LATE の一部にした、全項目の入力。"""
    args = full_args(**changes)
    return {k: {**v, "quote": "11月20日"} if "quote" in v else v for k, v in args.items()}


ANSWER = {
    "answer": "届出期間を過ぎています。",
    "claims": [{"text": "期間を過ぎた", "kind": "rule", "nodes": ["RULE-BIRTH-FILING-PERIOD"]}],
}


async def collect(sess, q):
    return [e async for e in sess.ask(q)]


async def test_turn_records_tool_events_and_saves(knowledge, settings, tmp_path):
    f = fake_factory(
        [
            thinking("考える"),
            tool("judge_birth_case", quoted(filingDate="2026-11-20")),
            tool("submit_answer", ANSWER),
            text("以上です"),
        ]
    )
    sess = AgentSession(knowledge, settings, client_factory=f, session_id="s1")
    events = await collect(sess, LATE)
    types = [e["type"] for e in events]
    assert types[0] == "user" and types[-1] == "turn_end"
    assert {"tool_call", "tool_result", "answer", "thinking", "assistant_text"} <= set(types)
    trace = events[-1]["trace"]
    assert trace["judgment"]["decision"] == "additionalProcedure"
    assert trace["answer"]["claims"][0]["kind"] == "rule" and trace["answer"]["submitted"]
    assert trace["case"]["fields"] and trace["flow"]["BIRTH-S2-I11"]["state"] == "finding"
    assert trace["model"]["responded"] == "claude-sonnet-5-5"
    saved = json.loads((tmp_path / "s1" / "001.json").read_text("utf-8"))
    assert saved["turn"] == 1 and (tmp_path / "s1" / "decisions.json").exists()
    call = next(e for e in events if e["type"] == "tool_call")
    assert call["tool"] == "judge_birth_case" and call.get("via") == "hook"


async def test_tool_error_is_returned_not_raised(knowledge, settings):
    bad = {"childBirthDate": {"status": "given", "value": "2026-11-02", "quote": "言っていない"}}
    f = fake_factory([tool("judge_birth_case", bad), text("聞き返します")])
    events = await collect(AgentSession(knowledge, settings, client_factory=f), LATE)
    res = next(e for e in events if e["type"] == "tool_result")
    assert res["is_error"] and "childBirthDate" in res["result"]["error"]
    assert events[-1]["trace"]["status"] == "ok"


async def test_turn_without_submit_answer(knowledge, settings):
    f = fake_factory([text("たぶん受理できます")])
    trace = (await collect(AgentSession(knowledge, settings, client_factory=f), "質問"))[-1][
        "trace"
    ]
    assert trace["answer"]["submitted"] is False
    assert trace["answer"]["answer"] == "たぶん受理できます"
    assert trace["answer"]["claims"][0]["kind"] == "speculation"


@pytest.mark.parametrize("step", [fail("boom"), assistant_error("rate_limit")])
async def test_sdk_error_is_saved(knowledge, settings, tmp_path, step):
    f = fake_factory([text("途中"), step])
    sess = AgentSession(knowledge, settings, client_factory=f, session_id="e1")
    trace = (await collect(sess, "質問"))[-1]["trace"]
    assert trace["status"] == "error" and any(e["type"] == "error" for e in trace["events"])
    assert (tmp_path / "e1" / "001.json").exists()


async def test_second_turn_sees_previous_utterance(knowledge, settings):
    args = {"childBirthDate": {"status": "given", "value": "2026-11-02", "quote": "11月2日生まれ"}}
    f = fake_factory([text("出生日は？")], [tool("judge_birth_case", args), text("保留")])
    sess = AgentSession(knowledge, settings, client_factory=f)
    await collect(sess, "11月2日生まれ")
    events = await collect(sess, "母が届出")
    res = next(e for e in events if e["type"] == "tool_result")
    assert not res["is_error"] and res["result"]["decision"] == "pending"
    assert events[-1]["trace"]["turn"] == 2


async def test_flow_initial_carries_previous_case_states(knowledge, settings):
    f = fake_factory(
        [tool("judge_birth_case", quoted(filingDate="2026-11-20"))],
        [tool("describe_node", {"node_id": "BIRTH-S2-I1"})],
    )
    sess = AgentSession(knowledge, settings, client_factory=f)
    await collect(sess, LATE)
    trace = (await collect(sess, "届出地の根拠は？"))[-1]["trace"]
    assert trace["judgment"] is None
    assert trace["flow_initial"]["BIRTH-S2-I11"]["state"] == "finding"
    assert trace["flow"]["BIRTH-S2-I11"]["state"] == "finding"


async def test_close_disconnects(knowledge, settings):
    f = fake_factory([text("a")])
    sess = AgentSession(knowledge, settings, client_factory=f)
    await collect(sess, "q")
    await sess.close()
    assert f.created[0].connected is False


def test_options_disable_builtin_tools(knowledge, settings):
    sess = AgentSession(knowledge, settings, client_factory=fake_factory())
    o = build_options(sess)
    assert o.tools == [] and o.setting_sources == []
    assert set(o.allowed_tools) == set(allowed_tool_names())
    assert o.model == "claude-sonnet-5-5" and o.max_turns == 20
    assert "2026" in o.system_prompt or "{today}" not in o.system_prompt
    assert set(o.hooks) == {"PreToolUse", "PostToolUse"}


async def test_default_client_is_blocked_in_tests(knowledge, settings):
    sess = AgentSession(knowledge, settings, session_id="b1")
    trace = (await collect(sess, "q"))[-1]["trace"]
    assert trace["status"] == "error"
    assert "llm マーカー" in next(e for e in trace["events"] if e["type"] == "error")["message"]


async def test_result_error_marks_turn_failed(knowledge, settings):
    from fake_sdk import result_error

    f = fake_factory([text("途中まで"), result_error("error_max_turns")])
    trace = (await collect(AgentSession(knowledge, settings, client_factory=f), "q"))[-1]["trace"]
    assert trace["status"] == "error"
    err = next(e for e in trace["events"] if e["type"] == "error")
    assert "error_max_turns" in err["message"]


async def test_unexpected_tool_exception_is_recorded(knowledge, settings, monkeypatch):
    from fake_sdk import crash_tool

    import semantica_agent.agent.session as agent_mod

    def boom(*a, **k):
        raise KeyError("壊れた")

    monkeypatch.setattr(agent_mod, "describe_node", boom)
    f = fake_factory([crash_tool("describe_node", {"node_id": "BIRTH-S2-I1"}), text("続き")])
    trace = (await collect(AgentSession(knowledge, settings, client_factory=f), "q"))[-1]["trace"]
    res = next(e for e in trace["events"] if e["type"] == "tool_result")
    assert res["is_error"] and trace["status"] == "error"
    assert any(e["type"] == "error" and "KeyError" in e["message"] for e in trace["events"])


async def test_cancelled_turn_saves_trace_and_resets_client(knowledge, settings, tmp_path):
    import asyncio

    from fake_sdk import cancel

    f = fake_factory([text("途中"), cancel()], [text("次")])
    sess = AgentSession(knowledge, settings, client_factory=f, session_id="c1")
    with pytest.raises(asyncio.CancelledError):
        await collect(sess, "q")
    saved = json.loads((tmp_path / "c1" / "001.json").read_text("utf-8"))
    assert saved["status"] == "error"
    assert f.created[0].connected is False and sess.busy is False
    # 次のターンは新しいクライアントで始める（前のターンの応答の残りを読まない）
    events = await collect(sess, "続き")
    assert len(f.created) == 2 and events[-1]["trace"]["turn"] == 2


async def test_concurrent_ask_is_rejected(knowledge, settings):
    sess = AgentSession(knowledge, settings, client_factory=fake_factory([text("a")]))
    sess.busy = True
    events = await collect(sess, "q")
    assert [e["type"] for e in events] == ["error"]


def test_options_disable_claude_md_and_memory(knowledge, settings):
    sess = AgentSession(knowledge, settings, client_factory=fake_factory())
    env = build_options(sess).env
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"


async def test_trace_runtime_is_agent_sdk(knowledge, settings):
    f = fake_factory([text("a")])
    trace = (await collect(AgentSession(knowledge, settings, client_factory=f), "q"))[-1]["trace"]
    assert trace["runtime"]["kind"] == "agent-sdk"
