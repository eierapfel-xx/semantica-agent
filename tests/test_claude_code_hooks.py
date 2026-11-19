import json
from dataclasses import replace

import pytest

from semantica_agent.agent import claude_code
from semantica_agent.agent.claude_code import handle_hook
from semantica_agent.agent.spool import Spool
from semantica_agent.core.settings import load_settings

SID = "11111111-2222-3333-4444-555555555555"
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
def spool(settings):
    s = Spool(settings.spool_root, SID)
    s.write_session(SESSION)
    return s


ENV = {"KOSEKI_SESSION_ID": SID}


def payload(event: str, **kw) -> dict:
    return {
        "session_id": SID,
        "transcript_path": None,
        "cwd": "/x",
        "hook_event_name": event,
        **kw,
    }


def test_prompt_hook_starts_turn(settings, spool):
    assert handle_hook("prompt", payload("UserPromptSubmit", prompt="問い"), ENV, settings) == 0
    assert spool.current_turn()["turn"] == 1
    events = spool.read_events(1)
    assert [e["type"] for e in events] == ["user"] and events[0]["text"] == "問い"


def test_pre_tool_hook_records_koseki_only(settings, spool):
    handle_hook("prompt", payload("UserPromptSubmit", prompt="問い"), ENV, settings)
    for name in ("mcp__koseki__run_cq", "mcp__other__x"):
        p = payload("PreToolUse", tool_name=name, tool_input={"number": 1}, tool_use_id="tu1")
        assert handle_hook("pre-tool", p, ENV, settings) == 0
    calls = [e for e in spool.read_events(1) if e["type"] == "tool_call"]
    assert len(calls) == 1
    assert calls[0] | {"time": None} == {
        "type": "tool_call",
        "tool": "run_cq",
        "args": {"number": 1},
        "tool_use_id": "tu1",
        "via": "hook",
        "time": None,
    }


def test_hook_ignores_other_session(settings, spool, capsys):
    p = {**payload("UserPromptSubmit", prompt="問い"), "session_id": "other"}
    assert handle_hook("prompt", p, ENV, settings) == 0
    assert spool.current_turn() is None
    assert "セッション" in capsys.readouterr().err


def test_stop_hook_saves_trace(settings, spool):
    handle_hook("prompt", payload("UserPromptSubmit", prompt="問い"), ENV, settings)
    p = payload("Stop", last_assistant_message="答え", stop_hook_active=False)
    assert handle_hook("stop", p, ENV, settings) == 0
    trace = json.loads((settings.trace_root / SID / "001.json").read_text("utf-8"))
    assert trace["answer"]["answer"] == "答え" and trace["status"] == "ok"


def test_next_prompt_closes_open_turn(settings, spool):
    handle_hook("prompt", payload("UserPromptSubmit", prompt="一"), ENV, settings)
    handle_hook("prompt", payload("UserPromptSubmit", prompt="二"), ENV, settings)
    trace = json.loads((settings.trace_root / SID / "001.json").read_text("utf-8"))
    assert trace["status"] == "error"
    assert spool.current_turn()["turn"] == 2 and spool.open_turns() == [2]


def test_hook_error_is_logged_not_raised(settings, spool, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("壊れた")

    monkeypatch.setattr(claude_code, "close_turn", boom)
    handle_hook("prompt", payload("UserPromptSubmit", prompt="問い"), ENV, settings)
    assert handle_hook("stop", payload("Stop"), ENV, settings) == 0
    assert "壊れた" in (spool.dir / "hook-errors.log").read_text("utf-8")


def test_unknown_hook_name_is_logged(settings, spool):
    assert handle_hook("bogus", payload("X"), ENV, settings) == 0
    assert "bogus" in (spool.dir / "hook-errors.log").read_text("utf-8")


def test_main_hook_reads_stdin(settings, spool, monkeypatch):
    import io

    monkeypatch.setenv("KOSEKI_SESSION_ID", SID)
    monkeypatch.setenv("KOSEKI_SPOOL_ROOT", str(settings.spool_root))
    monkeypatch.setenv("KOSEKI_TRACE_ROOT", str(settings.trace_root))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    data = json.dumps(payload("UserPromptSubmit", prompt="問い"))
    monkeypatch.setattr("sys.stdin", io.StringIO(data))
    assert claude_code.main(["hook", "prompt"]) == 0
    assert spool.current_turn()["question"] == "問い"


def test_main_hook_bad_json_does_not_block(settings, monkeypatch, capsys):
    import io

    monkeypatch.setenv("KOSEKI_SESSION_ID", SID)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert claude_code.main(["hook", "prompt"]) == 0
    assert "JSON" in capsys.readouterr().err


def test_pre_tool_other_session_is_denied(settings, spool, capsys):
    p = {
        **payload("PreToolUse", tool_name="mcp__koseki__run_cq", tool_input={}, tool_use_id="t"),
        "session_id": "other",
    }
    assert handle_hook("pre-tool", p, ENV, settings) == 0
    out = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert out["hookEventName"] == "PreToolUse" and out["permissionDecision"] == "deny"


def test_prompt_other_session_tells_user(settings, spool, capsys):
    p = {**payload("UserPromptSubmit", prompt="問い"), "session_id": "other"}
    handle_hook("prompt", p, ENV, settings)
    assert "記録" in json.loads(capsys.readouterr().out)["systemMessage"]


def test_failed_close_still_starts_new_turn(settings, spool, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("閉じられない")

    handle_hook("prompt", payload("UserPromptSubmit", prompt="一"), ENV, settings)
    monkeypatch.setattr(claude_code, "close_turn", boom)
    handle_hook("prompt", payload("UserPromptSubmit", prompt="二"), ENV, settings)
    assert spool.current_turn()["turn"] == 2
    assert spool.open_turns() == [2]
    assert "閉じられない" in (spool.dir / "hook-errors.log").read_text("utf-8")
