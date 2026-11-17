"""エージェントに渡すツールの本体。仕様 §5。

どのツールも、LLM に返す payload と一緒に、触れたノード（短い ID）とフローへの反映を返す。
記録はこの戻り値から呼び出し側（agent.py）が行い、LLM の自己申告に頼らない。
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import anyio
from pyparsing import ParseException
from rdflib import RDF, RDFS, Graph, Literal, URIRef
from rdflib.plugins.sparql import prepareQuery

from semantica_agent.flow import BUSINESSES
from semantica_agent.ids import iri_from_short_id, short_id
from semantica_agent.namespaces import KD, KOS
from semantica_agent.rule_inputs import rule_inputs
from semantica_agent.turtle_io import load_ontology

logger = logging.getLogger(__name__)

SEARCH_LIMIT = 20
SPARQL_ROW_LIMIT = 200
RULES_FILE = Path("ontology/rules/birth-rules.ttl")
CQ_DIR = Path("ontology/cq")
_SERVICE = re.compile(r"\bSERVICE\b", re.IGNORECASE)
PARENT_PROPS = (KOS.hasStep, KOS.hasItem, KOS.hasSubItem)
SOURCE_PROPS = (
    "sourceKind", "businessName", "division", "pdfPage", "printedPage", "rowId", "quote",
    "url", "revisionId", "fetchedDate", "reviewer", "reviewedDate",
)  # fmt: skip


class ToolError(RuntimeError):
    """ツールの入力や実行の誤り。LLM に返して直させる。"""


@dataclass
class ToolResult:
    payload: dict
    nodes: list[str]
    flow: dict


@dataclass
class Knowledge:
    ontology: Graph
    rules: Graph
    inputs: dict[URIRef, frozenset[str]]
    cq_dir: Path
    cq_titles: dict[int, str] = field(default_factory=dict)

    @classmethod
    def load(cls, root: Path) -> "Knowledge":
        onto_dir, rules_path, cq_dir = root / "ontology", root / RULES_FILE, root / CQ_DIR
        for p in (onto_dir, rules_path, cq_dir):
            if not p.exists():
                raise FileNotFoundError(f"オントロジーのファイルがありません: {p}")
        rules = Graph().parse(rules_path)
        titles = {
            int(p.stem.removeprefix("cq")): p.read_text("utf-8").splitlines()[0].lstrip("# ")
            for p in sorted(cq_dir.glob("cq*.rq"))
        }
        return cls(load_ontology(onto_dir), rules, rule_inputs(rules), cq_dir, titles)


def to_short(node) -> str | None:
    if not isinstance(node, URIRef) or not str(node).startswith(str(KD)):
        return None
    try:
        return short_id(node)
    except ValueError:
        return None


def _label(g: Graph, node) -> str:
    return str(g.value(node, RDFS.label) or "")


def _ref(g: Graph, node) -> dict | str:
    sid = to_short(node)
    if sid:
        return {"id": sid, "label": _label(g, node)}
    if isinstance(node, URIRef) and "#" in str(node):
        return str(node).split("#")[-1]
    return str(node)


def _referenced(payload: dict, nodes: list[str]) -> ToolResult:
    return ToolResult(payload, nodes, {"referenced": nodes})


def search_nodes(
    k: Knowledge, text: str, business: str | None = None, cls: str | None = None
) -> ToolResult:
    if business is not None and business not in BUSINESSES:
        raise ToolError(f"業務は {', '.join(BUSINESSES)} のいずれかです: {business}")
    hits = []
    for s, label in k.ontology.subject_objects(RDFS.label):
        sid = to_short(s)
        if not sid or text not in str(label):
            continue
        if business and not sid.startswith(business.upper() + "-"):
            continue
        classes = sorted(str(t).split("#")[-1] for t in k.ontology.objects(s, RDF.type))
        if cls and cls not in classes:
            continue
        hits.append({"id": sid, "label": str(label), "classes": classes})
    hits = sorted(hits, key=lambda h: h["id"])[:SEARCH_LIMIT]
    return _referenced({"hits": hits}, [h["id"] for h in hits])


def _node(k: Knowledge, node_id: str) -> URIRef:
    try:
        node = iri_from_short_id(node_id)
    except (ValueError, KeyError, IndexError) as e:
        raise ToolError(f"短い ID として読めません: {node_id}") from e
    if (node, None, None) not in k.ontology:
        raise ToolError(f"オントロジーにノードがありません: {node_id}")
    return node


def _version(g: Graph, v) -> dict:
    return {
        "id": to_short(v),
        "status": _ref(g, g.value(v, KOS.versionStatus)),
        "validFrom": str(g.value(v, KOS.validFrom) or "") or None,
        "validUntil": str(g.value(v, KOS.validUntil) or "") or None,
        "summary": str(g.value(v, KOS.summary) or "") or None,
        "reviewStatus": _ref(g, g.value(v, KOS.reviewStatus)),
        "sources": [_source(g, s) for s in sorted(g.objects(v, KOS.hasSource))],
    }


def _source(g: Graph, s) -> dict:
    out: dict = {"id": to_short(s)}
    if (comment := g.value(s, RDFS.comment)) is not None:
        out["comment"] = str(comment)
    for p in SOURCE_PROPS:
        v = g.value(s, KOS[p])
        if v is not None:
            out[p] = _ref(g, v) if not isinstance(v, Literal) else str(v)
    return out


def describe_node(k: Knowledge, node_id: str) -> ToolResult:
    g, node = k.ontology, _node(k, node_id)
    props: dict[str, list] = {}
    for p, o in sorted(g.predicate_objects(node)):
        if p in (RDFS.label, KOS.hasSource):
            continue
        props.setdefault(str(p).split("#")[-1].split("/")[-1], []).append(_ref(g, o))
    payload = {
        "id": node_id,
        "label": _label(g, node),
        "classes": sorted(str(t).split("#")[-1] for t in g.objects(node, RDF.type)),
        "parents": [_ref(g, s) for p in PARENT_PROPS for s in g.subjects(p, node)],
        "properties": props,
        "provisions": [
            {**_ref(g, p), "versions": [_version(g, v) for v in g.objects(p, KOS.hasVersion)]}
            for p in sorted(g.objects(node, KOS.citesProvision))
        ],
        "rules": [_ref(g, r) for r in sorted(g.subjects(KOS.implementsCheck, node))],
        "sources": [_source(g, s) for s in sorted(g.objects(node, KOS.hasSource))],
    }
    return _referenced(payload, [node_id])


def _rows(g: Graph, result) -> tuple[list[dict], list[str], bool]:
    rows, nodes = [], []
    for i, row in enumerate(result):
        if i >= SPARQL_ROW_LIMIT:
            return rows, nodes, True
        out = {}
        for var, val in row.asdict().items():
            sid = to_short(val)
            out[var] = sid or str(val)
            if sid and sid not in nodes:
                nodes.append(sid)
        rows.append(out)
    return rows, nodes, False


def run_cq(k: Knowledge, number: int) -> ToolResult:
    path = k.cq_dir / f"cq{number:02d}.rq"
    if number not in k.cq_titles or not path.exists():
        raise ToolError(f"CQ の番号は {min(k.cq_titles)}〜{max(k.cq_titles)} です: {number}")
    rows, nodes, truncated = _rows(k.ontology, k.ontology.query(path.read_text("utf-8")))
    payload = {"cq": number, "question": k.cq_titles[number], "rows": rows, "truncated": truncated}
    return _referenced(payload, nodes)


def _check_select(query: str) -> None:
    if _SERVICE.search(query):
        raise ToolError("SERVICE を含む問い合わせは使えません")
    try:
        parsed = prepareQuery(query)
    except (ParseException, Exception) as e:  # rdflib は構文の誤りで種々の例外を出す
        raise ToolError(f"SPARQL として読めません: {e}") from e
    if parsed.algebra.name != "SelectQuery":
        raise ToolError("SELECT の問い合わせだけが使えます")


async def run_sparql(k: Knowledge, query: str, timeout_s: float) -> ToolResult:
    _check_select(query)

    def _run():
        return _rows(k.ontology, k.ontology.query(query))

    try:
        with anyio.fail_after(timeout_s):
            rows, nodes, truncated = await anyio.to_thread.run_sync(_run, abandon_on_cancel=True)
    except TimeoutError as e:
        logger.warning("SPARQL が時間の上限（%s 秒）を超えました", timeout_s)
        raise ToolError(
            f"時間の上限（{timeout_s} 秒）を超えました。問い合わせを絞ってください"
        ) from e
    return _referenced({"rows": rows, "truncated": truncated}, nodes)
