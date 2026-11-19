"""Claude Code 版の記録の置き場。仕様（2026-11-19）§5.3。

hook（別プロセス）と MCP サーバーが、`<root>/<session_id>/` のファイルで記録を受け渡す。
"""

import json
from datetime import UTC, datetime
from pathlib import Path


def now() -> str:
    return datetime.now(UTC).isoformat()


class Spool:
    def __init__(self, root: Path, session_id: str):
        self.session_id = session_id
        self.dir = root / session_id

    def _path(self, name: str) -> Path:
        return self.dir / name

    def _turn_file(self, turn: int, suffix: str) -> Path:
        return self._path(f"turn-{turn:03d}.{suffix}")

    def _write_json(self, path: Path, data: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)  # 読む側が書きかけを見ないように

    @staticmethod
    def _read_json(path: Path) -> dict | None:
        return json.loads(path.read_text("utf-8")) if path.exists() else None

    def write_session(self, info: dict) -> None:
        self._write_json(self._path("session.json"), info)

    def read_session(self) -> dict:
        info = self._read_json(self._path("session.json"))
        if info is None:
            raise FileNotFoundError(f"相談の情報がありません: {self._path('session.json')}")
        return info

    def begin_turn(self, question: str, transcript_path: str | None) -> int:
        cur = self.current_turn()
        turn = (cur["turn"] if cur else 0) + 1
        info = {
            "turn": turn,
            "question": question,
            "started": now(),
            "transcript_path": transcript_path,
        }
        self._write_json(self._path("turn.json"), info)
        return turn

    def current_turn(self) -> dict | None:
        return self._read_json(self._path("turn.json"))

    def append_event(self, turn: int, event: dict) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False) + "\n"
        with self._turn_file(turn, "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(line)

    def read_events(self, turn: int) -> list[dict]:
        path = self._turn_file(turn, "events.jsonl")
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text("utf-8").splitlines() if x.strip()]

    def write_state(self, turn: int, state: dict) -> None:
        self._write_json(self._turn_file(turn, "state.json"), state)

    def read_state(self, turn: int) -> dict | None:
        return self._read_json(self._turn_file(turn, "state.json"))

    def last_case_states(self, before_turn: int) -> dict:
        for t in range(before_turn - 1, 0, -1):
            state = self.read_state(t)
            if state is not None:
                return state.get("case_states", {})
        return {}

    def mark_done(self, turn: int) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self._turn_file(turn, "done").touch()

    def is_done(self, turn: int) -> bool:
        return self._turn_file(turn, "done").exists()

    def mark_failed(self, turn: int) -> None:
        """閉じられなかったターン（hook-errors.log に理由）。もう閉じ直さない。"""
        self.dir.mkdir(parents=True, exist_ok=True)
        self._turn_file(turn, "failed").touch()

    def open_turns(self) -> list[int]:
        turns = sorted(int(p.name[5:8]) for p in self.dir.glob("turn-*.events.jsonl"))
        return [
            t for t in turns if not self.is_done(t) and not self._turn_file(t, "failed").exists()
        ]

    def log_error(self, message: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        with self._path("hook-errors.log").open("a", encoding="utf-8") as f:
            f.write(f"{now()} {message}\n")
