import pytest
from rdflib import OWL, RDF, RDFS, Literal
from semantica.semantic_extract.registry import provider_registry

from semantica_agent.extract import Row, render_rows
from semantica_agent.namespaces import KOS
from semantica_agent.schema_gen import (
    KosekiOntologyGenerator,
    check_schema_coverage,
    generate_schema,
    schema_dict_to_graph,
    schema_summary,
)
from semantica_agent.vocab import REQUIRED_CLASSES, REQUIRED_PROPERTIES


@pytest.fixture
def rows_sample():
    return [
        Row("p2-r5", "table", "birth", "1.受付", "★下記(1)から(2)まで", "", 2, 1, 197.0),
        Row(
            "p2-r21",
            "table",
            "birth",
            "2.審査",
            "○届出地に該当しているか。",
            "戸籍法第25条",
            2,
            1,
            475.0,
        ),
    ]


def test_render_rows(rows_sample):
    text = render_rows(rows_sample)
    assert "p2-r21 | birth | 2.審査 | ○届出地に該当しているか。 | 戸籍法第25条" in text


def test_prompt_contains_required_names_and_rows(rows_sample):
    p = KosekiOntologyGenerator(provider=None)._build_prompt(text=render_rows(rows_sample))
    assert "ReviewCheck" in p and "citesProvision" in p and "p2-r5" in p
    assert "NeedsInquiry" in p
    assert "$rows" not in p


def _full_schema(extra_class=None):
    classes = [{"name": n, "label_ja": j} for n, j in REQUIRED_CLASSES.items()]
    if extra_class:
        classes.append(extra_class)
    props = [{"name": n, "type": "data", "label_ja": j} for n, j in REQUIRED_PROPERTIES.items()]
    return {"classes": classes, "properties": props}


def test_coverage_reports_missing_and_extra():
    schema = {
        "classes": [{"name": "Business"}, {"name": "Foo", "speculative": True}],
        "properties": [],
    }
    r = check_schema_coverage(schema)
    assert "ReviewCheck" in r.missing and "citesProvision" in r.missing
    assert r.extra == ("Foo",) and r.speculative == ("Foo",)


def test_coverage_of_complete_schema_is_empty():
    r = check_schema_coverage(_full_schema())
    assert (r.missing, r.extra) == ((), ())


def test_schema_dict_to_graph_keeps_japanese_label():
    g = schema_dict_to_graph(
        {"classes": [{"name": "Business", "label_ja": "業務"}], "properties": []}
    )
    assert (KOS.Business, RDFS.label, Literal("業務", lang="ja")) in g
    assert (KOS.Business, RDF.type, OWL.Class) in g
    assert (KOS.Reject, RDF.type, OWL.NamedIndividual) in g


def test_schema_dict_to_graph_property_types_and_ranges():
    g = schema_dict_to_graph(
        {
            "classes": [],
            "properties": [
                {
                    "name": "citesProvision",
                    "type": "object",
                    "domain": ["StepItem"],
                    "range": ["LegalProvision"],
                },
                {"name": "filingDate", "type": "data", "domain": ["Filing"], "range": ["xsd:date"]},
            ],
        }
    )
    assert (KOS.citesProvision, RDF.type, OWL.ObjectProperty) in g
    assert (KOS.citesProvision, RDFS.range, KOS.LegalProvision) in g
    assert (KOS.filingDate, RDF.type, OWL.DatatypeProperty) in g
    assert str(g.value(KOS.filingDate, RDFS.range)).endswith("#date")


def test_speculative_class_is_marked():
    g = schema_dict_to_graph(
        {"classes": [{"name": "Foo", "speculative": True, "reason": "要るから"}], "properties": []}
    )
    assert (KOS.Foo, KOS.sourceKind, KOS.Speculation) in g
    assert any("要るから" in str(c) for c in g.objects(KOS.Foo, RDFS.comment))


def test_non_ascii_name_is_rejected():
    with pytest.raises(ValueError, match="届出"):
        schema_dict_to_graph({"classes": [{"name": "届出"}], "properties": []})


def test_schema_summary_lists_names():
    g = schema_dict_to_graph(_full_schema())
    text = schema_summary(g)
    assert "ReviewCheck" in text and "審査項目" in text and "citesProvision" in text


class FakeProvider:
    def __init__(self, **kwargs):
        self.last_model = "fake-model"

    def generate_structured(self, prompt, **kwargs):
        assert "ReviewCheck" in prompt
        return {
            "classes": [{"name": "Business", "label_ja": "業務", "comment_ja": "c"}],
            "properties": [],
        }


def test_generate_schema_uses_registered_provider(rows_sample):
    provider_registry.register("fake_schema", FakeProvider)
    try:
        out = generate_schema(rows_sample, provider="fake_schema")
    finally:
        provider_registry.unregister("fake_schema")
    assert out["classes"][0]["label_ja"] == "業務"
    assert out["metadata"]["model"] == "fake-model"
