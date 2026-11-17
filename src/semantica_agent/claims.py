"""回答の主張の検証。根拠の種類はコードが確かめ、確かめられなければ推測に下げる。仕様 §5.2。"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from semantica_agent.ids import iri_from_short_id, short_id

if TYPE_CHECKING:
    from semantica_agent.tools import Knowledge, SessionState

KINDS = ("fact", "rule", "speculation")
EVALUATED_STATES = ("passed", "finding")


class ClaimError(ValueError):
    pass


@dataclass(frozen=True)
class Claim:
    text: str
    kind: Literal["fact", "rule", "speculation"]
    nodes: tuple[str, ...]
    downgraded_reason: str | None = None


def _exists(k: "Knowledge", sid: str) -> bool:
    try:
        return (iri_from_short_id(sid), None, None) in k.ontology
    except (ValueError, KeyError, IndexError):
        return False


def _short(node) -> str | None:
    try:
        return short_id(node)
    except ValueError:
        return None


def evaluated_rule_nodes(k: "Knowledge", s: "SessionState") -> set[str]:
    """最後の判定で評価できたルールと、状態が通過か指摘の審査項目の短い ID。

    審査項目は、フローの状態（適用される判定のルールがすべて評価できたか）と同じ基準で決める。
    """
    a = s.last_assessment
    if a is None:
        return set()
    rules = {_short(r) for r in a.applicable - set(a.unevaluated)}
    checks = {c for c, st in s.last_case_states.items() if st["state"] in EVALUATED_STATES}
    return {x for x in rules | checks if x}


def _parse(raw: object) -> tuple[str, str, list[str]]:
    if not isinstance(raw, dict):
        raise ClaimError("主張は {text, kind, nodes} の形です")
    text, kind, nodes = raw.get("text"), raw.get("kind"), raw.get("nodes", [])
    if not isinstance(text, str) or not text or kind not in KINDS:
        raise ClaimError(f"主張には text と kind（{', '.join(KINDS)}）が要ります: {raw!r}")
    if not isinstance(nodes, list) or not all(isinstance(n, str) for n in nodes):
        raise ClaimError(f"nodes は短い ID の配列です: {raw!r}")
    return text, kind, nodes


def verify_claims(raw: list, k: "Knowledge", s: "SessionState") -> list["Claim"]:
    rule_nodes = evaluated_rule_nodes(k, s)
    out = []
    for item in raw:
        text, kind, nodes = _parse(item)
        kept = tuple(n for n in nodes if _exists(k, n))
        reason = None
        if kind == "rule" and not set(kept) & rule_nodes:
            reason = "この相談の最後の判定で評価されたルール・審査項目を指していない"
        elif kind == "fact" and not set(kept) & s.referenced_this_turn:
            reason = "このターンのツールの結果に出てきたノードを指していない"
        out.append(Claim(text, "speculation" if reason else kind, kept, reason))
    return out
