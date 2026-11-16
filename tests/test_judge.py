from datetime import date
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal
from rdflib.namespace import XSD

from semantica_agent.judge import JudgeError, judge
from semantica_agent.namespaces import KCASE, KD, KOS

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
