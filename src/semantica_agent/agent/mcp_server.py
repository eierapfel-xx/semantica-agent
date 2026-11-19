"""Claude Code 版の stdio MCP サーバー（`koseki`）。仕様（2026-11-19）§5.2。

ツールは SDK 版と同じ `ReviewSession` から出す。ターンの区切りは hook が spool の
`turn.json` に書き、ここはツールを呼ばれるたびにそれを読んで追いつく。
`uv run python -m semantica_agent.agent.mcp_server` で起動する（`KOSEKI_SESSION_ID` が要る）。
"""

import logging
import os
import sys
from datetime import date

import anyio
import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server

from semantica_agent.agent.session import ReviewSession, ToolOutcome, tool_specs
from semantica_agent.agent.spool import Spool
from semantica_agent.agent.tools import Knowledge
from semantica_agent.core.paths import REPO_ROOT
from semantica_agent.core.settings import ConfigError, Settings, configure_logging, load_settings
from semantica_agent.review.case_input import case_record

logger = logging.getLogger(__name__)

SERVER_NAME = "koseki"
NO_TURN = (
    "エラー: 記録中のターンがありません（UserPromptSubmit の hook が動いていないか、"
    "/clear などで会話が切り替わった可能性）。run.sh から起動し直してください"
)


class SpoolBackedSession:
    """MCP サーバーの中の相談。イベントは spool の今のターンに書く。"""

    def __init__(self, k: Knowledge, settings: Settings, spool: Spool, today: date):
        self.spool = spool
        self._turn = 0
        self.review = ReviewSession(
            k,
            settings,
            spool.session_id,
            today,
            spool.read_session()["runtime"],
            on_event=lambda e: self.spool.append_event(self._turn, e),
            record_tool_calls=False,  # 呼び出しは PreToolUse の hook が記録する
        )

    def _follow_turn(self) -> bool:
        cur = self.spool.current_turn()
        if cur is None or self.spool.is_done(
            cur["turn"]
        ):  # 閉じたターンには書かない（/clear 後など）
            return False
        if cur["turn"] != self._turn:
            self._turn = cur["turn"]
            self.review.state.turn = cur["turn"] - 1  # start_turn が 1 進める
            self.review.start_turn(cur["question"], record_user=False)
        return True

    def _state(self) -> dict:
        r, s = self.review, self.review.state
        judged = r.judged_this_turn
        return {
            "judged": judged,
            "judgment": s.last_judgment if judged else None,
            "case": case_record(s.last_case, s.last_case_iri) if judged else None,
            "answer": r.answer,
            "case_states": s.last_case_states,
            "initial_case_states": r.recorder.initial_case_states,
        }

    async def call_tool(self, name: str, args: dict) -> ToolOutcome:
        if not self._follow_turn():
            return ToolOutcome(NO_TURN, True)
        out = await self.review.call_tool(name, args)
        self.spool.write_state(self._turn, self._state())
        return out


def list_tools_result(k: Knowledge) -> types.ListToolsResult:
    return types.ListToolsResult(
        tools=[
            types.Tool(name=n, description=d, input_schema=s) for n, (d, s) in tool_specs(k).items()
        ]
    )


async def call_tool_result(
    sess: SpoolBackedSession, name: str, args: dict | None
) -> types.CallToolResult:
    out = await sess.call_tool(name, args or {})
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=out.text)], is_error=out.is_error
    )


def build_server(sess: SpoolBackedSession, k: Knowledge) -> Server:
    async def on_list_tools(ctx, params):
        return list_tools_result(k)

    async def on_call_tool(ctx, params):
        return await call_tool_result(sess, params.name, params.arguments)

    return Server(SERVER_NAME, on_list_tools=on_list_tools, on_call_tool=on_call_tool)


async def _serve(server: Server) -> None:
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def main() -> int:
    try:
        settings = load_settings()
        configure_logging(settings)
        sid = os.environ.get("KOSEKI_SESSION_ID")
        if not sid:
            raise ConfigError("KOSEKI_SESSION_ID がありません。run.sh から起動してください")
        k = Knowledge.load(REPO_ROOT)
        sess = SpoolBackedSession(k, settings, Spool(settings.spool_root, sid), date.today())
    except (ConfigError, FileNotFoundError, ValueError) as e:
        print(f"koseki の MCP サーバーを起動できません: {e}", file=sys.stderr)
        return 1
    anyio.run(_serve, build_server(sess, k))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
