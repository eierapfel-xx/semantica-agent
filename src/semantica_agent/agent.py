"""Agent SDK の審査支援エージェント。仕様 §4。

ツールは SDK 内の MCP サーバーで渡し、組み込みのツールは使わせない。1 ターンごとに、
ツールの結果とフックからコードがトレースを積み、保存する。
"""

import hashlib
import json
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
from semantica.context import ContextGraph

from semantica_agent.case_input import case_record, input_schema
from semantica_agent.settings import Settings
from semantica_agent.tools import (
    Knowledge,
    ToolError,
    ToolResult,
    describe_node,
    judge_birth_case,
    new_session,
    run_cq,
    run_sparql,
    search_nodes,
    submit_answer,
)
from semantica_agent.trace import TraceRecorder, ontology_info, save_trace

logger = logging.getLogger(__name__)

MCP_SERVER = "koseki"
TOOL_NAMES = (
    "judge_birth_case",
    "search_nodes",
    "describe_node",
    "run_cq",
    "run_sparql",
    "submit_answer",
)
PROMPT_PATH = Path(__file__).parent / "prompts" / "agent.md"
REPO_ROOT = Path(__file__).resolve().parents[2]
CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "kind": {"type": "string", "enum": ["fact", "rule", "speculation"]},
        "nodes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "kind", "nodes"],
}


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
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.state = new_session(self.session_id)
        self.today = today or date.today()
        self.prompt_template = PROMPT_PATH.read_text("utf-8")
        self.prompt_hash = hashlib.sha256(self.prompt_template.encode()).hexdigest()
        self.cg = ContextGraph()
        self.recorder: TraceRecorder | None = None
        self._answer: dict | None = None
        self.tools = build_tools(self)
        self._client = None
        self._client_factory = client_factory
        self.busy = False

    @property
    def system_prompt(self) -> str:
        return self.prompt_template.replace("{today}", self.today.isoformat())

    async def _ensure_client(self):
        if self._client is None:
            self._client = self._client_factory(build_options(self), self.tools)
            await self._client.connect()
        return self._client

    def _start_turn(self, text: str) -> TraceRecorder:
        s = self.state
        s.turn += 1
        s.utterances.append(text)
        s.referenced_this_turn = set()
        self._answer = None
        self._judge_calls_at_start = s.judge_calls
        self.recorder = TraceRecorder(
            session_id=self.session_id,
            turn=s.turn,
            question=text,
            model_requested=self.settings.agent_model,
            prompt_path=str(PROMPT_PATH.relative_to(REPO_ROOT)),
            prompt_hash=self.prompt_hash,
            ontology_info=ontology_info(REPO_ROOT),
            initial_case_states=dict(s.last_case_states),
        )
        self.recorder.add("user", text=text)
        return self.recorder

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
        rec = self._start_turn(text)
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
        trace = self._finish(texts, model, "error" if failed else "ok")
        return trace, save_trace(trace, self.settings.trace_root, self.cg)

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

    def _finish(self, texts: list[str], model: str | None, status: str) -> dict:
        s = self.state
        judged = s.judge_calls > self._judge_calls_at_start
        answer = self._answer or _fallback_answer(texts)
        return self.recorder.finish(
            answer=answer,
            judgment=s.last_judgment if judged else None,
            case=case_record(s.last_case, s.last_case_iri) if judged else None,
            model_responded=model,
            status=status,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.disconnect()
            self._client = None


def _fallback_answer(texts: list[str]) -> dict:
    last = texts[-1] if texts else ""
    claims = (
        [
            {
                "text": last,
                "kind": "speculation",
                "nodes": [],
                "downgraded_reason": "submit_answer が呼ばれなかった",
            }
        ]
        if last
        else []
    )
    return {"answer": last, "claims": claims, "submitted": False}


def _wrap(sess: AgentSession, name: str, fn: Callable) -> Callable:
    async def handler(args: dict) -> dict:
        rec = sess.recorder
        if not rec.events or rec.events[-1].get("type") != "tool_call":
            rec.add("tool_call", tool=name, args=args, via="handler")
        try:
            result: ToolResult = await fn(args)
        except ToolError as e:
            rec.add("tool_result", tool=name, result={"error": str(e)}, nodes=[], is_error=True)
            return {"content": [{"type": "text", "text": f"エラー: {e}"}], "is_error": True}
        except Exception as e:  # 想定外の失敗：ターンを失敗にし、LLM にもエラーで返す
            logger.exception("ツール %s が失敗しました", name)
            msg = f"{type(e).__name__}: {e}"
            rec.add("tool_result", tool=name, result={"error": msg}, nodes=[], is_error=True)
            rec.add("error", message=f"ツール {name} が失敗しました: {msg}")
            return {"content": [{"type": "text", "text": f"内部エラー: {msg}"}], "is_error": True}
        sess.state.referenced_this_turn |= set(result.nodes)
        rec.add(
            "tool_result",
            tool=name,
            result=result.payload,
            nodes=result.nodes,
            flow=result.flow,
            is_error=False,
        )
        if name == "submit_answer":
            sess._answer = {**result.payload, "submitted": True}
            rec.add("answer", **sess._answer)
        text = json.dumps(result.payload, ensure_ascii=False)
        return {"content": [{"type": "text", "text": text}]}

    return handler


def _descriptions(k: Knowledge) -> dict[str, str]:
    cqs = "\n".join(f"{n}: {t}" for n, t in sorted(k.cq_titles.items()))
    return {
        "judge_birth_case": "出生届の事案を判定する。職員が触れていない項目は渡さない（未確認）。"
        "値には職員の発言の引用（quote）を付ける。",
        "search_nodes": "オントロジーのノードをラベルの部分一致で探す（最大 20 件）。",
        "describe_node": "ノードの詳細（出典、条文、条文の版、現行の扱い、ルール）を返す。",
        "run_cq": f"決まった問い（competency questions）を引く。番号と問い:\n{cqs}",
        "run_sparql": "SELECT の SPARQL を実行する（最大 200 行）。接頭辞 kos: "
        "<https://semantica-agent.example/koseki/schema#>、kd: "
        "<https://semantica-agent.example/koseki/id/>。",
        "submit_answer": "最後の回答を出す。主張ごとに根拠の種類と根拠のノードの短い ID を付ける。",
    }


def build_tools(sess: AgentSession) -> dict[str, SdkMcpTool]:
    k, s = sess.k, sess.state

    async def judge(a):
        return judge_birth_case(k, s, a)

    async def search(a):
        return search_nodes(k, a.get("text", ""), a.get("business"), a.get("cls"))

    async def describe(a):
        return describe_node(k, a.get("node_id", ""))

    async def cq(a):
        return run_cq(k, int(a.get("number", 0)))

    async def sparql(a):
        return await run_sparql(k, a.get("query", ""), sess.settings.sparql_timeout_s)

    async def answer(a):
        return submit_answer(k, s, a)

    schemas = {
        "judge_birth_case": input_schema(k.ontology),
        "search_nodes": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "business": {"type": "string"},
                "cls": {"type": "string"},
            },
            "required": ["text"],
        },
        "describe_node": {
            "type": "object",
            "properties": {"node_id": {"type": "string"}},
            "required": ["node_id"],
        },
        "run_cq": {
            "type": "object",
            "properties": {"number": {"type": "integer"}},
            "required": ["number"],
        },
        "run_sparql": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        "submit_answer": {
            "type": "object",
            "properties": {
                "answer": {"type": "string"},
                "claims": {"type": "array", "items": CLAIM_SCHEMA},
            },
            "required": ["answer", "claims"],
        },
    }
    fns = {
        "judge_birth_case": judge,
        "search_nodes": search,
        "describe_node": describe,
        "run_cq": cq,
        "run_sparql": sparql,
        "submit_answer": answer,
    }
    desc = _descriptions(k)
    return {n: tool(n, desc[n], schemas[n])(_wrap(sess, n, fns[n])) for n in TOOL_NAMES}


def _hooks(sess: AgentSession) -> dict:
    async def pre(data, tool_use_id, context):
        name = _bare(data.get("tool_name", ""))
        if name in TOOL_NAMES and sess.recorder is not None:
            sess.recorder.add(
                "tool_call",
                tool=name,
                args=data.get("tool_input", {}),
                tool_use_id=tool_use_id,
                via="hook",
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
    )
