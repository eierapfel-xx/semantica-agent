"""オントロジーの名前空間。URI はここだけで定義する。"""

from rdflib import Graph, Namespace
from rdflib.namespace import DCTERMS, OWL, PROV, RDFS, SH, XSD

KOS = Namespace("https://semantica-agent.example/koseki/schema#")
KD = Namespace("https://semantica-agent.example/koseki/id/")
KCASE = Namespace("https://semantica-agent.example/koseki/case/")

PREFIXES: dict[str, str] = {
    "kos": str(KOS),
    "kd": str(KD),
    "kcase": str(KCASE),
    "prov": str(PROV),
    "sh": str(SH),
    "dcterms": str(DCTERMS),
    "rdfs": str(RDFS),
    "owl": str(OWL),
    "xsd": str(XSD),
}


def bind_prefixes(g: Graph) -> Graph:
    for prefix, uri in PREFIXES.items():
        g.bind(prefix, uri, override=True)
    return g
