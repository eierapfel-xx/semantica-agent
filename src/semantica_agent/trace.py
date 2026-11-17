"""1 ターンのトレースの記録・検証・保存。仕様 §6。

イベントはツールの実装と SDK のフックからコードが積む。LLM の自己申告は記録の元にしない。
"""

import json
import logging
import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
from rdflib import OWL, RDF, Graph, Literal, URIRef
from rdflib.namespace import PROV, XSD
from semantica.context import ContextGraph

from semantica_agent.flow import pick_business, replay
from semantica_agent.ids import iri_from_short_id
from semantica_agent.namespaces import KCASE, bind_prefixes

logger = logging.getLogger(__name__)

TRACE_VERSION = "1"
SCHEMA_PATH = Path(__file__).parent / "schemas" / "trace.schema.json"
EVENT_TYPES = ("user", "assistant_text", "thinking", "tool_call", "tool_result", "answer", "error")
DECISION_JA = {
    "reject": "受理できない",
    "needsCorrection": "補正・追完が要る",
    "needsInquiry": "法務局への受理照会が要る",
    "additionalProcedure": "受理できるが追加の手続が要る",
    "acceptable": "受理可",
    "pending": "判定保留",
}
KIND_JA = {"fact": "事実", "rule": "ルール", "speculation": "推測"}
DECISION_CATEGORY = "出生届の判定"


class TraceError(ValueError):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TraceRecorder:
    session_id: str
    turn: int
    question: str
    model_requested: str
    prompt_path: str
    prompt_hash: str
    ontology_info: dict
    initial_case_states: dict
    events: list[dict] = field(default_factory=list)
    started: str = field(default_factory=_now)

    def add(self, type: str, **fields) -> dict:
        if type not in EVENT_TYPES:
            raise TraceError(f"知らないイベントの種類です: {type}")
        event = {"seq": len(self.events) + 1, "time": _now(), "type": type, **fields}
        self.events.append(event)
        return event

    def finish(
        self,
        answer: dict | None,
        judgment: dict | None,
        case: dict | None,
        model_responded: str | None,
        status: str,
    ) -> dict:
        flow = replay(self.events, self.initial_case_states)
        touched = [n for e in self.events for n in e.get("nodes", [])]
        return {
            "trace_version": TRACE_VERSION,
            "session_id": self.session_id,
            "turn": self.turn,
            "status": status,
            "started": self.started,
            "ended": _now(),
            "model": {"requested": self.model_requested, "responded": model_responded},
            "prompt": {"path": self.prompt_path, "sha256": self.prompt_hash},
            "ontology": self.ontology_info,
            "question": self.question,
            "events": list(self.events),
            "flow_initial": self.initial_case_states,
            "flow": flow,
            "business": "birth" if judgment is not None else pick_business(touched),
            "case": case,
            "judgment": judgment,
            "answer": answer,
        }


def validate_trace(trace: dict) -> None:
    schema = json.loads(SCHEMA_PATH.read_text("utf-8"))
    try:
        jsonschema.validate(trace, schema)
    except jsonschema.ValidationError as e:
        path = "/".join(str(p) for p in e.absolute_path)
        raise TraceError(f"トレースの形が不正です（{path}）: {e.message}") from e


def ontology_info(root: Path) -> dict:
    commit = dirty = None
    try:
        commit = _git(root, "rev-parse", "HEAD")
        dirty = bool(_git(root, "status", "--porcelain", "--", "ontology"))
    except (OSError, subprocess.CalledProcessError) as e:
        logger.warning("オントロジーのコミットを取れません（git）: %s", e)
    version = None
    schema = root / "ontology" / "schema.ttl"
    if schema.exists():
        g = Graph().parse(schema)
        version = next((str(o) for o in g.objects(None, OWL.versionInfo)), None)
    return {"commit": commit, "dirty": dirty, "version_info": version}


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True, timeout=10
    )
    return out.stdout.strip()


def _confidence(j: dict) -> float:
    return 1.0 if not j["has_unconfirmed"] and not j.get("provisional_decision") else 0.5


def _reasoning(j: dict) -> str:
    parts = [f"{f['rule']}（{f['outcome']}）: {f['message']}" for f in j["findings"]]
    parts += [
        f"{u['rule']} は評価できず（未確認: {', '.join(u['missing'])}）" for u in j["unevaluated"]
    ]
    return "；".join(parts) or "指摘なし"


def _birth(case: dict | None) -> str:
    if not case:
        return "不明"
    f = next((f for f in case["fields"] if f["name"] == "childBirthDate"), None)
    return str(f.get("value")) if f and f["status"] == "given" else "不明"


def record_decision(cg: ContextGraph, trace: dict, trace_path: str = "") -> str | None:
    """判定があるときだけ semantica の判断記録に残す。引数はすべてコードが作る。"""
    j = trace["judgment"]
    if j is None:
        return None
    case_iri = trace["case"]["iri"] if trace["case"] else ""
    entities = sorted({x for f in j["findings"] for x in (f["rule"], f["check"]) if x})
    return cg.record_decision(
        category=DECISION_CATEGORY,
        scenario=f"{case_iri}（出生日 {_birth(trace['case'])}）",
        reasoning=_reasoning(j),
        outcome=j["decision"],
        confidence=_confidence(j),
        entities=entities,
        metadata={"trace": trace_path, "session_id": trace["session_id"], "turn": trace["turn"]},
    )


def prov_graph(trace: dict) -> Graph:
    g = bind_prefixes(Graph())
    act = KCASE[f"activity/{trace['session_id']}-{trace['turn']}"]
    g.add((act, RDF.type, PROV.Activity))
    g.add((act, PROV.startedAtTime, Literal(trace["started"], datatype=XSD.dateTime)))
    g.add((act, PROV.endedAtTime, Literal(trace["ended"], datatype=XSD.dateTime)))
    model = trace["model"]["responded"] or trace["model"]["requested"]
    g.add((act, PROV.wasAssociatedWith, Literal(model)))
    if trace["ontology"]["commit"]:
        g.add((act, PROV.used, URIRef(f"urn:git:commit:{trace['ontology']['commit']}")))
    for n in sorted({n for e in trace["events"] for n in e.get("nodes", [])}):
        g.add((act, PROV.used, iri_from_short_id(n)))
    if trace["case"]:
        g.add((act, PROV.used, URIRef(trace["case"]["iri"])))
    if trace["judgment"]:
        result = KCASE[f"judgment/{trace['session_id']}-{trace['turn']}"]
        g.add((result, RDF.type, PROV.Entity))
        g.add((result, PROV.wasGeneratedBy, act))
        g.add((result, PROV.value, Literal(trace["judgment"]["decision"])))
    return g


def save_trace(trace: dict, root: Path, cg: ContextGraph | None = None) -> Path:
    validate_trace(trace)
    folder = root / trace["session_id"]
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{trace['turn']:03d}"
    path = folder / f"{stem}.json"
    path.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    (folder / f"{stem}.md").write_text(render_report(trace), encoding="utf-8")
    prov_graph(trace).serialize(folder / f"{stem}.prov.ttl", format="turtle")
    if cg is not None:
        record_decision(cg, trace, str(path))
        cg.save_to_file(str(folder / "decisions.json"))
    logger.info("トレースを保存しました: %s", path)
    return path


def _report_judgment(j: dict) -> list[str]:
    lines = ["## 判定（コードの結果）", "", f"- 判定：{DECISION_JA[j['decision']]}"]
    if j["unconfirmed"]:
        lines.append("- 未確認の項目：" + "、".join(u["label"] for u in j["unconfirmed"]))
    if j.get("provisional_decision"):
        lines.append(f"- 暫定の判定（未承認の現行版）：{j['provisional_decision']}")
    for f in [*j["findings"], *j.get("info", [])]:
        lines.append(f"- [{f['outcome']}] {f['rule']} → {f['check']}：{f['message']}")
        if f["versions"]:
            lines.append(f"  - 条文の版：{', '.join(f['versions'])}")
    for u in j["unevaluated"]:
        lines.append(f"- 評価できず：{u['rule']} → {u['check']}（{', '.join(u['missing'])}）")
    return [*lines, ""]


def render_report(trace: dict) -> str:
    onto = trace["ontology"]
    lines = [
        f"# 審査のトレース（{trace['session_id']} / {trace['turn']}）",
        "",
        f"- 状態：{trace['status']}　モデル：{trace['model']['responded'] or '-'}",
        f"- オントロジー：{onto['commit'] or '-'}（版 {onto['version_info']}）",
        "",
        "## 質問",
        "",
        trace["question"],
        "",
    ]
    if trace["judgment"]:
        lines += _report_judgment(trace["judgment"])
    if trace["answer"]:
        lines += ["## 回答", "", trace["answer"]["answer"], ""]
        for c in trace["answer"]["claims"]:
            note = f"（下げた理由：{c['downgraded_reason']}）" if c["downgraded_reason"] else ""
            lines.append(f"- [{KIND_JA[c['kind']]}] {c['text']} {', '.join(c['nodes'])}{note}")
        lines.append("")
    lines += ["## 処理の流れ", ""]
    for e in trace["events"]:
        detail = e.get("tool") or (e.get("text") or "")[:60]
        nodes = f" → {', '.join(e['nodes'])}" if e.get("nodes") else ""
        lines.append(f"{e['seq']}. {e['type']} {detail}{nodes}")
    return "\n".join(lines) + "\n"
