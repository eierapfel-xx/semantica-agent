"""Agent SDK の審査支援エージェント。仕様 §4。

ツールは SDK 内の MCP サーバーで渡し、組み込みのツールは使わせない。1 ターンごとに、
ツールの結果とフックからコードがトレースを積み、保存する。
"""

import logging
import uuid
from collections.abc import AsyncIterator, Callable
from datetime import date
from pathlib import Path

import anyio
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    HookMatcher,
    SdkMcpTool,
    create_sdk_mcp_server,
    tool,
)
from claude_agent_sdk.types import AssistantMessage, ResultMessage, TextBlock, ThinkingBlock

from semantica_agent.agent.claude_code import ISOLATION_ENV, bundled_cli_version
from semantica_agent.agent.session import TOOL_NAMES, ReviewSession, tool_specs
from semantica_agent.agent.tools import Knowledge
from semantica_agent.core.settings import Settings

logger = logging.getLogger(__name__)

MCP_SERVER = "koseki"


def allowed_tool_names() -> list[str]:
    return [f"mcp__{MCP_SERVER}__{n}" for n in TOOL_NAMES]


def _bare(name: str) -> str:
    return name.removeprefix(f"mcp__{MCP_SERVER}__")


def _default_client(options: ClaudeAgentOptions, tools: dict) -> ClaudeSDKClient:
    return ClaudeSDKClient(options)


class AgentSession:
    """1 つの相談。続けての質問は同じクライアントに送る。"""

    def __init__(
        self,
        k: Knowledge,
        settings: Settings,
        client_factory: Callable = _default_client,
        session_id: str | None = None,
        today: date | None = None,
    ):
        self.k, self.settings = k, settings
        self.review = ReviewSession(
            k,
            settings,
            session_id or uuid.uuid4().hex[:12],
            today or date.today(),
            {"kind": "agent-sdk", "cli_version": bundled_cli_version()},
        )
        self.session_id = self.review.session_id
        self.state = self.review.state
        self.tools = build_tools(self)
        self._client = None
        self._client_factory = client_factory
        self.busy = False

    @property
    def system_prompt(self) -> str:
        return self.review.system_prompt

    @property
    def recorder(self):
        return self.review.recorder

    async def _ensure_client(self):
        if self._client is None:
            self._client = self._client_factory(build_options(self), self.tools)
            await self._client.connect()
        return self._client

    def _record_message(self, msg, texts: list[str]) -> str | None:
        if not isinstance(msg, AssistantMessage):
            return None
        for b in msg.content:
            if isinstance(b, TextBlock) and b.text:
                texts.append(b.text)
                self.recorder.add("assistant_text", text=b.text)
            elif isinstance(b, ThinkingBlock):
                self.recorder.add("thinking", text=b.thinking)
        if msg.error:
            self.recorder.add("error", message=f"Agent SDK がエラーを返しました: {msg.error}")
        return msg.model

    def _record_result(self, msg) -> None:
        if isinstance(msg, ResultMessage) and msg.is_error:
            detail = "、".join(str(e) for e in (msg.errors or []))
            self.recorder.add(
                "error", message=f"ターンが打ち切られました（{msg.subtype}）{detail}".rstrip()
            )

    async def ask(self, text: str) -> AsyncIterator[dict]:
        if self.busy:  # 同じ相談で同時に 2 つの質問は処理しない
            yield {"type": "error", "message": "処理中です。終わってから送ってください"}
            return
        self.busy = True
        try:
            async for e in self._turn(text):
                yield e
        finally:
            self.busy = False

    async def _turn(self, text: str) -> AsyncIterator[dict]:
        rec = self.review.start_turn(text)
        sent, texts, model = 0, [], None
        try:
            client = await self._ensure_client()
            await client.query(text)
            async for msg in client.receive_response():
                model = self._record_message(msg, texts) or model
                self._record_result(msg)
                for e in rec.events[sent:]:
                    yield e
                sent = len(rec.events)
        except Exception as e:  # SDK・通信の失敗はトレースに残して画面に返す
            logger.exception("ターンの処理に失敗しました")
            rec.add("error", message=f"{type(e).__name__}: {e}")
        except BaseException:  # 取り消し（画面の再読み込みなど）：記録を残し、クライアントを捨てる
            rec.add("error", message="ターンが取り消されました")
            with anyio.CancelScope(shield=True):
                self._save(texts, model)
                await self._drop_client()
            raise
        for e in rec.events[sent:]:
            yield e
        trace, path = self._save(texts, model)
        yield {"type": "turn_end", "trace_path": str(path), "trace": trace}

    def _save(self, texts: list[str], model: str | None) -> tuple[dict, Path]:
        failed = any(e["type"] == "error" for e in self.recorder.events)
        trace = self.review.finish_turn(texts, model, "error" if failed else "ok")
        return trace, self.review.save_turn(trace)

    async def _drop_client(self) -> None:
        """応答の途中のクライアントは捨てる（次のターンが前の応答の残りを読まないように）。"""
        client, self._client = self._client, None
        if client is None:
            return
        try:
            await client.interrupt()
        except Exception:
            logger.warning("クライアントの中断に失敗しました", exc_info=True)
        await client.disconnect()

    async def close(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None


def build_tools(sess: AgentSession) -> dict[str, SdkMcpTool]:
    def handler(name: str):
        async def call(args: dict) -> dict:
            out = await sess.review.call_tool(name, args)
            content = {"content": [{"type": "text", "text": out.text}]}
            return {**content, "is_error": True} if out.is_error else content

        return call

    specs = tool_specs(sess.k)
    return {n: tool(n, specs[n][0], specs[n][1])(handler(n)) for n in TOOL_NAMES}


def _hooks(sess: AgentSession) -> dict:
    async def pre(data, tool_use_id, context):
        if sess.recorder is not None:
            sess.review.record_tool_call(
                _bare(data.get("tool_name", "")), data.get("tool_input", {}), tool_use_id, "hook"
            )
        return {}

    async def post(data, tool_use_id, context):
        logger.debug("ツールの呼び出しが終わりました: %s", data.get("tool_name"))
        return {}

    return {
        "PreToolUse": [HookMatcher(matcher=None, hooks=[pre])],
        "PostToolUse": [HookMatcher(matcher=None, hooks=[post])],
    }


def build_options(sess: AgentSession) -> ClaudeAgentOptions:
    server = create_sdk_mcp_server(MCP_SERVER, tools=list(sess.tools.values()))
    return ClaudeAgentOptions(
        model=sess.settings.agent_model,
        system_prompt=sess.system_prompt,
        mcp_servers={MCP_SERVER: server},
        allowed_tools=allowed_tool_names(),
        tools=[],
        setting_sources=[],
        max_turns=sess.settings.agent_max_turns,
        hooks=_hooks(sess),
        env=dict(ISOLATION_ENV),
    )
