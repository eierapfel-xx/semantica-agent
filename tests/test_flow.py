import pytest
from case_helpers import UNKNOWN, full_case

from semantica_agent.assess import assess
from semantica_agent.flow import (
    BUSINESSES,
    case_states,
    flow_shape,
    merge_states,
    pick_business,
    replay,
    step_states,
)
from semantica_agent.namespaces import KCASE
from semantica_agent.rule_inputs import rule_inputs


@pytest.fixture(scope="module")
def inputs(rules):
    return rule_inputs(rules)


def states(onto, rules, inputs, **changes):
    a = assess(full_case(onto, **changes), KCASE.t1, onto, rules, inputs)
    return case_states(a, rules, onto)


def test_birth_flow_shape(onto):
    s = flow_shape(onto, "birth")
    assert [st["number"] for st in s["steps"]] == [1, 2, 3, 4, 5, 6, 7]
    assert len(s["steps"][1]["items"]) == 13
    i5 = s["steps"][1]["items"][4]
    assert i5["id"] == "BIRTH-S2-I5" and i5["kind"] == "check" and len(i5["children"]) == 4
    assert s["steps"][0]["items"][2]["conditions"] == ["非本籍地に届出された場合"]


@pytest.mark.parametrize("business", BUSINESSES)
def test_all_business_shapes(onto, business):
    assert flow_shape(onto, business)["steps"]


def test_unknown_business_rejected(onto):
    with pytest.raises(ValueError):
        flow_shape(onto, "adoption")


def test_full_case_states(onto, rules, inputs):
    st = states(onto, rules, inputs)
    assert st["BIRTH-S2-I4"]["state"] == "human"  # 子の氏名（ルールなし）
    assert st["BIRTH-S2-I11"]["state"] == "passed"
    assert st["BIRTH-S2-I5.1"]["state"] == "passed"  # 親のルールの状態を受け継ぐ


def test_finding_state_and_outcome(onto, rules, inputs):
    st = states(onto, rules, inputs, filingDate="2026-11-20")["BIRTH-S2-I11"]
    assert st["state"] == "finding" and st["outcome"] == "additionalProcedure"


@pytest.mark.parametrize("birth,info", [("2024-03-31", False), ("2024-04-01", True)])
def test_legitimacy_color_uses_applicable_rule(onto, rules, inputs, birth, info):
    st = states(
        onto,
        rules,
        inputs,
        childBirthDate=birth,
        certBirthDate=birth,
        filingDate="2024-04-05",
        parentsMarriageDate="2024-01-01",
    )["BIRTH-S2-I5"]
    assert st["state"] == "passed"
    assert ("info" in st["badges"]) == info
    assert ("current" if birth == "2024-04-01" else "manual") in st["badges"]


def test_unevaluated_reason(onto, rules, inputs):
    st = states(onto, rules, inputs, motherBirthDate=UNKNOWN)["BIRTH-S2-I8"]
    assert st["state"] == "unevaluated" and "母の生年月日" in st["reason"]


def test_merge_keeps_case_state_over_reference():
    out = merge_states({"A": {"state": "finding"}}, ["A", "B"])
    assert out["A"]["state"] == "finding" and out["B"]["state"] == "referenced"


def test_step_state_is_worst_item(onto):
    shape = flow_shape(onto, "birth")
    s = step_states(
        shape, {"BIRTH-S2-I5.2": {"state": "unevaluated"}, "BIRTH-S2-I1": {"state": "passed"}}
    )
    assert s["BIRTH-S2"] == "unevaluated" and s["BIRTH-S1"] == "none"


def test_replay_second_judge_replaces_case_states():
    ev = [
        {"flow": {"case_states": {"A": {"state": "finding"}}}},
        {"flow": {"referenced": ["B"]}},
        {"type": "assistant_text"},
        {"flow": {"case_states": {"A": {"state": "passed"}}}},
    ]
    out = replay(ev, {})
    assert out["A"]["state"] == "passed" and out["B"]["state"] == "referenced"


def test_replay_starts_from_initial():
    assert replay([], {"A": {"state": "human"}})["A"]["state"] == "human"


def test_pick_business():
    assert (
        pick_business(["MARRIAGE-S7", "BIRTH-S7", "MARRIAGE-S2-I4", "LAW-MINPO-733"]) == "marriage"
    )
    assert pick_business(["LAW-MINPO-733"]) == "birth"
