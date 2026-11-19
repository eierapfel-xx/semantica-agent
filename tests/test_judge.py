from datetime import date
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal
from rdflib.namespace import XSD

from semantica_agent.core.namespaces import KCASE, KD, KOS
from semantica_agent.review.judge import JudgeError, judge

FX = Path(__file__).parent / "fixtures"


@pytest.fixture
def ont():
    return Graph().parse(FX / "mini_ontology.ttl")


@pytest.fixture
def rules():
    return Graph().parse(FX / "mini_rules.ttl")


def case(birth, filed, **extra):
    g = Graph()
    c = KCASE.c1
    g.add((c, RDF.type, KOS.BirthFiling))
    g.add((c, KOS.childBirthDate, Literal(date.fromisoformat(birth), datatype=XSD.date)))
    g.add((c, KOS.filingDate, Literal(date.fromisoformat(filed), datatype=XSD.date)))
    for k, v in extra.items():
        lit = (
            Literal(date.fromisoformat(v), datatype=XSD.date) if k.endswith("Date") else Literal(v)
        )
        g.add((c, KOS[k], lit))
    return g


def legitimacy_case(birth):
    return case(birth, birth, parentsMarriageDate="2020-01-01", statedRelationship="嫡出でない子")


def test_late_filing_gives_additional_procedure(ont, rules):
    j = judge(case("2026-11-02", "2026-11-20"), KCASE.c1, ont, rules)
    assert j.decision == KOS.AdditionalProcedure
    [f] = j.findings
    assert f.rule == KD["rule/birth/filing-period"] and f.check == KD["birth/step/2/item/9"]
    assert f.outcome == KOS.AdditionalProcedure
    assert f.versions == (KD["law/koseki-ho/art/49/version/manual"],)
    assert f.focus == KCASE.c1 and not f.provisional


def test_in_time_filing_has_no_findings(ont, rules):
    j = judge(case("2026-11-02", "2026-11-16"), KCASE.c1, ont, rules)
    assert j.decision is None and j.findings == ()


def test_derived_values_are_returned(ont, rules):
    j = judge(case("2026-11-02", "2026-11-20"), KCASE.c1, ont, rules)
    assert j.derived.value(KCASE.c1, KOS.daysLate).toPython() == 4


@pytest.mark.parametrize("birth,applies", [("2024-03-31", False), ("2024-04-01", True)])
def test_version_boundary(ont, rules, birth, applies):
    j = judge(legitimacy_case(birth), KCASE.c1, ont, rules)
    hit = any(f.rule == KD["rule/birth/legitimacy-current"] for f in j.findings)
    assert hit == applies


def test_llm_draft_version_is_provisional(ont, rules):
    v = KD["law/minpo/art/772/version/2024-04-01"]
    ont.remove((v, KOS.reviewStatus, None))
    ont.add((v, KOS.reviewStatus, KOS.LlmDraft))
    j = judge(legitimacy_case("2025-01-01"), KCASE.c1, ont, rules)
    [f] = [f for f in j.findings if f.rule == KD["rule/birth/legitimacy-current"]]
    assert f.provisional and j.decision is None


def test_most_severe_outcome_wins(ont, rules):
    g = legitimacy_case("2025-01-01")
    g.remove((KCASE.c1, KOS.filingDate, None))
    g.add((KCASE.c1, KOS.filingDate, Literal(date(2025, 2, 1), datatype=XSD.date)))
    j = judge(g, KCASE.c1, ont, rules)
    assert {f.outcome for f in j.findings} == {KOS.NeedsCorrection, KOS.AdditionalProcedure}
    assert j.decision == KOS.NeedsCorrection


def test_result_without_rule_is_error(ont, rules):
    rules.remove((KD["rule/birth/filing-period"], KOS.shape, None))
    with pytest.raises(JudgeError, match="filing-period"):
        judge(case("2026-11-02", "2026-11-20"), KCASE.c1, ont, rules)


def test_message_is_kept(ont, rules):
    j = judge(case("2026-11-02", "2026-11-20"), KCASE.c1, ont, rules)
    assert "届出期間" in j.findings[0].message


def test_llm_draft_manual_version_is_not_provisional(ont, rules):
    v = KD["law/koseki-ho/art/49/version/manual"]
    ont.remove((v, KOS.reviewStatus, None))
    ont.add((v, KOS.reviewStatus, KOS.LlmDraft))
    j = judge(case("2026-11-02", "2026-11-20"), KCASE.c1, ont, rules)
    assert not j.findings[0].provisional and j.decision == KOS.AdditionalProcedure


def test_missing_inputs_are_reported(ont, rules):
    g = case("2026-11-02", "2026-11-20")
    g.remove((KCASE.c1, KOS.childBirthDate, None))
    j = judge(g, KCASE.c1, ont, rules)
    assert KOS.childBirthDate in j.missing_inputs


def test_complete_case_has_no_missing_inputs(ont, rules):
    g = case("2026-11-02", "2026-11-16")
    for p, v in (
        ("filingMunicipality", "A"),
        ("honsekiMunicipality", "A"),
        ("statedRelationship", "嫡出子"),
        ("motherBirthDate", None),
        ("familyRegisterExists", True),
        ("addressExists", True),
    ):
        lit = Literal(date(1990, 1, 1), datatype=XSD.date) if v is None else Literal(v)
        g.add((KCASE.c1, KOS[p], lit))
    g.add((KCASE.c1, KOS.notifierRole, KD["role/mother"]))
    assert judge(g, KCASE.c1, ont, rules).missing_inputs == ()


def test_provisional_decision_is_kept(ont, rules):
    v = KD["law/minpo/art/772/version/2024-04-01"]
    ont.remove((v, KOS.reviewStatus, None))
    ont.add((v, KOS.reviewStatus, KOS.LlmDraft))
    j = judge(legitimacy_case("2025-01-01"), KCASE.c1, ont, rules)
    assert j.decision is None and j.provisional_decision == KOS.NeedsCorrection


def test_sparql_value_and_substituted_message(ont, rules):
    shape = KD["shape/birth/missing"]
    from rdflib.namespace import SH

    rule = KD["rule/birth/missing"]
    rules.add((rule, KOS.shape, shape))
    rules.add((rule, KOS.outcome, KOS.NeedsCorrection))
    rules.add((shape, RDF.type, SH.NodeShape))
    rules.add((shape, SH.targetClass, KOS.BirthFiling))
    rules.add((shape, SH.message, Literal("記載事項 {?value} が無い")))
    sparql = KD["shape/birth/missing/sparql"]
    rules.add((shape, SH.sparql, sparql))
    rules.add((sparql, SH.prefixes, KD.prefixes))
    rules.add(
        (
            sparql,
            SH.select,
            Literal(
                "SELECT $this ?value WHERE { $this a kos:BirthFiling . "
                "BIND(<https://semantica-agent.example/koseki/id/record-item/x> AS ?value) }"
            ),
        )
    )
    j = judge(case("2026-11-02", "2026-11-10"), KCASE.c1, ont, rules)
    [f] = [f for f in j.findings if f.rule == rule]
    assert f.value == KD["record-item/x"]
    assert "{?value}" not in f.message
