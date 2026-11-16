import pytest
from rdflib import RDF, Graph
from rdflib.namespace import PROV
from semantica.semantic_extract.registry import provider_registry

from semantica_agent.build import main
from semantica_agent.extract import Row, save_rows
from semantica_agent.namespaces import KOS
from semantica_agent.turtle_io import write_turtle
from semantica_agent.vocab import REQUIRED_CLASSES, REQUIRED_PROPERTIES


class FakeSchemaProvider:
    def __init__(self, **kwargs):
        self.last_model = "fake-model"

    def generate_structured(self, prompt, **kwargs):
        return {
            "classes": [{"name": n, "label_ja": j} for n, j in REQUIRED_CLASSES.items()],
            "properties": [
                {"name": n, "label_ja": j, "type": "data"} for n, j in REQUIRED_PROPERTIES.items()
            ],
        }

    def generate(self, prompt, **kwargs):
        return (
            "```turtle\n@prefix sh: <http://www.w3.org/ns/shacl#> .\n<urn:s> a sh:NodeShape .\n```"
        )


@pytest.fixture
def fake_provider():
    provider_registry.register("fake_build", FakeSchemaProvider)
    yield "fake_build"
    provider_registry.unregister("fake_build")


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    rows = [Row("p2-r1", "table", "birth", "1.受付", "受付する", "", 2, 1, 1.0)]
    save_rows(rows, tmp_path / "data" / "extracted" / "rows.json")
    (tmp_path / "ontology").mkdir()
    return tmp_path


def test_instances_requires_fixed_schema(tmp_project, fake_provider):
    args = [
        "instances",
        "--business",
        "birth",
        "--root",
        str(tmp_project),
        "--provider",
        fake_provider,
    ]
    assert main(args) == 1


def test_schema_stage_writes_generated_and_provenance(tmp_project, fake_provider, capsys):
    assert main(["schema", "--root", str(tmp_project), "--provider", fake_provider]) == 0
    out = tmp_project / "ontology" / "generated" / "schema" / "schema.ttl"
    assert (KOS.ReviewCheck, None, None) in Graph().parse(out)
    g = Graph().parse(tmp_project / "ontology" / "provenance.ttl")
    acts = list(g.subjects(RDF.type, PROV.Activity))
    assert len(acts) == 1
    assert str(g.value(acts[0], KOS.model)) == "fake-model"
    assert "予定" in capsys.readouterr().out


def test_integrity_stage_writes_shapes(tmp_project, fake_provider):
    write_turtle(Graph(), tmp_project / "ontology" / "schema.ttl")
    assert main(["integrity", "--root", str(tmp_project), "--provider", fake_provider]) == 0
    assert (tmp_project / "ontology" / "generated" / "shapes" / "integrity.ttl").exists()


def test_validate_reports_violation(tmp_project, capsys):
    shapes = tmp_project / "ontology" / "shapes"
    shapes.mkdir()
    (shapes / "integrity.ttl").write_text(
        "@prefix sh: <http://www.w3.org/ns/shacl#> .\n"
        "@prefix kos: <https://semantica-agent.example/koseki/schema#> .\n"
        "@prefix dcterms: <http://purl.org/dc/terms/> .\n"
        "<urn:s> a sh:NodeShape ; sh:targetClass kos:Business ;\n"
        "  sh:property [ sh:path dcterms:identifier ; sh:minCount 1 ] .\n",
        encoding="utf-8",
    )
    (tmp_project / "ontology" / "x.ttl").write_text(
        "<urn:b> a <https://semantica-agent.example/koseki/schema#Business> .", encoding="utf-8"
    )
    assert main(["validate", "--root", str(tmp_project)]) == 1
    assert "urn:b" in capsys.readouterr().out


def test_validate_without_shapes_fails(tmp_project):
    assert main(["validate", "--root", str(tmp_project)]) == 1


def test_derived_stage_writes_definitions(tmp_project):
    assert main(["derived", "--root", str(tmp_project)]) == 0
    g = Graph().parse(tmp_project / "ontology" / "law" / "derived.ttl")
    assert len(list(g.subjects(RDF.type, KOS.DerivedValue))) >= 6


def test_approve_marks_node(tmp_project):
    f = tmp_project / "ontology" / "law" / "amendments.ttl"
    f.parent.mkdir(parents=True)
    f.write_text(
        "@prefix kos: <https://semantica-agent.example/koseki/schema#> .\n"
        "<https://semantica-agent.example/koseki/id/amendment/R4-102>"
        " kos:reviewStatus kos:LlmDraft .\n",
        encoding="utf-8",
    )
    args = [
        "approve",
        "AMENDMENT-R4-102",
        "--by",
        "reviewer",
        "--file",
        str(f),
        "--root",
        str(tmp_project),
    ]
    assert main(args) == 0
    g = Graph().parse(f)
    assert (None, KOS.reviewStatus, KOS.HumanReviewed) in g


def test_api_key_stops(tmp_project, monkeypatch, fake_provider):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert main(["schema", "--root", str(tmp_project), "--provider", fake_provider]) == 1


def test_extract_reads_pdf_path_error(tmp_project):
    assert main(["extract", "--root", str(tmp_project)]) == 1


def test_instances_from_saved_run(tmp_project, sample, birth_rows):
    import json as _json

    from semantica_agent.extract import save_rows as _save

    _save(birth_rows, tmp_project / "data" / "extracted" / "rows.json")
    write_turtle(Graph(), tmp_project / "ontology" / "schema.ttl")
    run = tmp_project / "data" / "generation" / "instances-1"
    run.mkdir(parents=True)
    bad = {**sample, "business": "birth", "steps": []}
    (run / "001-response.txt").write_text(_json.dumps(bad, ensure_ascii=False), encoding="utf-8")
    (run / "001-meta.json").write_text('{"model": "m-old"}', encoding="utf-8")
    (run / "002-response.txt").write_text(
        "```json\n" + _json.dumps(sample, ensure_ascii=False) + "\n```", encoding="utf-8"
    )
    (run / "002-meta.json").write_text('{"model": "m-saved"}', encoding="utf-8")
    args = [
        "instances",
        "--business",
        "birth",
        "--from-run",
        "instances-1",
        "--root",
        str(tmp_project),
    ]
    assert main(args) == 0
    g = Graph().parse(tmp_project / "ontology" / "generated" / "instances" / "birth.ttl")
    assert (None, RDF.type, KOS.ReviewCheck) in g
    prov = Graph().parse(tmp_project / "ontology" / "provenance.ttl")
    assert (None, KOS.model, None) in prov
    assert "m-saved" in {str(o) for o in prov.objects(None, KOS.model)}
