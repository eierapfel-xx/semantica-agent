import json
from pathlib import Path

import pytest
from rdflib import Graph
from semantica.context import ContextGraph

from semantica_agent.agent.trace import (
    TraceError,
    TraceRecorder,
    ontology_info,
    record_decision,
    render_report,
    save_trace,
    validate_trace,
)
from semantica_agent.review.flow import replay

ROOT = Path(__file__).resolve().parents[1]
JUDGMENT = {
    "decision": "pending",
    "has_unconfirmed": True,
    "unconfirmed": [{"name": "motherBirthDate", "label": "母の生年月日"}],
    "unevaluated": [
        {"rule": "RULE-BIRTH-MOTHER-AGE", "check": "BIRTH-S2-I8", "missing": ["motherBirthDate"]}
    ],
    "provisional_decision": None,
    "findings": [],
    "info": [],
}
CASE = {
    "iri": "https://semantica-agent.example/koseki/case/s-1-1",
    "turtle": "",
    "fields": [
        {"name": "childBirthDate", "label": "子の出生日", "status": "given", "value": "2024-04-01"}
    ],
}


def recorder(**kw):
    defaults = dict(
        session_id="s",
        turn=1,
        question="4月1日生まれ",
        model_requested="claude-sonnet-5-5",
        prompt_path="src/semantica_agent/prompts/agent.md",
        prompt_hash="abc",
        ontology_info={"commit": "c", "dirty": False, "version_info": "1.0"},
        initial_case_states={},
    )
    return TraceRecorder(**(defaults | kw))


def two_judges():
    r = recorder()
    r.add("user", text="4月1日生まれ")
    r.add("tool_call", tool="judge_birth_case", args={})
    r.add(
        "tool_result",
        tool="judge_birth_case",
        result={},
        nodes=["BIRTH-S2-I8"],
        flow={"case_states": {"BIRTH-S2-I8": {"state": "unevaluated", "badges": []}}},
    )
    r.add(
        "tool_result",
        tool="describe_node",
        result={},
        nodes=["BIRTH-S2-I11"],
        flow={"referenced": ["BIRTH-S2-I11"]},
    )
    r.add(
        "tool_result",
        tool="judge_birth_case",
        result={},
        nodes=[],
        flow={"case_states": {"BIRTH-S2-I8": {"state": "passed", "badges": []}}},
    )
    return r


def finished(r=None, **kw):
    r = r or two_judges()
    args = dict(
        answer={"answer": "保留です", "claims": [], "submitted": True},
        judgment=JUDGMENT,
        case=CASE,
        model_responded="claude-sonnet-5-5",
        status="ok",
    )
    return r.finish(**(args | kw))


def test_event_seq_and_time():
    r = recorder()
    e1, e2 = r.add("user", text="a"), r.add("assistant_text", text="b")
    assert (e1["seq"], e2["seq"]) == (1, 2) and e1["time"]


def test_unknown_event_type_rejected():
    with pytest.raises(TraceError):
        recorder().add("bogus")


def test_finished_trace_is_valid(tmp_path):
    t = finished()
    validate_trace(t)
    cg = ContextGraph()
    p = save_trace(t, tmp_path, cg)
    assert p == tmp_path / "s" / "001.json"
    assert (tmp_path / "s" / "001.md").exists() and (tmp_path / "s" / "decisions.json").exists()
    g = Graph().parse(tmp_path / "s" / "001.prov.ttl")
    assert len(g) > 0
    assert json.loads(p.read_text("utf-8"))["judgment"]["decision"] == "pending"


def test_replay_matches_saved_flow():
    t = finished()
    assert replay(t["events"], t["flow_initial"]) == t["flow"]
    assert t["flow"]["BIRTH-S2-I8"]["state"] == "passed"
    assert t["flow"]["BIRTH-S2-I11"]["state"] == "referenced"
    assert t["business"] == "birth"


def test_business_from_references_without_judge():
    r = recorder()
    r.add(
        "tool_result",
        tool="run_cq",
        result={},
        nodes=["MARRIAGE-S8"],
        flow={"referenced": ["MARRIAGE-S8"]},
    )
    t = finished(r, judgment=None, case=None)
    assert t["business"] == "marriage"


def test_invalid_trace_is_rejected():
    with pytest.raises(TraceError):
        validate_trace({"trace_version": "1"})


def test_record_decision_confidence():
    cg = ContextGraph()
    did = record_decision(cg, finished())
    data = cg.to_dict()
    node = next(n for n in data["nodes"] if n["id"] == did)
    assert node["properties"]["confidence"] == 0.5 and node["properties"]["outcome"] == "pending"


def test_record_decision_full_confidence():
    cg = ContextGraph()
    j = JUDGMENT | {
        "has_unconfirmed": False,
        "decision": "acceptable",
        "unconfirmed": [],
        "unevaluated": [],
    }
    did = record_decision(cg, finished(judgment=j))
    node = next(n for n in cg.to_dict()["nodes"] if n["id"] == did)
    assert node["properties"]["confidence"] == 1.0


def test_record_decision_skipped_without_judgment():
    assert record_decision(ContextGraph(), finished(judgment=None, case=None)) is None


def test_report_mentions_decision_and_unconfirmed():
    text = render_report(finished())
    assert "判定保留" in text and "母の生年月日" in text and "4月1日生まれ" in text


def test_ontology_info_reads_version():
    info = ontology_info(ROOT)
    assert info["version_info"] == "1.0" and isinstance(info["commit"], str)


def test_ontology_info_without_git(tmp_path):
    (tmp_path / "ontology").mkdir()
    (tmp_path / "ontology/schema.ttl").write_text("", "utf-8")
    info = ontology_info(tmp_path)
    assert info["commit"] is None and info["dirty"] is None


def test_no_secret_in_trace(monkeypatch):
    monkeypatch.setenv("SOME_TOKEN", "secret-xyz")
    assert "secret-xyz" not in json.dumps(finished(), ensure_ascii=False)


def test_prov_uses_node_iris(tmp_path):
    save_trace(finished(), tmp_path)
    text = (tmp_path / "s" / "001.prov.ttl").read_text("utf-8")
    assert "koseki/id/birth/step/2/item/8" in text and "urn:git:commit:c" in text


def test_trace_without_runtime_is_still_valid():
    t = json.loads((ROOT / "tests/fixtures/traces/demo-001.json").read_text("utf-8"))
    assert "runtime" not in t
    validate_trace(t)


def test_runtime_is_carried_and_on_add_called():
    seen = []
    r = recorder()
    r.runtime = {"kind": "claude-code", "cli_version": "2.1.325"}
    r.on_add = seen.append
    e = r.add("user", text="a")
    assert seen == [e]
    t = finished(r)
    assert t["runtime"] == {"kind": "claude-code", "cli_version": "2.1.325"}
    validate_trace(t)


def test_bad_runtime_kind_is_rejected():
    t = finished()
    t["runtime"] = {"kind": "other", "cli_version": None}
    with pytest.raises(TraceError):
        validate_trace(t)
