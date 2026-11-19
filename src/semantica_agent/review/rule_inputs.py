"""判定ルールの使う入力と、出生日で適用されるルール。仕様 §5.1.1・§7.2。"""

import re
from datetime import date

from rdflib import RDF, BNode, Graph, Literal, URIRef

from semantica_agent.core.namespaces import KOS
from semantica_agent.review.case_input import FIELDS_BY_NAME
from semantica_agent.review.derive import DERIVED_VALUES

_KOS_NAME = re.compile(r"kos:(\w+)|" + re.escape(str(KOS)) + r"(\w+)")
_DERIVED_INPUTS = {d.output: d.inputs for d in DERIVED_VALUES}


def _expand(name: str) -> set[str]:
    """派生値の名前を、元の事案の項目に置き換える（派生値の入力が派生値でも辿る）。"""
    if name not in _DERIVED_INPUTS:
        return {name}
    return set().union(*(_expand(i) for i in _DERIVED_INPUTS[name]))


def _names_in_shape(rules: Graph, shape) -> set[str]:
    names: set[str] = set()
    seen, todo = set(), [shape]
    while todo:
        node = todo.pop()
        if node in seen:
            continue
        seen.add(node)
        for _, o in rules.predicate_objects(node):
            if isinstance(o, BNode):
                todo.append(o)
            elif isinstance(o, URIRef) and str(o).startswith(str(KOS)):
                names.add(str(o).removeprefix(str(KOS)))
            elif isinstance(o, Literal):
                names |= {a or b for a, b in _KOS_NAME.findall(str(o))}
    return names


def rule_inputs(rules: Graph) -> dict[URIRef, frozenset[str]]:
    """ルールごとに、シェイプに現れる事案の項目（派生値は元の項目に直す）。"""
    out = {}
    for rule in rules.subjects(RDF.type, KOS.JudgmentRule):
        names: set[str] = set()
        for shape in rules.objects(rule, KOS.shape):
            for n in _names_in_shape(rules, shape):
                names |= _expand(n)
        out[rule] = frozenset(n for n in names if n in FIELDS_BY_NAME)
    return out


def _version_covers(ontology: Graph, version, birth: date) -> bool:
    vf = ontology.value(version, KOS.validFrom)
    vu = ontology.value(version, KOS.validUntil)
    return (vf is None or vf.toPython() <= birth) and (vu is None or birth < vu.toPython())


def applicable_rules(rules: Graph, ontology: Graph, birth: date | None) -> frozenset[URIRef]:
    """出生日に適用されるルール。版の無いルールと出生日が不明のときは常に、ほかは版の期間に入るとき。"""
    out = set()
    for rule in rules.subjects(RDF.type, KOS.JudgmentRule):
        versions = list(rules.objects(rule, KOS.underVersion))
        # 出生日が分からなければ版を選べないので外さない（未確認の扱いは assess が決める）
        if (
            not versions
            or birth is None
            or any(_version_covers(ontology, v, birth) for v in versions)
        ):
            out.add(rule)
    return frozenset(out)
