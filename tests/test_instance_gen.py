import pytest
from rdflib import RDF, Literal
from rdflib.namespace import DCTERMS, PROV
from semantica.semantic_extract.registry import provider_registry

from semantica_agent.ids import (
    ProvisionRef,
    article_iri,
    item_iri,
    manual_source_iri,
    provision_iri,
    step_iri,
    version_iri,
    vocab_iri,
)
from semantica_agent.instance_check import InstanceValidationError
from semantica_agent.instance_gen import (
    build_instance_prompt,
    generate_instances,
    instances_to_graph,
)
from semantica_agent.namespaces import KD, KOS
from semantica_agent.turtle_io import write_turtle

ACT = KD["activity/t"]


def test_prompt_contains_rows_schema_and_vocab(birth_rows):
    p = build_instance_prompt("birth", birth_rows, "SCHEMA-TEXT", ["戸籍法"])
    assert "p2-r7" in p and "SCHEMA-TEXT" in p and "出生証明書" in p and "remark_row_ids" in p


def test_items_are_typed_and_nested(sample, birth_rows):
    g, _ = instances_to_graph(sample, birth_rows, ACT)
    assert (item_iri("birth", 2, (1,)), RDF.type, KOS.ReviewCheck) in g
    assert (item_iri("birth", 1, (1,)), RDF.type, KOS.Task) in g
    assert (step_iri("birth", 1), KOS.hasItem, item_iri("birth", 1, (2,))) in g
    assert (item_iri("birth", 1, (2,)), KOS.hasSubItem, item_iri("birth", 1, (2, 1))) in g
    assert (item_iri("birth", 1, (1,)), KOS.prerequisiteFor, step_iri("birth", 2)) in g
    assert (step_iri("birth", 1), KOS.nextStep, step_iri("birth", 2)) in g
    assert g.value(item_iri("birth", 1, (2,)), KOS.itemLabel) == Literal("(1)")


def test_graph_has_source_from_rows_not_llm(sample, birth_rows):
    g, _ = instances_to_graph(sample, birth_rows, ACT)
    src = g.value(item_iri("birth", 2, (1,)), KOS.hasSource)
    assert src == manual_source_iri("p2-r7")
    assert g.value(src, KOS.pdfPage) == Literal(2)
    assert g.value(src, KOS.printedPage) == Literal(1)
    assert g.value(src, KOS.sourceKind) == KOS.ManualSource
    assert "届出地に該当しているか" in str(g.value(src, KOS.quote))


def test_every_node_has_identifier_status_and_activity(sample, birth_rows):
    g, laws = instances_to_graph(sample, birth_rows, ACT)
    for graph in (g, laws):
        for s in set(graph.subjects(RDF.type, None)):
            assert graph.value(s, DCTERMS.identifier) is not None, s
            assert graph.value(s, KOS.reviewStatus) == KOS.LlmDraft, s
            assert graph.value(s, PROV.wasGeneratedBy) == ACT, s


def test_vocab_and_escalation(sample, birth_rows):
    g, _ = instances_to_graph(sample, birth_rows, ACT)
    item = item_iri("birth", 2, (4,))
    assert (item, KOS.escalatesTo, vocab_iri("organization", "legal-affairs-bureau")) in g
    assert (item, KOS.appliesWhen, vocab_iri("condition", "no-birth-certificate")) in g
    assert (vocab_iri("organization", "legal-affairs-bureau"), RDF.type, KOS.Organization) in g


def test_law_graph_links_paragraph_to_article(sample, birth_rows):
    g, laws = instances_to_graph(sample, birth_rows, ACT)
    para = provision_iri(ProvisionRef("戸籍法", 52, paragraph=1))
    art = article_iri(ProvisionRef("戸籍法", 52))
    assert (para, KOS.partOf, art) in laws
    assert (para, RDF.type, KOS.LegalProvision) in laws
    assert (art, KOS.partOfLaw, KD["law/koseki-ho"]) in laws
    assert (item_iri("birth", 2, (2,)), KOS.citesProvision, para) in g
    v = version_iri(para, "manual")
    assert (para, KOS.hasVersion, v) in laws
    assert laws.value(v, KOS.versionStatus) == KOS.Manual


def test_instances_to_graph_is_deterministic(sample, birth_rows, tmp_path):
    for name in ("a", "b"):
        g, laws = instances_to_graph(sample, birth_rows, ACT)
        write_turtle(g + laws, tmp_path / f"{name}.ttl")
    assert (tmp_path / "a.ttl").read_bytes() == (tmp_path / "b.ttl").read_bytes()


class _Fake:
    reply: dict = {}

    def __init__(self, **kwargs):
        self.last_model = "fake"

    def generate_structured(self, prompt, **kwargs):
        return self.reply


def test_generate_instances_raises_on_invalid(sample, birth_rows):
    _Fake.reply = {**sample, "business": "death"}
    provider_registry.register("fake_inst", _Fake)
    try:
        with pytest.raises(InstanceValidationError) as e:
            generate_instances("birth", birth_rows, "S", [], provider="fake_inst")
    finally:
        provider_registry.unregister("fake_inst")
    assert any("business" in x for x in e.value.errors)


def test_generate_instances_returns_valid_output(sample, birth_rows):
    _Fake.reply = sample
    provider_registry.register("fake_inst2", _Fake)
    try:
        out = generate_instances("birth", birth_rows, "S", [], provider="fake_inst2")
    finally:
        provider_registry.unregister("fake_inst2")
    assert out["business"] == "birth" and out["metadata"]["model"] == "fake"


def test_cite_without_article_becomes_note(sample, birth_rows):
    import copy

    out = copy.deepcopy(sample)
    out["steps"][1]["items"][0]["cites"].append({"law": "地方公共団体の手数料の標準に関する政令"})
    g, _ = instances_to_graph(out, birth_rows, ACT)
    from rdflib import RDFS

    notes = {str(o) for o in g.objects(item_iri("birth", 2, (1,)), RDFS.comment)}
    assert "根拠法令（条の指定なし）：地方公共団体の手数料の標準に関する政令" in notes
