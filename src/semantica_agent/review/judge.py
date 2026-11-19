"""事案データの判定。派生値を足し、判定シェイプを当て、結果からルール・審査項目・版を引く。"""

import logging
from dataclasses import dataclass

from pyshacl import validate
from rdflib import RDF, Graph, URIRef
from rdflib.namespace import SH

from semantica_agent.core.namespaces import KOS, bind_prefixes
from semantica_agent.review.derive import derive

logger = logging.getLogger(__name__)

SEVERITY_ORDER = (KOS.Reject, KOS.NeedsCorrection, KOS.NeedsInquiry, KOS.AdditionalProcedure)
_MAX_SHAPE_DEPTH = 5
# 出生届の判定に要る入力（仕様 §4.4）。欠けていればルールが黙って評価されないので、明示して返す。
BIRTH_REQUIRED_INPUTS = tuple(
    KOS[p]
    for p in (
        "childBirthDate", "filingDate", "filingMunicipality", "honsekiMunicipality",
        "notifierRole", "statedRelationship", "motherBirthDate", "familyRegisterExists",
        "addressExists",
    )
)  # fmt: skip


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
    value: object = None  # 指摘の対象の値（足りない記載事項など。sh:value）


@dataclass(frozen=True)
class Judgment:
    """判定の結果。missing_inputs があれば一部のルールは評価されていない。"""

    case: URIRef
    findings: tuple[Finding, ...]
    decision: URIRef | None
    derived: Graph
    missing_inputs: tuple[URIRef, ...] = ()
    provisional_decision: URIRef | None = (
        None  # 暫定の指摘（未承認の現行版に基づく）だけから見た判定
    )

    @property
    def complete(self) -> bool:
        return not self.missing_inputs


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


def _message(report: Graph, result, rules: Graph, source, top) -> str:
    # 結果を出したシェイプ自身に sh:message があれば、pyshacl が {?value} 等を埋めた文を使う。
    # 無ければ（property shape など）、ルールのシェイプの sh:message を使う。
    if rules.value(source, SH.message) is None and rules.value(top, SH.message) is not None:
        return str(rules.value(top, SH.message))
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
        message=_message(report, result, rules, shape, top),
        provisional=provisional,
        value=report.value(result, SH.value),
    )


def _decision(findings: list[Finding], provisional: bool = False) -> URIRef | None:
    outcomes = {f.outcome for f in findings if f.provisional == provisional}
    return next((o for o in SEVERITY_ORDER if o in outcomes), None)


def judge(case: Graph, case_iri: URIRef, ontology: Graph, rules: Graph) -> Judgment:
    derived = derive(case, case_iri, ontology)
    data = bind_prefixes(Graph())
    # ルールのノード（kos:underVersion 等）も入れる。シェイプが自分のルールから版を引くため。
    for g in (derived, ontology, rules):
        for t in g:
            data.add(t)
    _, report, _ = validate(data, shacl_graph=rules, advanced=True, allow_warnings=True)
    findings = [
        _finding(report, r, rules, ontology)
        for r in report.subjects(RDF.type, SH.ValidationResult)
        if report.value(r, SH.focusNode) == case_iri
    ]
    findings.sort(key=lambda f: (str(f.rule), str(f.value), f.message))
    for f in findings:
        logger.debug("判定: %s → %s（暫定=%s）", f.rule, f.outcome, f.provisional)
    missing = tuple(p for p in BIRTH_REQUIRED_INPUTS if (case_iri, p, None) not in case)
    if missing:
        logger.warning("判定に要る入力が欠けています: %s", ", ".join(str(p) for p in missing))
    return Judgment(
        case_iri,
        tuple(findings),
        _decision(findings),
        derived,
        missing_inputs=missing,
        provisional_decision=_decision(findings, provisional=True),
    )
