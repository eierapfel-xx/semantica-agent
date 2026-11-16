from rdflib import Graph, Literal

from semantica_agent.namespaces import KD, KOS
from semantica_agent.turtle_io import load_ontology, write_turtle

TRIPLES = [
    (KD["birth/step/2"], KOS.stepNumber, Literal(2)),
    (KD["birth"], KOS.hasStep, KD["birth/step/2"]),
    (KD["birth"], KOS.hasStep, KD["birth/step/1"]),
    (KD["birth/step/1"], KOS.stepNumber, Literal(1)),
]


def _graph(triples):
    g = Graph()
    for t in triples:
        g.add(t)
    return g


def test_write_turtle_is_deterministic(tmp_path):
    write_turtle(_graph(TRIPLES), tmp_path / "a.ttl")
    write_turtle(_graph(list(reversed(TRIPLES))), tmp_path / "b.ttl")
    assert (tmp_path / "a.ttl").read_bytes() == (tmp_path / "b.ttl").read_bytes()


def test_write_turtle_uses_prefixes(tmp_path):
    write_turtle(_graph(TRIPLES), tmp_path / "a.ttl")
    text = (tmp_path / "a.ttl").read_text(encoding="utf-8")
    assert "@prefix kos:" in text and "kd:birth" in text


def test_load_ontology_skips_generated_and_cq(tmp_path):
    (tmp_path / "instances").mkdir()
    (tmp_path / "generated").mkdir()
    write_turtle(_graph(TRIPLES[:1]), tmp_path / "instances" / "birth.ttl")
    write_turtle(_graph(TRIPLES[1:2]), tmp_path / "generated" / "raw.ttl")
    g = load_ontology(tmp_path)
    assert len(g) == 1


def test_load_ontology_reports_broken_file(tmp_path):
    (tmp_path / "bad.ttl").write_text("not turtle at all", encoding="utf-8")
    import pytest

    with pytest.raises(ValueError, match="bad.ttl"):
        load_ontology(tmp_path)
