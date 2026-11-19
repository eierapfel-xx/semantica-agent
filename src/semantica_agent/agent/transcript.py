"""Claude Code の会話の記録（transcript の JSONL）から、1 ターンの LLM の文章を取り出す。

transcript の形は公開の仕様ではないので、読み取りはここだけで行い、知らない形の行は飛ばす。
仕様（2026-11-19）§5.6。
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

BLOCK_TYPES = {"text": ("assistant_text", "text"), "thinking": ("thinking", "thinking")}


@dataclass(frozen=True)
class TranscriptItem:
    time: str
    type: str
    text: str


@dataclass(frozen=True)
class TurnMessages:
    items: list[TranscriptItem]
    model: str | None


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _line_items(line: str, since: datetime) -> tuple[list[TranscriptItem], str | None]:
    d = json.loads(line)
    if not isinstance(d, dict) or d.get("type") != "assistant":
        return [], None
    msg, ts = d.get("message"), d.get("timestamp")
    if not isinstance(msg, dict) or not isinstance(ts, str):
        return [], None
    t = _parse_time(ts)
    if t < since:
        return [], None
    items = []
    for block in msg.get("content") or []:
        kind = BLOCK_TYPES.get(block.get("type")) if isinstance(block, dict) else None
        if kind and block.get(kind[1]):
            items.append(TranscriptItem(t.isoformat(), kind[0], block[kind[1]]))
    return items, msg.get("model")


def read_turn_messages(path: Path | None, since: str) -> TurnMessages:
    if path is None or not path.exists():
        return TurnMessages([], None)
    start, items, model = _parse_time(since), [], None
    for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        try:
            got, m = _line_items(line, start)
        except (ValueError, AttributeError, TypeError) as e:
            logger.debug("transcript の %d 行目を読めないので飛ばします: %s", n, e)
            continue
        items += got
        model = m or model
    return TurnMessages(items, model)
