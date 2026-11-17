"""審査支援の Web サーバー。仕様 §7.4。

処理の進みは Server-Sent Events で送る。各イベントには、その時点のフローの状態（view）を
サーバーが計算して付ける。画面の JS は状態を合成せず、描くだけにする。
"""

import argparse
import json
import logging
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from semantica_agent.agent import AgentSession
from semantica_agent.flow import BUSINESSES, flow_shape, pick_business, replay, step_states
from semantica_agent.settings import ConfigError, Settings, configure_logging, load_settings
from semantica_agent.tools import Knowledge, ToolError, describe_node
from semantica_agent.turtle_io import validate_integrity

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
STATIC_DIR = Path(__file__).parent / "web" / "static"
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")


class Message(BaseModel):
    text: str

    @field_validator("text")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("質問が空です")
        return v


def make_view(
    events: Sequence[dict], initial: dict, shapes: dict[str, dict], business: str | None = None
) -> dict:
    """イベントの列のその時点の状態：ノードの状態、業務ごとの工程の状態、開く業務。"""
    flow = replay(events, initial)
    if business is None:
        judged = any("case_states" in (e.get("flow") or {}) for e in events) or initial
        touched = [n for e in events for n in e.get("nodes", [])]
        business = "birth" if judged else pick_business(touched)
    return {
        "flow": flow,
        "steps": {b: step_states(s, flow) for b, s in shapes.items()},
        "business": business,
    }


def timeline(trace: dict, shapes: dict[str, dict]) -> list[dict]:
    events, initial = trace["events"], trace.get("flow_initial", {})
    return [make_view(events[: i + 1], initial, shapes) for i in range(len(events))]


def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def create_app(
    k: Knowledge, settings: Settings, session_factory: Callable[[], AgentSession]
) -> FastAPI:
    app = FastAPI(title="審査支援")
    app.state.sessions = {}
    app.state.busy = set()
    shapes = {b: flow_shape(k.ontology, b) for b in BUSINESSES}
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/flow/{business}")
    def flow(business: str):
        if business not in shapes:
            raise HTTPException(404, f"知らない業務です: {business}")
        return shapes[business]

    @app.post("/api/sessions")
    def new_session():
        sess = session_factory()
        app.state.sessions[sess.session_id] = sess
        return {"session_id": sess.session_id}

    @app.delete("/api/sessions/{sid}", status_code=204)
    async def close_session(sid: str):
        sess = app.state.sessions.pop(sid, None)
        if sess is None:
            raise HTTPException(404, "相談がありません")
        await sess.close()
        return Response(status_code=204)

    @app.post("/api/sessions/{sid}/messages")
    def message(sid: str, body: Message):
        sess = app.state.sessions.get(sid)
        if sess is None:
            raise HTTPException(404, "相談がありません")
        if sid in app.state.busy:
            raise HTTPException(409, "処理中です。終わってから送ってください")
        app.state.busy.add(sid)

        async def stream():
            # ターンの初めの事案の状態（前のターンの判定の色）。turn_end ではトレースの値を使う。
            state = getattr(sess, "state", None)
            initial = dict(getattr(state, "last_case_states", None) or {})
            seen: list[dict] = []
            try:
                async for e in sess.ask(body.text):
                    if e["type"] == "turn_end":
                        t = e["trace"]
                        view = make_view(t.get("events", seen), t.get("flow_initial", {}), shapes)
                    else:
                        seen.append(e)
                        view = make_view(seen, initial, shapes)
                    yield _sse({**e, "view": view})
            finally:
                app.state.busy.discard(sid)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/nodes/{node_id}")
    def node(node_id: str):
        try:
            return describe_node(k, node_id).payload
        except ToolError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/api/traces")
    def traces():
        out = []
        for p in sorted(settings.trace_root.glob("*/*.json")):
            if not p.stem.isdigit():
                continue
            t = json.loads(p.read_text("utf-8"))
            out.append(
                {
                    "session_id": t["session_id"],
                    "turn": t["turn"],
                    "question": t["question"],
                    "started": t["started"],
                    "status": t["status"],
                    "decision": (t.get("judgment") or {}).get("decision"),
                }
            )
        return sorted(out, key=lambda x: x["started"], reverse=True)

    @app.get("/api/traces/{sid}/{turn}")
    def trace(sid: str, turn: int):
        if not _SAFE_ID.match(sid):
            raise HTTPException(400, "相談の ID が不正です")
        p = settings.trace_root / sid / f"{turn:03d}.json"
        if not p.exists():
            raise HTTPException(404, "トレースがありません")
        t = json.loads(p.read_text("utf-8"))
        return {**t, "timeline": timeline(t, shapes)}

    return app


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="semantica_agent.web")
    p.add_argument("--root", default=".", help="リポジトリの場所（ontology/ がある所）")
    args = p.parse_args(argv)
    root = Path(args.root).resolve()
    try:
        settings = load_settings()
        configure_logging(settings)
        k = Knowledge.load(root)
        conforms, text = validate_integrity(root / "ontology")
    except (ConfigError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    if not conforms:
        print(f"エラー: オントロジーの整合性の検証で違反があります\n{text}", file=sys.stderr)
        return 1
    app = create_app(k, settings, lambda: AgentSession(k, settings))
    print(f"審査支援の画面: http://{HOST}:{settings.web_port}/")
    uvicorn.run(app, host=HOST, port=settings.web_port, log_level=settings.log_level.lower())
    return 0


if __name__ == "__main__":
    sys.exit(main())
