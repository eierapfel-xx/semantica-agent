import pytest
from case_helpers import UNKNOWN, full_args

from semantica_agent.claims import verify_claims
from semantica_agent.tools import ToolError, judge_birth_case, new_session, submit_answer


def judged(knowledge, **changes):
    s = new_session("t")
    s.utterances.append("q")
    judge_birth_case(knowledge, s, full_args(**changes))
    return s


def test_rule_claim_with_finding_is_kept(knowledge):
    s = judged(knowledge, filingDate="2026-11-20")
    (c,) = verify_claims(
        [{"text": "期間を過ぎた", "kind": "rule", "nodes": ["RULE-BIRTH-FILING-PERIOD"]}],
        knowledge,
        s,
    )
    assert c.kind == "rule" and c.downgraded_reason is None


def test_rule_claim_without_finding_is_downgraded(knowledge):
    s = judged(knowledge, filingDate="2026-11-20", addressExists=UNKNOWN)
    (c,) = verify_claims(
        [{"text": "住所が無い", "kind": "rule", "nodes": ["RULE-BIRTH-ADDRESS"]}], knowledge, s
    )
    assert c.kind == "speculation" and c.downgraded_reason


def test_rule_claim_on_passed_check_is_kept(knowledge):
    s = judged(knowledge)
    (c,) = verify_claims(
        [{"text": "期間内", "kind": "rule", "nodes": ["BIRTH-S2-I11"]}], knowledge, s
    )
    assert c.kind == "rule"


def test_rule_claim_without_judge_is_downgraded(knowledge):
    s = new_session("t")
    (c,) = verify_claims([{"text": "x", "kind": "rule", "nodes": ["BIRTH-S2-I11"]}], knowledge, s)
    assert c.kind == "speculation"


def test_fact_claim_needs_referenced_node(knowledge):
    s = new_session("t")
    s.referenced_this_turn = {"BIRTH-S2-I11"}
    ok, bad = verify_claims(
        [
            {"text": "a", "kind": "fact", "nodes": ["BIRTH-S2-I11"]},
            {"text": "b", "kind": "fact", "nodes": ["BIRTH-S2-I1"]},
        ],
        knowledge,
        s,
    )
    assert ok.kind == "fact" and bad.kind == "speculation"


def test_unknown_node_id_is_dropped(knowledge):
    s = new_session("t")
    s.referenced_this_turn = {"BIRTH-S2-I11"}
    (c,) = verify_claims(
        [{"text": "a", "kind": "fact", "nodes": ["BIRTH-S2-I11", "NOPE-9"]}], knowledge, s
    )
    assert c.nodes == ("BIRTH-S2-I11",)


def test_speculation_stays(knowledge):
    (c,) = verify_claims(
        [{"text": "a", "kind": "speculation", "nodes": []}], knowledge, new_session("t")
    )
    assert c.kind == "speculation" and c.downgraded_reason is None


def test_submit_answer_payload(knowledge):
    s = new_session("t")
    r = submit_answer(
        knowledge, s, {"answer": "本文", "claims": [{"text": "a", "kind": "fact", "nodes": []}]}
    )
    assert r.payload["answer"] == "本文" and r.payload["claims"][0]["kind"] == "speculation"


@pytest.mark.parametrize(
    "args", [{}, {"answer": "", "claims": []}, {"answer": "x", "claims": [{"kind": "x"}]}]
)
def test_submit_answer_rejects_bad_args(knowledge, args):
    with pytest.raises(ToolError):
        submit_answer(knowledge, new_session("t"), args)
