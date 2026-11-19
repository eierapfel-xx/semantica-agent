"""Claude Code 版の起動と hook の処理。仕様（2026-11-19）§5.1・§5.3。

起動：`claude-code-agent/run.sh [質問]`（中身は `... claude_code launch`）。
hook：`uv run python -m semantica_agent.agent.claude_code hook <prompt|pre-tool|stop>`
（stdin に Claude Code の hook の JSON）。hook の失敗はターンを止めない。
"""

import argparse
import functools
import hashlib
import json
import logging
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import claude_agent_sdk

from semantica_agent.agent.session import PROMPT_PATH, TOOL_NAMES, render_prompt
from semantica_agent.agent.spool import Spool, now
from semantica_agent.agent.tools import Knowledge
from semantica_agent.agent.trace import ontology_info
from semantica_agent.agent.turn_close import close_turn
from semantica_agent.core.paths import REPO_ROOT
from semantica_agent.core.settings import ConfigError, Settings, configure_logging, load_settings
from semantica_agent.core.turtle_io import validate_integrity

logger = logging.getLogger(__name__)

MCP_PREFIX = "mcp__koseki__"
AGENT_DIR = REPO_ROOT / "claude-code-agent"
SDK_DIR = Path(claude_agent_sdk.__file__).parent
ISOLATION_ENV = {"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}
Runner = Callable[..., subprocess.CompletedProcess]


def bundled_cli(sdk_dir: Path | None = None) -> Path:
    path = (sdk_dir or SDK_DIR) / "_bundled" / "claude"
    if not path.exists():
        raise ConfigError(
            f"Agent SDK 同梱の Claude Code が見つかりません: {path}。uv sync を確かめてください"
        )
    return path


@functools.cache
def bundled_cli_version(cli: Path | None = None) -> str | None:
    try:
        cli = cli or bundled_cli()
        out = subprocess.run([str(cli), "--version"], capture_output=True, text=True, timeout=30)
        return out.stdout.split()[0] if out.returncode == 0 and out.stdout.strip() else None
    except (ConfigError, OSError, subprocess.SubprocessError) as e:
        logger.warning("同梱の Claude Code の版を取れません: %s", e)
        return None


def installed_plugin_ids(cli: Path, run: Runner = subprocess.run) -> list[str]:
    out = run([str(cli), "plugin", "list", "--json"], capture_output=True, text=True)
    if out.returncode != 0:
        raise ConfigError(f"インストール済みのプラグインの一覧を取れません: {out.stderr.strip()}")
    try:
        ids = [p["id"] for p in json.loads(out.stdout)]
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        raise ConfigError(f"プラグインの一覧の形が読めません: {e}") from e
    return list(dict.fromkeys(ids))


@dataclass(frozen=True)
class LaunchPlan:
    cli: Path
    argv: list[str]
    env: dict[str, str]
    cwd: Path
    session_id: str
    prompt_file: Path


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else REPO_ROOT / path


def build_launch_plan(
    settings: Settings,
    session_id: str,
    prompt_file: Path,
    plugin_ids: list[str],
    question: str | None,
    base_env: Mapping[str, str],
    cli: Path,
) -> LaunchPlan:
    plugins = json.dumps({"enabledPlugins": {p: False for p in plugin_ids}})
    argv = [
        str(cli),
        "--session-id", session_id,
        "--model", settings.agent_model,
        "--system-prompt-file", str(prompt_file),
        "--tools", "",
        "--strict-mcp-config", "--mcp-config", ".mcp.json",
        "--setting-sources", "project",
        "--disable-slash-commands",
        "--allowedTools", "mcp__koseki__*",
        "--permission-mode", "dontAsk",
        "--settings", plugins,
    ]  # fmt: skip
    if question:
        argv += ["-p", question, "--max-turns", str(settings.agent_max_turns)]
    env = {
        **base_env,
        **ISOLATION_ENV,
        "KOSEKI_SESSION_ID": session_id,
        "KOSEKI_REPO_ROOT": str(REPO_ROOT),
        "KOSEKI_SPOOL_ROOT": str(_absolute(settings.spool_root)),
        "KOSEKI_TRACE_ROOT": str(_absolute(settings.trace_root)),
    }
    return LaunchPlan(cli, argv, env, AGENT_DIR, session_id, prompt_file)


def _close_open_turns(spool: Spool, trace_root: Path) -> None:
    """Stop が届かなかったターンを閉じる。閉じられないターンは印を付けて先へ進む。"""
    for turn in spool.open_turns():
        try:
            close_turn(spool, turn, trace_root, interrupted=True)
        except Exception as e:  # 1 つの失敗で以降のターンの記録を止めない
            logger.exception("ターン %d を閉じられません", turn)
            spool.log_error(f"ターン {turn} を閉じられません: {type(e).__name__}: {e}")
            spool.mark_failed(turn)


def _on_prompt(spool: Spool, payload: dict, settings: Settings) -> None:
    _close_open_turns(spool, settings.trace_root)
    prompt = payload.get("prompt", "")
    turn = spool.begin_turn(prompt, payload.get("transcript_path"))
    spool.append_event(turn, {"type": "user", "text": prompt, "time": now()})


def _on_pre_tool(spool: Spool, payload: dict, settings: Settings) -> None:
    name = payload.get("tool_name", "").removeprefix(MCP_PREFIX)
    cur = spool.current_turn()
    if name not in TOOL_NAMES or cur is None:
        return
    event = {
        "type": "tool_call",
        "tool": name,
        "args": payload.get("tool_input", {}),
        "tool_use_id": payload.get("tool_use_id"),
        "via": "hook",
        "time": now(),
    }
    spool.append_event(cur["turn"], event)


def _on_stop(spool: Spool, payload: dict, settings: Settings) -> None:
    cur = spool.current_turn()
    if cur is not None:
        last = payload.get("last_assistant_message")
        close_turn(spool, cur["turn"], settings.trace_root, last_message=last)


HOOKS = {"prompt": _on_prompt, "pre-tool": _on_pre_tool, "stop": _on_stop}
OTHER_SESSION = (
    "koseki: 会話のセッション ID が起動時と変わったので（/clear・/resume など）、記録できません。"
    "run.sh から起動し直してください"
)


def _refuse_other_session(name: str, session_id: str | None) -> None:
    """記録できない会話では、ツールを止め、利用者に知らせる（hook の stdout の JSON）。"""
    print(f"{OTHER_SESSION}（{session_id}）", file=sys.stderr)
    if name == "pre-tool":
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": OTHER_SESSION,
            }
        }
    else:
        out = {"systemMessage": OTHER_SESSION}
    print(json.dumps(out, ensure_ascii=False))


def handle_hook(name: str, payload: dict, env: Mapping[str, str], settings: Settings) -> int:
    sid = env.get("KOSEKI_SESSION_ID", "")
    if not sid or payload.get("session_id") != sid:
        _refuse_other_session(name, payload.get("session_id"))
        return 0
    spool = Spool(settings.spool_root, sid)
    try:
        if name not in HOOKS:
            raise ValueError(f"知らない hook です: {name}")
        HOOKS[name](spool, payload, settings)
    except Exception as e:  # hook の失敗でターンを止めない。記録だけ残す
        logger.exception("hook %s が失敗しました", name)
        spool.log_error(f"hook {name}: {type(e).__name__}: {e}")
    return 0


def _prepare(settings: Settings, today: date) -> tuple[Spool, Path]:
    """相談の置き場を作り、システムプロンプトと相談の情報を書く。"""
    Knowledge.load(REPO_ROOT)  # 読めないオントロジーなら起動しない
    conforms, text = validate_integrity(REPO_ROOT / "ontology")
    if not conforms:
        raise ConfigError(f"オントロジーの整合性の検証で違反があります\n{text}")
    spool = Spool(_absolute(settings.spool_root), str(uuid.uuid4()))
    template = PROMPT_PATH.read_text("utf-8")
    spool.dir.mkdir(parents=True, exist_ok=True)
    prompt_file = spool.dir / "prompt.md"
    prompt_file.write_text(render_prompt(template, today), encoding="utf-8")
    spool.write_session(
        {
            "model_requested": settings.agent_model,
            "prompt_path": str(PROMPT_PATH.relative_to(REPO_ROOT)),
            "prompt_hash": hashlib.sha256(template.encode()).hexdigest(),
            "ontology_info": ontology_info(REPO_ROOT),
            "runtime": {"kind": "claude-code", "cli_version": bundled_cli_version()},
        }
    )
    return spool, prompt_file


def launch(
    argv: list[str] | None = None,
    env: Mapping[str, str] = os.environ,
    run: Runner = subprocess.run,
    today: date | None = None,
) -> int:
    question = " ".join(argv or []).strip() or None
    try:
        settings = load_settings(env)
        configure_logging(settings)
        cli = bundled_cli()
        plugins = installed_plugin_ids(cli, run)
        spool, prompt_file = _prepare(settings, today or date.today())
    except (ConfigError, FileNotFoundError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    plan = build_launch_plan(settings, spool.session_id, prompt_file, plugins, question, env, cli)
    logger.info("Claude Code 版を起動します（相談 %s）", plan.session_id)
    code = run(plan.argv, env=plan.env, cwd=plan.cwd).returncode
    trace_root = _absolute(settings.trace_root)
    _close_open_turns(spool, trace_root)  # Stop が届かないまま終わったターン
    print(f"トレース: {trace_root / plan.session_id}", file=sys.stderr)
    return code


def _hook_main(name: str) -> int:
    try:
        payload = json.loads(sys.stdin.read())
        settings = load_settings()
    except (json.JSONDecodeError, ConfigError) as e:
        print(f"koseki: hook {name} を処理できません（JSON か設定の誤り）: {e}", file=sys.stderr)
        return 0
    configure_logging(settings)
    return handle_hook(name, payload, os.environ, settings)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="semantica_agent.agent.claude_code")
    sub = p.add_subparsers(dest="command", required=True)
    h = sub.add_parser("hook", help="Claude Code の hook から呼ぶ")
    h.add_argument("name", choices=sorted(HOOKS))
    lp = sub.add_parser("launch", help="Claude Code 版を起動する（質問を渡すと 1 問で終わる）")
    lp.add_argument("question", nargs="*")
    args = p.parse_args(argv)
    if args.command == "launch":
        return launch(args.question)
    return _hook_main(args.name)


if __name__ == "__main__":
    raise SystemExit(main())
