from datetime import UTC, datetime

from rdflib import RDF, Graph, Literal
from rdflib.namespace import PROV

from semantica_agent.build.provenance import file_sha256, record_activity
from semantica_agent.core.namespaces import KD, KOS


def _record(tmp_path, g=None):
    inp = tmp_path / "rows.json"
    inp.write_text("[]", encoding="utf-8")
    prompt = tmp_path / "schema.md"
    prompt.write_text("prompt", encoding="utf-8")
    out = tmp_path / "schema.ttl"
    out.write_text("", encoding="utf-8")
    return record_activity(
        g if g is not None else Graph(),
        run_id="schema-20261116120000",
        stage="schema",
        started=datetime(2026, 11, 16, 12, 0, tzinfo=UTC),
        ended=datetime(2026, 11, 16, 12, 1, tzinfo=UTC),
        inputs=[inp],
        pdf_pages=[2, 3],
        prompt_path=prompt,
        model="claude-x",
        outputs=[out],
    )


def test_file_sha256(tmp_path):
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    assert file_sha256(p) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_record_activity_links_inputs_and_model(tmp_path):
    g, act = _record(tmp_path)
    assert act == KD["activity/schema-20261116120000"]
    assert (act, RDF.type, PROV.Activity) in g
    assert (act, KOS.model, Literal("claude-x")) in g
    assert {int(p) for p in g.objects(act, KOS.pdfPage)} == {2, 3}
    assert g.value(act, KOS.promptSha256) == Literal(file_sha256(tmp_path / "schema.md"))
    assert len(list(g.objects(act, PROV.used))) == 2
    assert len(list(g.subjects(PROV.wasGeneratedBy, act))) == 1


def test_record_activity_does_not_mutate_input(tmp_path):
    base = Graph()
    _record(tmp_path, base)
    assert len(base) == 0
