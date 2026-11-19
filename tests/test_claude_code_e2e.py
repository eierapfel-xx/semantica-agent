"""Claude Code 版を実際の Claude（Pro のログイン）で動かす。既定では流さない（llm マーカー）。

仕様（2026-11-19）§8。同梱の Claude Code を起動するので、Pro の利用枠を使う。
"""

import json
import os
import subprocess
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
    sid = "00000000-0000-4000-8000-000000000001"
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
    init = next(
        m
        for m in map(json.loads, filter(None, out.stdout.splitlines()))
        if m.get("type") == "system" and m.get("subtype") == "init"
    )
    assert init["tools"] and all(t.startswith("mcp__koseki__") for t in init["tools"])
    assert init.get("plugins", []) == []
    assert [s["name"] for s in init["mcp_servers"]] == ["koseki"]
