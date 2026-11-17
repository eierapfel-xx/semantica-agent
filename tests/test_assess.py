import pytest
from case_helpers import UNKNOWN, case_changes, full_case

from semantica_agent.assess import assess
from semantica_agent.ids import short_id
from semantica_agent.namespaces import KCASE, KD, KOS
from semantica_agent.rule_inputs import rule_inputs


@pytest.fixture(scope="module")
def inputs(rules):
    return rule_inputs(rules)


def run(onto, rules, inputs, **changes):
    return assess(full_case(onto, **changes), KCASE.t1, onto, rules, inputs)


def test_full_base_case_is_acceptable(onto, rules, inputs):
    a = run(onto, rules, inputs)
    assert a.decision == "acceptable" and not a.has_unconfirmed and not a.unevaluated


def test_unconfirmed_document_does_not_raise_inquiry(onto, rules, inputs):
    a = run(onto, rules, inputs, attachedDocument=UNKNOWN)
    assert not any(short_id(f.rule) == "RULE-BIRTH-BIRTH-CERTIFICATE" for f in a.findings)
    assert a.unevaluated[KD["rule/birth/birth-certificate"]] == ("attachedDocument",)
    assert a.decision == "pending" and a.has_unconfirmed


def test_incomplete_document_list_is_unconfirmed(onto, rules, inputs):
    doc = {
        "status": "given",
        "items": ["DOCUMENT-BIRTH-CERTIFICATE"],
        "complete": False,
        "quote": "q",
    }
    a = run(onto, rules, inputs, attachedDocument=doc)
    assert KD["rule/birth/birth-certificate"] in a.unevaluated


def test_confirmed_missing_document_raises_inquiry(onto, rules, inputs):
    a = run(onto, rules, inputs, **case_changes("b3-no-certificate"))
    assert a.decision == "needsInquiry"


def test_finding_with_unconfirmed_keeps_severity(onto, rules, inputs):
    a = run(onto, rules, inputs, filingDate="2026-11-20", motherBirthDate=UNKNOWN)
    assert a.decision == "additionalProcedure" and a.has_unconfirmed
    assert "motherBirthDate" in a.unconfirmed


def test_none_required_input_is_unconfirmed(onto, rules, inputs):
    a = run(onto, rules, inputs, motherBirthDate=None)
    assert "motherBirthDate" in a.unconfirmed and a.decision == "pending"


def test_remarriage_not_needed_without_previous_marriage(onto, rules, inputs):
    a = run(onto, rules, inputs, motherRemarriedBeforeBirth=UNKNOWN)
    assert a.decision == "acceptable"


def test_remarriage_needed_with_previous_marriage(onto, rules, inputs):
    a = run(
        onto,
        rules,
        inputs,
        motherPrevMarriageEndDate="2026-01-01",
        motherRemarriedBeforeBirth=UNKNOWN,
    )
    assert "motherRemarriedBeforeBirth" in a.unconfirmed


def test_info_is_separated(onto, rules, inputs):
    a = run(onto, rules, inputs, **case_changes("boundary-2024-04-01"))
    assert a.info and all(f.outcome == KOS.Info for f in a.info)
    assert all(f.outcome != KOS.Info for f in a.findings)
    assert a.decision == "needsCorrection"


@pytest.mark.parametrize("case", ["b1-wrong-place", "b9-late", "b11-missing-item", "ok"])
def test_matches_fixture_decision_when_complete(onto, rules, inputs, birth_cases, case):
    expected = next(c for c in birth_cases["cases"] if c["id"] == case)["decision"]
    a = run(onto, rules, inputs, **case_changes(case))
    want = expected[0].lower() + expected[1:] if expected else "acceptable"
    assert a.decision == want


def test_list_none_means_confirmed_empty(onto, rules, inputs):
    a = run(onto, rules, inputs, attachedDocument={"status": "none", "quote": "添付なし"})
    assert "attachedDocument" not in a.unconfirmed
    assert a.decision == "needsInquiry"


def test_unknown_birth_date_marks_versioned_rules_unevaluated(onto, rules, inputs):
    a = run(onto, rules, inputs, childBirthDate=UNKNOWN)
    assert "childBirthDate" in a.unevaluated[KD["rule/birth/filing-place"]]
    assert KD["rule/birth/legitimacy-current"] in a.unevaluated
