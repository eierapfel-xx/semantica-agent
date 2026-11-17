"""手順書のフローの形と、ノードの状態（色）。仕様 §7.1・§7.2。

状態はツールの結果（判定の後処理、参照したノード）からだけ決める。LLM の申告は使わない。
"""

from collections import Counter
from collections.abc import Iterable, Sequence
from enum import StrEnum

from rdflib import RDF, RDFS, Graph, URIRef

from semantica_agent.assess import Assessment, decision_name
from semantica_agent.case_input import FIELDS_BY_NAME
from semantica_agent.ids import short_id
from semantica_agent.judge import SEVERITY_ORDER
from semantica_agent.namespaces import KD, KOS

BUSINESSES = ("birth", "marriage", "divorce", "death", "certificate")
VERSION_BADGES = {KOS.Manual: "manual", KOS.Current: "current"}


class NodeState(StrEnum):
    FINDING = "finding"
    UNEVALUATED = "unevaluated"
    HUMAN = "human"
    PASSED = "passed"
    REFERENCED = "referenced"
    NONE = "none"


PRIORITY = tuple(NodeState)  # 先頭ほど重い


def _sorted_by(g: Graph, nodes: Iterable, prop: URIRef) -> list:
    return sorted(nodes, key=lambda n: int(g.value(n, prop) or 0))


def _item(g: Graph, node) -> dict:
    return {
        "id": short_id(node),
        "label": str(g.value(node, RDFS.label) or ""),
        "itemLabel": str(g.value(node, KOS.itemLabel) or ""),
        "kind": "check" if (node, RDF.type, KOS.ReviewCheck) in g else "task",
        "conditions": sorted(str(g.value(c, RDFS.label)) for c in g.objects(node, KOS.appliesWhen)),
        "children": [
            _item(g, c) for c in _sorted_by(g, g.objects(node, KOS.hasSubItem), KOS.itemOrder)
        ],
    }


def flow_shape(ontology: Graph, business: str) -> dict:
    if business not in BUSINESSES:
        raise ValueError(f"知らない業務です: {business}（{', '.join(BUSINESSES)}）")
    biz = KD[business]
    steps = _sorted_by(ontology, ontology.objects(biz, KOS.hasStep), KOS.stepNumber)
    return {
        "business": business,
        "label": str(ontology.value(biz, RDFS.label) or business),
        "steps": [
            {
                "id": short_id(s),
                "number": int(ontology.value(s, KOS.stepNumber)),
                "label": str(ontology.value(s, RDFS.label) or ""),
                "items": [
                    _item(ontology, i)
                    for i in _sorted_by(ontology, ontology.objects(s, KOS.hasItem), KOS.itemOrder)
                ],
            }
            for s in steps
        ],
    }


def _descendants(g: Graph, node) -> list:
    out = []
    for c in g.objects(node, KOS.hasSubItem):
        out += [c, *_descendants(g, c)]
    return out


def _check_state(a: Assessment, rules: Graph, ontology: Graph, rs: list) -> dict | None:
    stateful = [r for r in rs if r in a.applicable and rules.value(r, KOS.outcome) != KOS.Info]
    if not stateful:
        return None
    found = [f for f in a.findings if f.rule in stateful]
    badges = sorted(
        {
            VERSION_BADGES[s]
            for r in stateful
            for v in rules.objects(r, KOS.underVersion)
            if (s := ontology.value(v, KOS.versionStatus)) in VERSION_BADGES
        }
        | ({"provisional"} if any(f.provisional for f in found) else set())
    )
    if found:
        worst = next(o for o in SEVERITY_ORDER if o in {f.outcome for f in found})
        return {"state": "finding", "outcome": decision_name(worst), "badges": badges}
    missing = sorted({n for r in stateful for n in a.unevaluated.get(r, ())})
    if missing:
        labels = "、".join(FIELDS_BY_NAME[n].label_ja for n in missing)
        return {"state": "unevaluated", "reason": f"{labels}が未確認", "badges": badges}
    return {"state": "passed", "badges": badges}


def case_states(a: Assessment, rules: Graph, ontology: Graph) -> dict[str, dict]:
    """出生届の審査項目の状態。ルールの付いた項目の子孫は、その状態を受け継ぐ。"""
    by_check: dict = {}
    for r in rules.subjects(RDF.type, KOS.JudgmentRule):
        for c in rules.objects(r, KOS.implementsCheck):
            by_check.setdefault(c, []).append(r)
    out: dict[str, dict] = {}
    covered = set()
    for check, rs in sorted(by_check.items()):
        st = _check_state(a, rules, ontology, rs)
        info = any(f.check == check for f in a.info)
        covered |= {check, *_descendants(ontology, check)}
        if st is None:
            continue
        if info:
            st = {**st, "badges": sorted({*st["badges"], "info"})}
        out[short_id(check)] = st
        for d in _descendants(ontology, check):
            if d not in by_check:
                out.setdefault(short_id(d), dict(st))
    prefix = f"{KD}birth/"
    for check in ontology.subjects(RDF.type, KOS.ReviewCheck):
        if str(check).startswith(prefix) and check not in covered:
            out[short_id(check)] = {"state": "human", "badges": []}
    return out


def merge_states(case: dict[str, dict], referenced: Iterable[str]) -> dict[str, dict]:
    out = {k: dict(v) for k, v in case.items()}
    for n in referenced:
        if out.get(n, {}).get("state", "none") == "none":
            out[n] = {"state": "referenced", "badges": []}
    return out


def _worst_state(states: Iterable[str]) -> str:
    present = set(states)
    return next((s.value for s in PRIORITY if s.value in present), "none")


def step_states(shape: dict, states: dict[str, dict]) -> dict[str, str]:
    def ids(items: list[dict]) -> list[str]:
        return [x for i in items for x in (i["id"], *ids(i["children"]))]

    return {
        s["id"]: _worst_state(
            states.get(i, {}).get("state", "none") for i in (s["id"], *ids(s["items"]))
        )
        for s in shape["steps"]
    }


def replay(events: Sequence[dict], initial_case: dict[str, dict]) -> dict[str, dict]:
    """イベントの flow を順に当てる。case_states は置き換え、referenced は足す。"""
    case, referenced = dict(initial_case), []
    for e in events:
        flow = e.get("flow") or {}
        if "case_states" in flow:
            case = dict(flow["case_states"])
        referenced += [n for n in flow.get("referenced", []) if n not in referenced]
    return merge_states(case, referenced)


def pick_business(ids: Iterable[str]) -> str:
    counts = Counter(i.split("-")[0].lower() for i in ids)
    best = max(BUSINESSES, key=lambda b: (counts[b], -BUSINESSES.index(b)))
    return best if counts[best] else BUSINESSES[0]
