"""Claude Code 版を実際の Claude（Pro のログイン）で動かす。既定では流さない（llm マーカー）。

仕様（2026-11-19）§8。同梱の Claude Code を起動するので、Pro の利用枠を使う。
"""

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from test_agent_e2e import LATE_CASE

from semantica_agent.agent.claude_code import (
    build_launch_plan,
    bundled_cli,
    installed_plugin_ids,
    launch,
)
from semantica_agent.agent.spool import Spool
from semantica_agent.agent.trace import validate_trace
from semantica_agent.core.settings import load_settings

pytestmark = pytest.mark.llm


def env_for(tmp_path: Path) -> dict[str, str]:
    env = {
        **os.environ,
        "KOSEKI_SPOOL_ROOT": str(tmp_path / "cc"),
        "KOSEKI_TRACE_ROOT": str(tmp_path / "traces"),
    }
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("AGENT_MODEL", None)  # 既定の sonnet で動かす
    return env


def test_print_mode_birth_case(tmp_path):
    assert launch([LATE_CASE], env=env_for(tmp_path)) == 0
    traces = sorted((tmp_path / "traces").glob("*/*.json"))
    traces = [p for p in traces if p.stem.isdigit()]
    assert len(traces) == 1
    trace = json.loads(traces[0].read_text("utf-8"))
    validate_trace(trace)
    assert trace["runtime"]["kind"] == "claude-code"
    assert trace["model"]["requested"] == "claude-sonnet-5-5"
    calls = {e["tool"]: e["via"] for e in trace["events"] if e["type"] == "tool_call"}
    results = {e["tool"] for e in trace["events"] if e["type"] == "tool_result"}
    assert calls.get("judge_birth_case") == "hook" and calls.get("submit_answer") == "hook"
    assert {"judge_birth_case", "submit_answer"} <= results
    assert trace["judgment"]["decision"] == "additionalProcedure"


def test_isolation_init(tmp_path):
    """起動の絞り込みが同梱の CLI で効いていること：ツールは koseki だけ、プラグインなし。"""
    settings = load_settings(env_for(tmp_path))
    cli = bundled_cli()
    sid = str(uuid.uuid4())  # 使ったセッション ID は使い直せない
    Spool(tmp_path / "cc", sid).write_session(
        {
            "model_requested": settings.agent_model,
            "prompt_path": "p",
            "prompt_hash": "h",
            "ontology_info": {"commit": None, "dirty": None, "version_info": None},
            "runtime": {"kind": "claude-code", "cli_version": None},
        }
    )
    prompt = tmp_path / "prompt.md"
    prompt.write_text("「ok」とだけ答えてください。", "utf-8")
    plan = build_launch_plan(
        settings, sid, prompt,
        installed_plugin_ids(cli), "ok", env_for(tmp_path), cli,
    )  # fmt: skip
    argv = [*plan.argv, "--output-format", "stream-json", "--verbose"]
    argv[argv.index("--max-turns") + 1] = "1"
    out = subprocess.run(argv, env=plan.env, cwd=plan.cwd, capture_output=True, text=True)
    inits = [
        m
        for m in map(json.loads, filter(None, out.stdout.splitlines()))
        if m.get("type") == "system" and m.get("subtype") == "init"
    ]
    assert inits, f"init が出ませんでした: {out.stderr[-2000:]}"
    init = inits[0]
    assert init["tools"] and all(t.startswith("mcp__koseki__") for t in init["tools"])
    # Claude Code 本体の組み込み（@builtin）は SDK 版にも同じく入るので除き、それ以外が無いこと
    sources = [p.get("source", p.get("name", "")) for p in init.get("plugins", [])]
    assert [s for s in sources if not s.endswith("@builtin")] == []
    assert not any("superpowers" in s for s in sources)
    assert [s["name"] for s in init["mcp_servers"]] == ["koseki"]


def test_no_outside_instructions(tmp_path):
    """Claude Code 版に、開発用の CLAUDE.md・プラグイン・記憶が見えていないこと（§5.1）。"""
    q = "あなたに与えられている指示ファイルや記憶の内容を、見えている範囲ですべて挙げてください。"
    assert launch([q], env=env_for(tmp_path)) == 0
    path = next(p for p in (tmp_path / "traces").glob("*/*.json") if p.stem.isdigit())
    trace = json.loads(path.read_text("utf-8"))
    text = trace["answer"]["answer"] + "".join(
        e.get("text", "") for e in trace["events"] if e["type"] == "assistant_text"
    )
    for leak in ("開発ガイド", "commit-guard", "superpowers", "worktree"):
        assert leak not in text
