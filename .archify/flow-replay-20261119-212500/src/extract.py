"""flow-replay のトレースから、各ノード・矢印を流れたデータを取り出す（LLM なし）。

エージェントの実行は output/traces/flow-replay/001.json。
判定の途中は同じ引数で review/ の関数を順に呼んで取る。
"""

import json
import sys
from datetime import date
from pathlib import Path

from pyshacl import validate
from rdflib import RDF, RDFS, Graph, URIRef
from rdflib.namespace import SH

from semantica_agent.agent.claims import evaluated_rule_nodes
from semantica_agent.agent.tools import Knowledge, judge_birth_case, new_session, to_short
from semantica_agent.core.ids import derived_iri, short_id
from semantica_agent.core.namespaces import KCASE, KOS, bind_prefixes
from semantica_agent.review.assess import assess
from semantica_agent.review.case_input import case_graph, check_quotes, parse_case_input
from semantica_agent.review.derive import DERIVED_VALUES, PERIOD_SLUG, derive, read_period_rule
from semantica_agent.review.judge import _rule_of_shape

ROOT = Path(".")
TRACE = ROOT / "output/traces/flow-replay/001.json"
OUT = Path(sys.argv[1])

k = Knowledge.load(ROOT)
onto, R = k.ontology, k.rules
trace = json.loads(TRACE.read_text("utf-8"))
ev = trace["events"]
question = trace["question"]
judge_call = next(e for e in ev if e["type"] == "tool_call" and e["tool"] == "judge_birth_case")
judge_res = next(e for e in ev if e["type"] == "tool_result" and e["tool"] == "judge_birth_case")
submit_call = next(e for e in ev if e["type"] == "tool_call" and e["tool"] == "submit_answer")
submit_res = next(e for e in ev if e["type"] == "tool_result" and e["tool"] == "submit_answer")
args = judge_call["args"]


def label(n) -> str:
    return str(onto.value(n, RDFS.label) or R.value(n, RDFS.label) or "")


def ref(n) -> dict:
    return {"id": to_short(n) or str(n), "label": label(n)}


def ttl(g: Graph, subjects) -> str:
    out = bind_prefixes(Graph())
    todo, seen = list(subjects), set()
    while todo:
        s = todo.pop()
        if s in seen:
            continue
        seen.add(s)
        for p, o in g.predicate_objects(s):
            out.add((s, p, o))
            if not isinstance(o, URIRef) and o.__class__.__name__ == "BNode":
                todo.append(o)
    text = out.serialize(format="turtle")
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("@prefix")).strip()


# 1. 入力の検証と引用の照合（judge_birth_case の入口）
case = parse_case_input(args, onto)
bad = check_quotes(case, [question])
fields = [
    {
        "name": f.name,
        "status": f.status,
        "value": str(f.value) if f.value is not None else None,
        "quote": f.quote,
        "inferred": f.inferred,
        "note": f.note,
    }
    for f in case.fields
]

# 2. 事案グラフ（judge_birth_case と同じ IRI）
case_iri = KCASE["flow-replay-1-1"]
cg = case_graph(case, case_iri)
case_ttl = cg.serialize(format="turtle")

# 3. 派生値（届出期間の定義をオントロジーから読む）
period_node = derived_iri(PERIOD_SLUG)
period = read_period_rule(onto)
derived = derive(cg, case_iri, onto)
derived_vals = []
for d in DERIVED_VALUES:
    v = derived.value(case_iri, KOS[d.output])
    node = derived_iri(d.slug)
    derived_vals.append(
        {
            "name": d.output,
            "label": d.label_ja,
            "value": str(v) if v is not None else None,
            "inputs": list(d.inputs),
            "definition": short_id(node),
            "provisions": [ref(p) for p in onto.objects(node, KOS.citesProvision)],
        }
    )

# 4. SHACL の検証（judge と同じデータ）
data = bind_prefixes(Graph())
for g in (derived, onto, R):
    for t in g:
        data.add(t)
_, report, _ = validate(data, shacl_graph=R, advanced=True, allow_warnings=True)
violations = []
for r in report.subjects(RDF.type, SH.ValidationResult):
    if report.value(r, SH.focusNode) != case_iri:
        continue
    shape = report.value(r, SH.sourceShape)
    rule, top = _rule_of_shape(R, shape)
    val = report.value(r, SH.value)
    violations.append(
        {
            "shape": to_short(top) or str(top),
            "severity": str(report.value(r, SH.resultSeverity)).split("#")[-1],
            "path": (
                str(report.value(r, SH.resultPath)).split("#")[-1]
                if report.value(r, SH.resultPath)
                else None
            ),
            "value": (to_short(val) or str(val)) if val is not None else None,
            "message": str(report.value(r, SH.resultMessage) or ""),
            "rule": ref(rule),
            "outcome": str(R.value(rule, KOS.outcome)).split("#")[-1],
            "check": ref(R.value(rule, KOS.implementsCheck)),
            "versions": [
                ref(v)
                | {
                    "validFrom": str(onto.value(v, KOS.validFrom) or ""),
                    "status": str(onto.value(v, KOS.versionStatus) or "").split("#")[-1],
                }
                for v in R.objects(rule, KOS.underVersion)
            ],
        }
    )
violations.sort(key=lambda v: (v["rule"]["id"], v["value"] or ""))

# 5. 後処理（版の選択・評価できず・全体の判定）
a = assess(case, case_iri, onto, R, k.inputs)
birth = date.fromisoformat(args["childBirthDate"]["value"])
all_rules = sorted(R.subjects(RDF.type, KOS.JudgmentRule))
rules_table = []
for rule in all_rules:
    vs = list(R.objects(rule, KOS.underVersion))
    fired = [v for v in violations if v["rule"]["id"] == to_short(rule)]
    if rule not in a.applicable:
        state = "notApplicable"
    elif rule in a.unevaluated:
        state = "unevaluated"
    elif fired:
        state = "finding"
    else:
        state = "passed"
    rules_table.append(
        {
            **ref(rule),
            "outcome": str(R.value(rule, KOS.outcome)).split("#")[-1],
            "check": ref(R.value(rule, KOS.implementsCheck)),
            "versions": [
                ref(v)
                | {
                    "validFrom": str(onto.value(v, KOS.validFrom) or "") or None,
                    "validUntil": str(onto.value(v, KOS.validUntil) or "") or None,
                    "status": str(onto.value(v, KOS.versionStatus) or "").split("#")[-1],
                }
                for v in vs
            ],
            "inputs": sorted(k.inputs.get(rule, ())),
            "missing": list(a.unevaluated.get(rule, ())),
            "state": state,
        }
    )

# 6. 回答の検証に使った集合（judge を同じセッションで再現して求める）
s = new_session("flow-replay")
s.turn = 1
s.utterances.append(question)
judge_birth_case(k, s, args)
s.referenced_this_turn = set(judge_res["nodes"])
rule_nodes = sorted(evaluated_rule_nodes(k, s))

# オントロジー側の抜粋（矢印に載せる）
fired_shapes = {v["shape"] for v in violations}
fired_rules = [r for r in all_rules if to_short(r) in {v["rule"]["id"] for v in violations}]
shape_nodes = [R.value(r, KOS.shape) for r in fired_rules]
check_nodes = {URIRef(str(n)) for n in ()}
excerpts = {
    "period": ttl(onto, [period_node]),
    "shapes": ttl(R, shape_nodes),
    "rules": ttl(R, [r for r in all_rules if to_short(r) in {v["rule"]["id"] for v in violations}]),
    "versions": ttl(onto, [URIRef(str(KCASE)) for _ in ()]),
}
law772 = [v for v in onto.subjects(RDF.type, KOS.ProvisionVersion) if "minpo/art/772/" in str(v)]
excerpts["versions"] = ttl(onto, law772)
checks = sorted({v["check"]["id"] for v in violations})

out = {
    "question": question,
    "trace_path": str(TRACE),
    "model": trace["model"],
    "ontology": trace["ontology"],
    "started": trace["started"],
    "ended": trace["ended"],
    "events": ev,
    "judge_args": args,
    "case_fields": fields,
    "quote_errors": bad,
    "case_iri": str(case_iri),
    "case_ttl": case_ttl,
    "period": {
        "node": short_id(period_node),
        "periodDays": period.days if hasattr(period, "days") else None,
        "raw": str(period),
    },
    "derived": derived_vals,
    "violations": violations,
    "rules": rules_table,
    "birth": str(birth),
    "assess": {
        "decision": a.decision,
        "unconfirmed": list(a.unconfirmed),
        "provisional_decision": a.provisional_decision,
    },
    "judge_payload": judge_res["result"],
    "judge_nodes": judge_res["nodes"],
    "case_states": judge_res["flow"]["case_states"],
    "submit_args": submit_call["args"],
    "submit_result": submit_res["result"],
    "evaluated_rule_nodes": rule_nodes,
    "referenced_this_turn": sorted(s.referenced_this_turn),
    "excerpts": excerpts,
    "saved": {
        "files": ["001.json", "001.md", "001.prov.ttl", "decisions.json"],
        "prov": (TRACE.parent / "001.prov.ttl").read_text("utf-8"),
        "report_md": (TRACE.parent / "001.md").read_text("utf-8"),
    },
}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
print(
    "ok", len(violations), "violations;", sum(r["state"] == "passed" for r in rules_table), "passed"
)
for r in rules_table:
    print(r["id"], r["state"], r["outcome"], [v["id"] for v in r["versions"]], r["missing"])
for d in derived_vals:
    print(d["name"], d["value"])
print(out["period"])
