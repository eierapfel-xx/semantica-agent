"""1 つの相談の処理（実行環境によらない部分）。仕様（2026-11-19）§3.1。

Agent SDK 版と Claude Code 版（MCP サーバー）の両方が使う。ツールの呼び出しと結果は
ここでトレースに積む。LLM の自己申告は記録の元にしない。
"""

import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from semantica.context import ContextGraph

from semantica_agent.agent.tools import (
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
from semantica_agent.agent.trace import TraceRecorder, ontology_info, save_trace
from semantica_agent.core.paths import REPO_ROOT
from semantica_agent.core.settings import Settings
from semantica_agent.review.case_input import case_record, input_schema

logger = logging.getLogger(__name__)

TOOL_NAMES = (
    "judge_birth_case",
    "search_nodes",
    "describe_node",
    "run_cq",
    "run_sparql",
    "submit_answer",
)
PROMPT_PATH = Path(__file__).parent / "prompts" / "agent.md"
CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string"},
        "kind": {"type": "string", "enum": ["fact", "rule", "speculation"]},
        "nodes": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["text", "kind", "nodes"],
}


@dataclass(frozen=True)
class ToolOutcome:
    text: str
    is_error: bool


def render_prompt(template: str, today: date) -> str:
    return template.replace("{today}", today.isoformat())


def _object(props: dict, required: list[str]) -> dict:
    return {"type": "object", "properties": props, "required": required}


def tool_specs(k: Knowledge) -> dict[str, tuple[str, dict]]:
    """ツールの名前 → (説明, 入力スキーマ)。SDK 版と Claude Code 版で同じものを使う。"""
    cqs = "\n".join(f"{n}: {t}" for n, t in sorted(k.cq_titles.items()))
    s = {"type": "string"}
    return {
        "judge_birth_case": (
            "出生届の事案を判定する。職員が触れていない項目は渡さない（未確認）。"
            "値には職員の発言の引用（quote）を付ける。",
            input_schema(k.ontology),
        ),
        "search_nodes": (
            "オントロジーのノードをラベルの部分一致で探す（最大 20 件）。",
            _object({"text": s, "business": s, "cls": s}, ["text"]),
        ),
        "describe_node": (
            "ノードの詳細（出典、条文、条文の版、現行の扱い、ルール）を返す。",
            _object({"node_id": s}, ["node_id"]),
        ),
        "run_cq": (
            f"決まった問い（competency questions）を引く。番号と問い:\n{cqs}",
            _object({"number": {"type": "integer"}}, ["number"]),
        ),
        "run_sparql": (
            "SELECT の SPARQL を実行する（最大 200 行）。接頭辞 kos: "
            "<https://semantica-agent.example/koseki/schema#>、kd: "
            "<https://semantica-agent.example/koseki/id/>。",
            _object({"query": s}, ["query"]),
        ),
        "submit_answer": (
            "最後の回答を出す。主張ごとに根拠の種類と根拠のノードの短い ID を付ける。",
            _object(
                {"answer": s, "claims": {"type": "array", "items": CLAIM_SCHEMA}},
                ["answer", "claims"],
            ),
        ),
    }


def fallback_answer(texts: list[str]) -> dict:
    """submit_answer が呼ばれなかったときの回答：最後の文章を推測として扱う。"""
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


class ReviewSession:
    """1 つの相談。ターンの開始・ツールの呼び出し・ターンの終わりの組み立てを行う。"""

    def __init__(
        self,
        k: Knowledge,
        settings: Settings,
        session_id: str,
        today: date,
        runtime: dict,
        on_event: Callable[[dict], None] | None = None,
        record_tool_calls: bool = True,
    ):
        self.k, self.settings, self.session_id = k, settings, session_id
        self.today, self.runtime = today, runtime
        self.on_event, self.record_tool_calls = on_event, record_tool_calls
        self.state = new_session(session_id)
        self.prompt_template = PROMPT_PATH.read_text("utf-8")
        self.prompt_hash = hashlib.sha256(self.prompt_template.encode()).hexdigest()
        self.cg = ContextGraph()
        self.recorder: TraceRecorder | None = None
        self.answer: dict | None = None
        self.judge_calls_at_start = 0
        self._fns = self._tool_functions()

    @property
    def system_prompt(self) -> str:
        return render_prompt(self.prompt_template, self.today)

    def _tool_functions(self) -> dict[str, Callable[[dict], Awaitable[ToolResult]]]:
        k, s = self.k, self.state

        async def judge(a):
            return judge_birth_case(k, s, a)

        async def search(a):
            return search_nodes(k, a.get("text", ""), a.get("business"), a.get("cls"))

        async def describe(a):
            return describe_node(k, a.get("node_id", ""))

        async def cq(a):
            return run_cq(k, int(a.get("number", 0)))

        async def sparql(a):
            return await run_sparql(k, a.get("query", ""), self.settings.sparql_timeout_s)

        async def answer(a):
            return submit_answer(k, s, a)

        fns = (judge, search, describe, cq, sparql, answer)
        return dict(zip(TOOL_NAMES, fns, strict=True))

    def start_turn(self, question: str, record_user: bool = True) -> TraceRecorder:
        s = self.state
        s.turn += 1
        s.utterances.append(question)
        s.referenced_this_turn = set()
        self.answer = None
        self.judge_calls_at_start = s.judge_calls
        self.recorder = TraceRecorder(
            session_id=self.session_id,
            turn=s.turn,
            question=question,
            model_requested=self.settings.agent_model,
            prompt_path=str(PROMPT_PATH.relative_to(REPO_ROOT)),
            prompt_hash=self.prompt_hash,
            ontology_info=ontology_info(REPO_ROOT),
            initial_case_states=dict(s.last_case_states),
            runtime=self.runtime,
            on_add=self.on_event,
        )
        if record_user:
            self.recorder.add("user", text=question)
        return self.recorder

    def record_tool_call(self, name: str, args: dict, tool_use_id: str | None, via: str) -> None:
        if name in TOOL_NAMES and self.recorder is not None:
            self.recorder.add("tool_call", tool=name, args=args, tool_use_id=tool_use_id, via=via)

    async def call_tool(self, name: str, args: dict) -> ToolOutcome:
        rec = self.recorder
        if self.record_tool_calls and (not rec.events or rec.events[-1]["type"] != "tool_call"):
            rec.add("tool_call", tool=name, args=args, via="handler")
        try:
            result = await self._fns[name](args)
        except ToolError as e:
            rec.add("tool_result", tool=name, result={"error": str(e)}, nodes=[], is_error=True)
            return ToolOutcome(f"エラー: {e}", True)
        except Exception as e:  # 想定外の失敗：ターンを失敗にし、LLM にもエラーで返す
            logger.exception("ツール %s が失敗しました", name)
            msg = f"{type(e).__name__}: {e}"
            rec.add("tool_result", tool=name, result={"error": msg}, nodes=[], is_error=True)
            rec.add("error", message=f"ツール {name} が失敗しました: {msg}")
            return ToolOutcome(f"内部エラー: {msg}", True)
        self.state.referenced_this_turn |= set(result.nodes)
        rec.add(
            "tool_result",
            tool=name,
            result=result.payload,
            nodes=result.nodes,
            flow=result.flow,
            is_error=False,
        )
        if name == "submit_answer":
            self.answer = {**result.payload, "submitted": True}
            rec.add("answer", **self.answer)
        return ToolOutcome(json.dumps(result.payload, ensure_ascii=False), False)

    @property
    def judged_this_turn(self) -> bool:
        return self.state.judge_calls > self.judge_calls_at_start

    def finish_turn(self, texts: list[str], model: str | None, status: str) -> dict:
        s, judged = self.state, self.judged_this_turn
        return self.recorder.finish(
            answer=self.answer or fallback_answer(texts),
            judgment=s.last_judgment if judged else None,
            case=case_record(s.last_case, s.last_case_iri) if judged else None,
            model_responded=model,
            status=status,
        )

    def save_turn(self, trace: dict) -> Path:
        return save_trace(trace, self.settings.trace_root, self.cg)
