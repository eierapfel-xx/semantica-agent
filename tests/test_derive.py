from dataclasses import replace
from datetime import date, timedelta

import pytest
from rdflib import RDF, Graph, Literal
from rdflib.namespace import PROV, XSD

from semantica_agent.derive import (
    DERIVED_VALUES,
    DeriveError,
    PeriodRule,
    age_on,
    days_between,
    derive,
    derived_definitions_graph,
    filing_deadline,
    is_closed_day,
    read_period_rule,
)
from semantica_agent.ids import derived_iri
from semantica_agent.namespaces import KCASE, KOS

RULE_14 = PeriodRule(days=14, count_first_day=True, extend_on_holiday=True)


def test_deadline_counts_first_day():
    # 2026-11-02 を 1 日目に数えると 14 日目は 11-15（日曜）なので、11-16（月）に延びる
    assert filing_deadline(date(2026, 11, 2), RULE_14) == date(2026, 11, 16)


def test_deadline_without_extension():
    rule = replace(RULE_14, extend_on_holiday=False)
    assert filing_deadline(date(2026, 11, 2), rule) == date(2026, 11, 15)


def test_deadline_without_first_day():
    rule = PeriodRule(days=14, count_first_day=False, extend_on_holiday=False)
    assert filing_deadline(date(2026, 11, 2), rule) == date(2026, 11, 16)


def test_deadline_skips_new_year():
    assert filing_deadline(date(2026, 12, 18), RULE_14) == date(2027, 1, 4)


def test_closed_days():
    assert is_closed_day(date(2026, 11, 23))  # 勤労感謝の日
    assert is_closed_day(date(2026, 12, 29))
    assert not is_closed_day(date(2026, 11, 24))


@pytest.mark.parametrize("days", [199, 200, 300, 301])
def test_days_between_boundary(days):
    assert days_between(date(2025, 1, 1), date(2025, 1, 1) + timedelta(days=days)) == days


def test_age_on_birthday_eve():
    assert age_on(date(1976, 5, 10), date(2026, 5, 9)) == 49
    assert age_on(date(1976, 5, 10), date(2026, 5, 10)) == 50


def test_age_on_leap_day():
    assert age_on(date(2008, 2, 29), date(2026, 2, 28)) == 17
    assert age_on(date(2008, 2, 29), date(2026, 3, 1)) == 18


def _ontology():
    g = derived_definitions_graph()
    p = derived_iri("birth-filing-period")
    g.add((p, RDF.type, KOS.DerivedValue))
    g.add((p, KOS.periodDays, Literal(14)))
    g.add((p, KOS.countFirstDay, Literal(True)))
    g.add((p, KOS.extendOnHoliday, Literal(True)))
    return g


def _case(**values):
    g = Graph()
    c = KCASE.c1
    g.add((c, RDF.type, KOS.BirthFiling))
    for k, v in values.items():
        g.add((c, KOS[k], Literal(date.fromisoformat(v), datatype=XSD.date)))
    return g


def test_read_period_rule():
    assert read_period_rule(_ontology()) == RULE_14


def test_read_period_rule_missing():
    with pytest.raises(DeriveError, match="birth-filing-period"):
        read_period_rule(Graph())


def test_definitions_graph_has_all_values():
    g = derived_definitions_graph()
    for d in DERIVED_VALUES:
        assert (derived_iri(d.slug), RDF.type, KOS.DerivedValue) in g


def test_derive_adds_values_with_provenance():
    case = _case(childBirthDate="2026-11-02", filingDate="2026-11-20", motherBirthDate="1990-01-01")
    g = derive(case, KCASE.c1, _ontology())
    assert g.value(KCASE.c1, KOS.filingDeadline) == Literal(date(2026, 11, 16), datatype=XSD.date)
    assert g.value(KCASE.c1, KOS.daysLate).toPython() == 4
    assert g.value(KCASE.c1, KOS.motherAgeAtBirth).toPython() == 36
    assert g.value(KCASE.c1, KOS.childAgeAtFiling).toPython() == 0
    d = KCASE["c1/derived/days-late"]
    assert (d, PROV.wasGeneratedBy, derived_iri("days-late")) in g
    assert (d, PROV.wasDerivedFrom, KOS.filingDate) in g
    assert (KCASE.c1, KOS.daysLate, None) not in case  # 元を変えない


def test_derive_in_time_has_zero_days_late():
    g = derive(_case(childBirthDate="2026-11-02", filingDate="2026-11-16"), KCASE.c1, _ontology())
    assert g.value(KCASE.c1, KOS.daysLate).toPython() == 0


def test_derive_skips_missing_inputs():
    g = derive(_case(childBirthDate="2026-11-02", filingDate="2026-11-16"), KCASE.c1, _ontology())
    assert g.value(KCASE.c1, KOS.daysFromMarriageToBirth) is None


def test_derive_marriage_days():
    case = _case(
        childBirthDate="2025-07-20", parentsMarriageDate="2025-01-01", filingDate="2025-07-25"
    )
    g = derive(case, KCASE.c1, _ontology())
    assert g.value(KCASE.c1, KOS.daysFromMarriageToBirth).toPython() == 200
