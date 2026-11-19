"""Claude Code 版の hook の処理と起動。仕様（2026-11-19）§5.1・§5.3。

hook：`uv run python -m semantica_agent.agent.claude_code hook <prompt|pre-tool|stop>`
（stdin に Claude Code の hook の JSON）。hook の失敗はターンを止めない。
"""

import argparse
import json
import logging
import os
import sys
from collections.abc import Mapping

from semantica_agent.agent.session import TOOL_NAMES
from semantica_agent.agent.spool import Spool, now
from semantica_agent.agent.turn_close import close_turn
from semantica_agent.core.settings import ConfigError, Settings, configure_logging, load_settings

logger = logging.getLogger(__name__)

MCP_PREFIX = "mcp__koseki__"


def _on_prompt(spool: Spool, payload: dict, settings: Settings) -> None:
    for turn in spool.open_turns():  # Stop が届かなかったターンを閉じる
        close_turn(spool, turn, settings.trace_root, interrupted=True)
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


def handle_hook(name: str, payload: dict, env: Mapping[str, str], settings: Settings) -> int:
    sid = env.get("KOSEKI_SESSION_ID", "")
    if not sid or payload.get("session_id") != sid:
        print(
            f"koseki: セッション ID が起動時と違うので記録しません（{payload.get('session_id')}）",
            file=sys.stderr,
        )
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
    args = p.parse_args(argv)
    return _hook_main(args.name)


if __name__ == "__main__":
    raise SystemExit(main())
