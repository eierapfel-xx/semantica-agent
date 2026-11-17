"""判定の後処理。未確認の項目を使うルールを「評価できず」にし、全体の判定を決める。仕様 §5.1.1。"""

import logging
from dataclasses import dataclass
from datetime import date

from rdflib import Graph, URIRef

from semantica_agent.case_input import FIELDS_BY_NAME, CaseInput, case_graph
from semantica_agent.judge import SEVERITY_ORDER, Finding, Judgment, judge
from semantica_agent.namespaces import KOS
from semantica_agent.rule_inputs import applicable_rules

logger = logging.getLogger(__name__)

DECISIONS = (
    "reject",
    "needsCorrection",
    "needsInquiry",
    "additionalProcedure",
    "acceptable",
    "pending",
)
# 前の項目が none（無いと確認）なら、後の項目は問う意味が無いので未確認に数えない。
# 前婚が無ければ、出生までの再婚の有無は判定に効かない
# （ルールでは前婚解消後 300 日以内のときだけ見る）。
NOT_NEEDED_WHEN_NONE = {"motherRemarriedBeforeBirth": "motherPrevMarriageEndDate"}


@dataclass(frozen=True)
class Assessment:
    decision: str
    has_unconfirmed: bool
    unconfirmed: tuple[str, ...]
    findings: tuple[Finding, ...]
    info: tuple[Finding, ...]
    unevaluated: dict[URIRef, tuple[str, ...]]
    applicable: frozenset[URIRef]
    provisional_decision: str | None
    judgment: Judgment


def decision_name(outcome: URIRef) -> str:
    local = str(outcome).split("#")[-1]
    return local[0].lower() + local[1:]


def _unconfirmed(case: CaseInput, judgment: Judgment) -> tuple[str, ...]:
    names = set(case.unknown_fields)
    names |= {str(p).split("#")[-1] for p in judgment.missing_inputs}
    for fv in case.fields:  # 一覧が「これで全部」と確認されていなければ、無いものは言えない
        if FIELDS_BY_NAME[fv.name].kind == "iri_list" and fv.name not in case.complete_lists:
            names.add(fv.name)
    for name, prior in NOT_NEEDED_WHEN_NONE.items():
        if case.get(prior).status == "none" and case.get(name).status != "given":
            names.discard(name)
    return tuple(sorted(names))


def _worst(findings: list[Finding]) -> str | None:
    outcomes = {f.outcome for f in findings}
    return next((decision_name(o) for o in SEVERITY_ORDER if o in outcomes), None)


def _birth(case: CaseInput) -> date | None:
    fv = case.get("childBirthDate")
    return fv.value if fv.status == "given" else None


def assess(
    case: CaseInput,
    case_iri: URIRef,
    ontology: Graph,
    rules: Graph,
    inputs: dict[URIRef, frozenset[str]],
) -> Assessment:
    j = judge(case_graph(case, case_iri), case_iri, ontology, rules)
    unconfirmed = _unconfirmed(case, j)
    applicable = applicable_rules(rules, ontology, _birth(case))
    unevaluated = {
        r: tuple(sorted(inputs.get(r, frozenset()) & set(unconfirmed)))
        for r in sorted(applicable)
        if inputs.get(r, frozenset()) & set(unconfirmed)
    }
    evaluated = [f for f in j.findings if f.rule in applicable and f.rule not in unevaluated]
    info = tuple(f for f in evaluated if f.outcome == KOS.Info)
    findings = tuple(f for f in evaluated if f.outcome != KOS.Info)
    worst = _worst([f for f in findings if not f.provisional])
    decision = worst or ("pending" if unevaluated else "acceptable")
    logger.debug(
        "判定の後処理: %s（未確認 %s、評価できず %d）", decision, unconfirmed, len(unevaluated)
    )
    return Assessment(
        decision=decision,
        has_unconfirmed=bool(unconfirmed),
        unconfirmed=unconfirmed,
        findings=findings,
        info=info,
        unevaluated=unevaluated,
        applicable=applicable,
        provisional_decision=_worst([f for f in findings if f.provisional]),
        judgment=j,
    )
