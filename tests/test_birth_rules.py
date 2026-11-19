"""出生届の判定ルールを、事案と正解表（ユーザーの承認済み）で固定する。"""

import json
from datetime import date, time
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal
from rdflib.namespace import XSD

from semantica_agent.core.ids import short_id
from semantica_agent.core.namespaces import KCASE, KD, KOS
from semantica_agent.core.turtle_io import load_ontology
from semantica_agent.review.judge import judge

ROOT = Path(__file__).resolve().parents[1]
CASES = json.loads((Path(__file__).parent / "fixtures/birth_cases/cases.json").read_text("utf-8"))
IRI_FIELDS = {"notifierRole": "role", "attachedDocument": "document", "recordedItem": "record-item"}


def _literal(key, value):
    if key.endswith("Date"):
        return Literal(date.fromisoformat(value), datatype=XSD.date)
    if key.endswith("Time"):
        return Literal(time.fromisoformat(value), datatype=XSD.time)
    return Literal(value)


def build_case(changes: dict) -> Graph:
    fields = {**CASES["base"], **changes}
    g = Graph()
    g.add((KCASE.c1, RDF.type, KOS.BirthFiling))
    for key, value in fields.items():
        if value is None:
            continue
        values = value if isinstance(value, list) else [value]
        for v in values:
            obj = KD[f"{IRI_FIELDS[key]}/{v}"] if key in IRI_FIELDS else _literal(key, v)
            g.add((KCASE.c1, KOS[key], obj))
    return g


@pytest.fixture(scope="module")
def ontology():
    return load_ontology(ROOT / "ontology")


@pytest.fixture(scope="module")
def rules():
    return Graph().parse(ROOT / "ontology/rules/birth-rules.ttl")


@pytest.mark.parametrize("case", CASES["cases"], ids=lambda c: c["id"])
def test_birth_case(case, ontology, rules):
    j = judge(build_case(case["changes"]), KCASE.c1, ontology, rules)
    decision = str(j.decision).split("#")[-1] if j.decision else None
    assert decision == case["decision"]
    assert {short_id(f.rule) for f in j.findings if not f.provisional} == set(case["rules"])
    assert {str(p).split("#")[-1] for p in j.missing_inputs} == set(case.get("missing", []))


def test_every_finding_traces_to_source(ontology, rules):
    for case in CASES["cases"]:
        for f in judge(build_case(case["changes"]), KCASE.c1, ontology, rules).findings:
            assert f.check is not None and ontology.value(f.check, KOS.hasSource) is not None
            assert all(
                ontology.value(v, KOS.hasSource) is not None
                or (v, KOS.versionStatus, KOS.Manual) in ontology
                for v in f.versions
            )


def test_expected_table_is_approved():
    assert CASES["approved_by"], "正解表はユーザーの承認が要る（仕様 §5.5）"
