"""Turtle の書き出し（差分を読みやすくするため並びを固定）と読み込み。"""

import logging
from pathlib import Path

from pyshacl import validate as shacl_validate
from rdflib import Graph

from semantica_agent.core.namespaces import bind_prefixes

logger = logging.getLogger(__name__)

EXCLUDED_DIRS = ("generated", "cq")


def write_turtle(g: Graph, path: Path) -> None:
    out = bind_prefixes(Graph())
    for t in sorted(g):
        out.add(t)
    path.parent.mkdir(parents=True, exist_ok=True)
    # rdflib の turtle 書き出しは主語・述語・目的語を並べ替えて出す
    path.write_text(out.serialize(format="turtle"), encoding="utf-8")
    logger.debug("Turtle を書き出しました: %s（%d トリプル）", path, len(out))


def load_ontology(root: Path) -> Graph:
    g = bind_prefixes(Graph())
    for p in sorted(root.rglob("*.ttl")):
        rel = p.relative_to(root)
        if rel.parts and rel.parts[0] in EXCLUDED_DIRS:
            continue
        try:
            g.parse(p, format="turtle")
        except Exception as e:
            raise ValueError(f"Turtle を読めません: {p}: {e}") from e
    return g


INTEGRITY_SHAPES = Path("shapes/integrity.ttl")


def validate_integrity(onto_dir: Path) -> tuple[bool, str]:
    """オントロジーを整合性シェイプで検証する（適合したか、結果の文）。"""
    shapes = onto_dir / INTEGRITY_SHAPES
    if not shapes.exists():
        raise FileNotFoundError(f"整合性シェイプがありません: {shapes}")
    conforms, _, text = shacl_validate(
        load_ontology(onto_dir), shacl_graph=Graph().parse(shapes), advanced=True
    )
    return bool(conforms), str(text)
