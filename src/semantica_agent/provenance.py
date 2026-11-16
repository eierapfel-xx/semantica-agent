"""生成の記録（PROV-O）。仕様 §5.7。"""

import hashlib
from datetime import datetime
from pathlib import Path

from rdflib import RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, XSD

from semantica_agent.ids import activity_iri
from semantica_agent.namespaces import KD, KOS, bind_prefixes


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _artifact(g: Graph, path: Path) -> URIRef:
    sha = file_sha256(path)
    node = KD[f"artifact/{sha}"]
    g.add((node, RDF.type, PROV.Entity))
    g.add((node, RDFS.label, Literal(path.as_posix())))
    g.add((node, KOS.sha256, Literal(sha)))
    return node


def record_activity(
    g: Graph,
    *,
    run_id: str,
    stage: str,
    started: datetime,
    ended: datetime,
    inputs: list[Path],
    pdf_pages: list[int],
    prompt_path: Path | None,
    model: str | None,
    outputs: list[Path],
) -> tuple[Graph, URIRef]:
    new = bind_prefixes(Graph())
    for t in g:
        new.add(t)
    act = activity_iri(run_id)
    new.add((act, RDF.type, PROV.Activity))
    new.add((act, DCTERMS.identifier, Literal(run_id)))
    new.add((act, RDFS.label, Literal(stage)))
    new.add((act, PROV.startedAtTime, Literal(started.isoformat(), datatype=XSD.dateTime)))
    new.add((act, PROV.endedAtTime, Literal(ended.isoformat(), datatype=XSD.dateTime)))
    for p in [*inputs, *([prompt_path] if prompt_path else [])]:
        new.add((act, PROV.used, _artifact(new, p)))
    if prompt_path:
        new.add((act, KOS.promptSha256, Literal(file_sha256(prompt_path))))
    for page in pdf_pages:
        new.add((act, KOS.pdfPage, Literal(page)))
    if model:
        new.add((act, KOS.model, Literal(model)))
    for p in outputs:
        new.add((_artifact(new, p), PROV.wasGeneratedBy, act))
    return new, act
