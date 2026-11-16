"""事案データの判定。派生値を足し、判定シェイプを当て、結果からルール・審査項目・版を引く。"""

import logging
from dataclasses import dataclass

from pyshacl import validate
from rdflib import RDF, Graph, URIRef
from rdflib.namespace import SH

from semantica_agent.derive import derive
from semantica_agent.namespaces import KOS, bind_prefixes

logger = logging.getLogger(__name__)

SEVERITY_ORDER = (KOS.Reject, KOS.NeedsCorrection, KOS.NeedsInquiry, KOS.AdditionalProcedure)
_MAX_SHAPE_DEPTH = 5


class JudgeError(RuntimeError):
    pass


@dataclass(frozen=True)
class Finding:
    rule: URIRef
    outcome: URIRef
    check: URIRef | None
    versions: tuple[URIRef, ...]
    focus: URIRef
    message: str
    provisional: bool


@dataclass(frozen=True)
class Judgment:
    case: URIRef
    findings: tuple[Finding, ...]
    decision: URIRef | None
    derived: Graph


def _rule_of_shape(rules: Graph, shape) -> tuple[URIRef | None, object]:
    """シェイプ（property shape なら親をたどる）に対応するルールと、たどった先のシェイプ。"""
    current = shape
    for _ in range(_MAX_SHAPE_DEPTH):
        rule = rules.value(predicate=KOS.shape, object=current)
        if rule is not None:
            return rule, current
        parent = next(iter(rules.subjects(None, current)), None)
        if parent is None:
            break
        current = parent
    return None, current


def _message(report: Graph, result, rules: Graph, shapes: list) -> str:
    for shape in shapes:
        msg = rules.value(shape, SH.message)
        if msg is not None:
            return str(msg)
    return str(report.value(result, SH.resultMessage) or "")


def _finding(report: Graph, result, rules: Graph, ontology: Graph) -> Finding:
    shape = report.value(result, SH.sourceShape)
    rule, top = _rule_of_shape(rules, shape)
    if rule is None:
        raise JudgeError(f"検証結果のシェイプに対応するルールがありません: {top}")
    outcome = rules.value(rule, KOS.outcome)
    if outcome is None:
        raise JudgeError(f"ルールに kos:outcome がありません: {rule}")
    versions = tuple(sorted(rules.objects(rule, KOS.underVersion)))
    # 下書きの現行版（e-Gov 由来、未承認）に基づく判定だけを暫定にする（仕様 §5.5）。
    # 手順書時点の版は手順書から起こしたもので、承認の対象ではない。
    provisional = any(
        (v, KOS.reviewStatus, KOS.LlmDraft) in ontology
        and (v, KOS.versionStatus, KOS.Manual) not in ontology
        for v in versions
    )
    return Finding(
        rule=rule,
        outcome=outcome,
        check=rules.value(rule, KOS.implementsCheck),
        versions=versions,
        focus=report.value(result, SH.focusNode),
        message=_message(report, result, rules, [shape, top]),
        provisional=provisional,
    )


def _decision(findings: list[Finding]) -> URIRef | None:
    outcomes = {f.outcome for f in findings if not f.provisional}
    return next((o for o in SEVERITY_ORDER if o in outcomes), None)


def judge(case: Graph, case_iri: URIRef, ontology: Graph, rules: Graph) -> Judgment:
    derived = derive(case, case_iri, ontology)
    data = bind_prefixes(Graph())
    for g in (derived, ontology):
        for t in g:
            data.add(t)
    _, report, _ = validate(data, shacl_graph=rules, advanced=True, allow_warnings=True)
    findings = [
        _finding(report, r, rules, ontology)
        for r in report.subjects(RDF.type, SH.ValidationResult)
        if report.value(r, SH.focusNode) == case_iri
    ]
    findings.sort(key=lambda f: (str(f.rule), f.message))
    for f in findings:
        logger.debug("判定: %s → %s（暫定=%s）", f.rule, f.outcome, f.provisional)
    return Judgment(case_iri, tuple(findings), _decision(findings), derived)
