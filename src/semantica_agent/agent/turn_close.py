"""Claude Code 版の 1 ターンを閉じて、トレースにまとめて保存する。仕様（2026-11-19）§5.3・§5.4。

イベントは hook と MCP サーバーが spool に書いたもの、LLM の文章は Claude Code の
transcript から取る。どちらも LLM の自己申告ではない。
"""

import logging
from datetime import datetime
from pathlib import Path

from semantica.context import ContextGraph

from semantica_agent.agent.session import fallback_answer
from semantica_agent.agent.spool import Spool, now
from semantica_agent.agent.trace import TraceRecorder, save_trace
from semantica_agent.agent.transcript import read_turn_messages

logger = logging.getLogger(__name__)

INTERRUPTED_MESSAGE = "ターンが中断されました（Stop が届かなかった）"


def _time(event: dict) -> datetime:
    return datetime.fromisoformat(event["time"].replace("Z", "+00:00"))


def _merge_events(
    spool: Spool, turn: int, info: dict, last_message: str | None, interrupted: bool
) -> tuple[list[dict], str | None]:
    path = info.get("transcript_path")
    msgs = read_turn_messages(Path(path) if path else None, info["started"])
    extra = [{"type": i.type, "text": i.text, "time": i.time} for i in msgs.items]
    texts = [e["text"] for e in extra if e["type"] == "assistant_text"]
    if last_message and (not texts or texts[-1] != last_message):  # Stop の時点で未記録の最後の文
        extra.append({"type": "assistant_text", "text": last_message, "time": now()})
    events = sorted(spool.read_events(turn) + extra, key=_time)  # 安定ソート
    if interrupted:
        events.append({"type": "error", "message": INTERRUPTED_MESSAGE, "time": now()})
    merged = [{**e, "seq": n} for n, e in enumerate(events, 1)]
    return merged, msgs.model


def _state(spool: Spool, turn: int) -> dict:
    state = spool.read_state(turn)
    if state is not None:
        return state
    prev = spool.last_case_states(turn)
    return {
        "judged": False,
        "judgment": None,
        "case": None,
        "answer": None,
        "case_states": prev,
        "initial_case_states": prev,
    }


def _turn_info(spool: Spool, turn: int) -> dict:
    cur = spool.current_turn()
    if cur and cur["turn"] == turn:
        return cur
    events = spool.read_events(turn)
    user = next((e for e in events if e["type"] == "user"), None)
    started = events[0]["time"] if events else now()
    return {"turn": turn, "question": (user or {}).get("text", ""), "started": started}


def _context_graph(folder: Path) -> ContextGraph:
    cg = ContextGraph()
    path = folder / "decisions.json"
    if path.exists():
        cg.load_from_file(str(path))
    return cg


def close_turn(
    spool: Spool,
    turn: int,
    trace_root: Path,
    *,
    last_message: str | None = None,
    interrupted: bool = False,
) -> Path | None:
    if spool.is_done(turn):
        return None
    info, session, state = _turn_info(spool, turn), spool.read_session(), _state(spool, turn)
    events, model = _merge_events(spool, turn, info, last_message, interrupted)
    rec = TraceRecorder(
        session_id=spool.session_id,
        turn=turn,
        question=info["question"],
        model_requested=session["model_requested"],
        prompt_path=session["prompt_path"],
        prompt_hash=session["prompt_hash"],
        ontology_info=session["ontology_info"],
        initial_case_states=state["initial_case_states"],
        events=events,
        started=info["started"],
        runtime=session["runtime"],
    )
    texts = [e["text"] for e in events if e["type"] == "assistant_text"]
    failed = any(e["type"] == "error" for e in events)
    trace = rec.finish(
        answer=state["answer"] or fallback_answer(texts),
        judgment=state["judgment"] if state["judged"] else None,
        case=state["case"] if state["judged"] else None,
        model_responded=model,
        status="error" if failed else "ok",
    )
    path = save_trace(trace, trace_root, _context_graph(trace_root / spool.session_id))
    spool.mark_done(turn)
    logger.info("Claude Code 版のターン %d を閉じました: %s", turn, path)
    return path
