"""Competency questions（仕様 §8）。期待する答えは手順書の PDF と照合して確定した。"""

from pathlib import Path

import pytest
from rdflib import URIRef

from semantica_agent.core.ids import short_id
from semantica_agent.core.namespaces import KD
from semantica_agent.core.turtle_io import load_ontology

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def ontology():
    return load_ontology(ROOT / "ontology")


def _fmt(v):
    if isinstance(v, URIRef) and str(v).startswith(str(KD)):
        return short_id(v)
    if isinstance(v, URIRef):
        return str(v).split("#")[-1]
    return None if v is None else str(v)


def run_cq(ontology, name: str) -> set[tuple]:
    query = (ROOT / "ontology" / "cq" / f"{name}.rq").read_text(encoding="utf-8")
    return {tuple(_fmt(x) for x in row) for row in ontology.query(query)}


def column(rows: set[tuple], i: int = 0) -> set:
    return {r[i] for r in rows}


def test_cq01_birth_review_checks_and_provisions(ontology):
    rows = run_cq(ontology, "cq01")
    assert column(rows) == {f"BIRTH-S2-I{n}" for n in (1, 2, 3, 4, 5, 6, 8, 10, 11, 13)}
    cites = {(i, p) for i, p in rows if p}
    assert cites == {
        ("BIRTH-S2-I1", "LAW-KOSEKI-HO-25"), ("BIRTH-S2-I1", "LAW-KOSEKI-HO-51"),
        ("BIRTH-S2-I2", "LAW-KOSEKI-HO-52-P1"), ("BIRTH-S2-I2", "LAW-KOSEKI-HO-52-P2"),
        ("BIRTH-S2-I3", "LAW-KOSEKI-HO-49-P3"),
        ("BIRTH-S2-I4", "LAW-MINPO-790"), ("BIRTH-S2-I4", "LAW-KOSEKI-HO-50"),
        ("BIRTH-S2-I4", "LAW-KOSEKI-HO-KISOKU-60"),
        ("BIRTH-S2-I5", "LAW-MINPO-772"), ("BIRTH-S2-I5", "LAW-MINPO-789"),
        ("BIRTH-S2-I5", "LAW-MINPO-790-P1"), ("BIRTH-S2-I5", "LAW-KOSEKI-HO-62"),
        ("BIRTH-S2-I10", "LAW-KOSEKI-HO-18-P1"), ("BIRTH-S2-I10", "LAW-KOSEKI-HO-18-P2"),
        ("BIRTH-S2-I11", "LAW-KOSEKI-HO-49"), ("BIRTH-S2-I13", "LAW-JUKI-HO-9-P2"),
    }  # fmt: skip


def test_cq02_kisoku_48(ontology):
    assert column(run_cq(ontology, "cq02")) == {"BIRTH-S7", "MARRIAGE-S8", "DIVORCE-S7", "DEATH-S7"}


def test_cq03_koseki_ho_48(ontology):
    assert column(run_cq(ontology, "cq03")) == {"BIRTH-S4", "MARRIAGE-S4", "DIVORCE-S4", "DEATH-S4"}


def test_cq04_inquiry_to_legal_affairs_bureau(ontology):
    assert column(run_cq(ontology, "cq04")) == {
        "BIRTH-S2-I3.1", "BIRTH-S2-I7", "BIRTH-S2-I9", "DEATH-S2-I3"
    }  # fmt: skip


def test_cq05_late_filing(ontology):
    assert run_cq(ontology, "cq05") == {
        ("BIRTH-S2-I12", "DOCUMENT-DELAY-REASON", "ORGANIZATION-SUMMARY-COURT"),
        ("DEATH-S2-I5.1", "DOCUMENT-DELAY-REASON", "ORGANIZATION-SUMMARY-COURT"),
    }


def test_cq06_checks_affected_by_amendments(ontology):
    assert run_cq(ontology, "cq06") == {
        ("BIRTH-S2-I5", "Changed", "AMENDMENT-R4-102"),
        ("MARRIAGE-S2-I4", "Obsolete", "AMENDMENT-R4-102"),
        ("MARRIAGE-S2-I2", "Changed", "AMENDMENT-H30-59"),
        ("MARRIAGE-S2-I2.1", "Obsolete", "AMENDMENT-H30-59"),
        ("DIVORCE-S2-I5.2", "Changed", "AMENDMENT-R6-33"),
    }


def test_cq07_minpo_733(ontology):
    assert run_cq(ontology, "cq07") == {("Repealed", "AMENDMENT-R4-102", "2024-04-01")}


def test_cq08_non_honseki_filing(ontology):
    assert column(run_cq(ontology, "cq08")) == {
        "BIRTH-S1", "BIRTH-S5", "DIVORCE-S5", "DEATH-S5", "MARRIAGE-S1"
    }  # fmt: skip


def test_cq09_documents_for_agent(ontology):
    assert column(run_cq(ontology, "cq09")) == {
        "DOCUMENT-POWER-OF-ATTORNEY",
        "DOCUMENT-FAMILY-REGISTER-COPY",
        "DOCUMENT-GUARDIANSHIP-REGISTRATION-CERTIFICATE",
        "DOCUMENT-COURT-COPY",
    }


def test_cq10_requester_types_and_provisions(ontology):
    assert run_cq(ontology, "cq10") == {
        ("CONDITION-BY-AGENT", "LAW-KOSEKI-HO-10-3"),
        ("CONDITION-BY-AGENT", "LAW-KOSEKI-HO-KISOKU-11-4"),
        ("CONDITION-PUBLIC-AGENCY-REQUEST", "LAW-KOSEKI-HO-10-2-P2"),
        ("CONDITION-PUBLIC-AGENCY-REQUEST", "LAW-KOSEKI-HO-10-3-P1"),
        ("CONDITION-PUBLIC-AGENCY-REQUEST", "LAW-KOSEKI-HO-KISOKU-11-3"),
        ("CONDITION-PUBLIC-AGENCY-REQUEST", "LAW-KOSEKI-HO-KISOKU-11-3-I1"),
        ("CONDITION-THIRD-PARTY-REQUEST", "LAW-KOSEKI-HO-10-2-P1"),
        ("CONDITION-THIRD-PARTY-REQUEST", "LAW-KOSEKI-HO-10-3"),
        ("CONDITION-DESIGNATED-AGENT-REQUEST", "LAW-KOSEKI-HO-10-2-P3"),
        ("CONDITION-DESIGNATED-AGENT-REQUEST", "LAW-KOSEKI-HO-10-2-P4"),
        ("CONDITION-DESIGNATED-AGENT-REQUEST", "LAW-KOSEKI-HO-10-2-P5"),
        ("CONDITION-DESIGNATED-AGENT-REQUEST", "LAW-KOSEKI-HO-KISOKU-11-2-I4"),
    }


def test_cq11_koseki_ho_27_2(ontology):
    assert column(run_cq(ontology, "cq11")) == {
        "BIRTH-S1-I2.3", "MARRIAGE-S1-I3", "MARRIAGE-S2-I5", "MARRIAGE-S5-I1",
        "DIVORCE-S1-I2.3", "DIVORCE-S1-I3.1",
    }  # fmt: skip


def test_cq12_source_of_filing_period_check(ontology):
    rows = run_cq(ontology, "cq12")
    assert {r[:5] for r in rows} == {
        ("3", "2", "○届出期間内の届出か。 戸籍法第49条", "LAW-KOSEKI-HO-49", "14")
    }
    assert column(rows, 5) == {"CurrentLawSource"}
    assert all(url.startswith("https://laws.e-gov.go.jp/") for url in column(rows, 6))


def test_cq13_rule_traces_to_check_version_amendment_and_egov(ontology):
    [(check, page, version, amendment, kind, url)] = run_cq(ontology, "cq13")
    assert (check, version, amendment) == (
        "BIRTH-S2-I5", "LAW-MINPO-772-V20240401", "AMENDMENT-R4-102"
    )  # fmt: skip
    assert page == "2" and kind == "CurrentLawSource"
    assert url.startswith("https://laws.e-gov.go.jp/")


def test_cq14_checks_without_rules(ontology):
    assert column(run_cq(ontology, "cq14")) == {"BIRTH-S2-I4"}


def test_cq15_speculation_nodes_have_reasons(ontology):
    rows = run_cq(ontology, "cq15")
    assert rows and all(reason.startswith("推測") for _, reason in rows)
