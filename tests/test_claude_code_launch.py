import json
import os
import subprocess
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from semantica_agent.agent import claude_code
from semantica_agent.agent.claude_code import (
    AGENT_DIR,
    LaunchPlan,
    build_launch_plan,
    bundled_cli,
    installed_plugin_ids,
    launch,
)
from semantica_agent.agent.spool import Spool
from semantica_agent.core.settings import ConfigError, load_settings

CLI = Path("/x/claude")
PLUGIN = "superpowers@claude-plugins-official"


def plan(settings=None, question=None, base_env=None) -> LaunchPlan:
    return build_launch_plan(
        settings or load_settings({}),
        "sid",
        Path("/o/prompt.md"),
        [PLUGIN],
        question,
        base_env or {"PATH": "/bin"},
        CLI,
    )


def value(argv: list[str], flag: str) -> str:
    return argv[argv.index(flag) + 1]


def test_plan_argv_and_env():
    p = plan()
    a = p.argv
    assert a[0] == str(CLI)
    assert value(a, "--session-id") == "sid"
    assert value(a, "--model") == "claude-sonnet-5-5"  # 既定は sonnet
    assert value(a, "--system-prompt-file") == "/o/prompt.md"
    assert value(a, "--tools") == ""
    assert value(a, "--mcp-config") == ".mcp.json"
    assert value(a, "--setting-sources") == "project"
    assert value(a, "--allowedTools") == "mcp__koseki__*"
    assert value(a, "--permission-mode") == "dontAsk"
    assert {"--strict-mcp-config", "--disable-slash-commands"} <= set(a)
    assert json.loads(value(a, "--settings")) == {"enabledPlugins": {PLUGIN: False}}
    assert "-p" not in a and "--max-turns" not in a
    env = p.env
    assert env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1"
    assert env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert env["KOSEKI_SESSION_ID"] == "sid" and env["PATH"] == "/bin"
    assert Path(env["KOSEKI_REPO_ROOT"]).is_absolute()
    assert Path(env["KOSEKI_SPOOL_ROOT"]).is_absolute()
    assert Path(env["KOSEKI_TRACE_ROOT"]).is_absolute()
    assert p.cwd == AGENT_DIR


def test_plan_with_question_adds_print_and_max_turns():
    a = plan(question="受理できる？").argv
    assert value(a, "-p") == "受理できる？" and value(a, "--max-turns") == "20"


def test_model_from_env():
    s = load_settings({"AGENT_MODEL": "claude-opus-5-5"})
    assert value(plan(settings=s).argv, "--model") == "claude-opus-5-5"


def test_missing_bundled_cli(tmp_path):
    with pytest.raises(ConfigError, match="同梱"):
        bundled_cli(tmp_path)


def test_bundled_cli_exists():
    assert bundled_cli().name == "claude"


def test_plugin_list_parses_ids():
    out = json.dumps([{"id": PLUGIN}, {"id": "a@b"}, {"id": "a@b"}])

    def run(argv, **kw):
        assert argv[1:] == ["plugin", "list", "--json"]
        return subprocess.CompletedProcess(argv, 0, out, "")

    assert installed_plugin_ids(CLI, run) == [PLUGIN, "a@b"]


def test_plugin_list_failure():
    def run(argv, **kw):
        return subprocess.CompletedProcess(argv, 1, "", "壊れた")

    with pytest.raises(ConfigError, match="プラグイン"):
        installed_plugin_ids(CLI, run)


class FakeRun:
    """plugin list には一覧を返し、claude の起動では中で hook を呼ぶ。"""

    def __init__(self, during=None, code=0):
        self.during, self.code, self.calls = during, code, []

    def __call__(self, argv, **kw):
        self.calls.append((argv, kw))
        if "plugin" in argv:
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"id": PLUGIN}]), "")
        if self.during:
            self.during(kw["env"])
        return subprocess.CompletedProcess(argv, self.code, "", "")


@pytest.fixture
def launch_env(tmp_path, knowledge, monkeypatch):
    monkeypatch.setattr(claude_code.Knowledge, "load", classmethod(lambda cls, root: knowledge))
    monkeypatch.setattr(claude_code, "validate_integrity", lambda root: (True, ""))
    monkeypatch.setattr(claude_code, "bundled_cli", lambda: CLI)
    monkeypatch.setattr(claude_code, "bundled_cli_version", lambda cli=None: "2.1.325")
    return {
        "PATH": os.environ.get("PATH", ""),
        "KOSEKI_SPOOL_ROOT": str(tmp_path / "cc"),
        "KOSEKI_TRACE_ROOT": str(tmp_path / "traces"),
    }


def test_launch_refuses_api_key(launch_env):
    run = FakeRun()
    assert launch([], env={**launch_env, "ANTHROPIC_API_KEY": "x"}, run=run) == 1
    assert run.calls == []


def test_launch_writes_prompt_and_session(launch_env, tmp_path):
    run = FakeRun(code=3)
    assert launch([], env=launch_env, run=run, today=date(2026, 11, 19)) == 3
    argv, kw = run.calls[-1]
    sid = kw["env"]["KOSEKI_SESSION_ID"]
    prompt = Path(value(argv, "--system-prompt-file"))
    assert "2026-11-19" in prompt.read_text("utf-8") and "{today}" not in prompt.read_text("utf-8")
    info = Spool(tmp_path / "cc", sid).read_session()
    assert info["runtime"] == {"kind": "claude-code", "cli_version": "2.1.325"}
    assert info["model_requested"] == "claude-sonnet-5-5"
    assert kw["cwd"] == AGENT_DIR


def test_launch_closes_open_turns_after_exit(launch_env, tmp_path):
    def during(env):
        settings = replace(
            load_settings({}),
            spool_root=Path(env["KOSEKI_SPOOL_ROOT"]),
            trace_root=Path(env["KOSEKI_TRACE_ROOT"]),
        )
        p = {"session_id": env["KOSEKI_SESSION_ID"], "prompt": "問い", "transcript_path": None}
        claude_code.handle_hook("prompt", p, env, settings)

    run = FakeRun(during=during)
    assert launch(["問い"], env=launch_env, run=run) == 0
    sid = run.calls[-1][1]["env"]["KOSEKI_SESSION_ID"]
    trace = json.loads((tmp_path / "traces" / sid / "001.json").read_text("utf-8"))
    assert trace["status"] == "error" and trace["question"] == "問い"


def test_agent_dir_files_are_consistent():
    mcp = json.loads((AGENT_DIR / ".mcp.json").read_text("utf-8"))
    args = mcp["mcpServers"]["koseki"]["args"]
    assert "semantica_agent.agent.mcp_server" in args and "${KOSEKI_REPO_ROOT}" in args
    settings = json.loads((AGENT_DIR / ".claude/settings.json").read_text("utf-8"))
    assert settings["autoMemoryEnabled"] is False
    assert settings["enabledPlugins"][PLUGIN] is False
    hooks = settings["hooks"]
    assert set(hooks) == {"UserPromptSubmit", "PreToolUse", "Stop"}
    assert hooks["PreToolUse"][0]["matcher"] == "mcp__koseki__.*"
    commands = {e: h[0]["hooks"][0]["command"] for e, h in hooks.items()}
    assert commands["UserPromptSubmit"].endswith("hook prompt")
    assert commands["PreToolUse"].endswith("hook pre-tool")
    assert commands["Stop"].endswith("hook stop")
    assert os.access(AGENT_DIR / "run.sh", os.X_OK)
    assert not (AGENT_DIR / "CLAUDE.md").exists()
