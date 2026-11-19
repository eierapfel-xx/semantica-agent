from rdflib import RDF, RDFS, Graph, Literal

from semantica_agent.build.shapes_gen import (
    RULE_TABLE,
    build_integrity_prompt,
    build_rules_prompt,
    check_shapes_text,
    extract_turtle,
)
from semantica_agent.core.ids import item_iri, rule_iri
from semantica_agent.core.namespaces import KD, KOS

PREFIX = """
@base <https://semantica-agent.example/koseki/> .
@prefix kos: <https://semantica-agent.example/koseki/schema#> .
@prefix kd: <id/> .
@prefix sh: <http://www.w3.org/ns/shacl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix dcterms: <http://purl.org/dc/terms/> .
"""


def _rule_ttl(rid, slug, with_version=True):
    version = " kos:underVersion <id/law/koseki-ho/art/49/version/manual> ;" if with_version else ""
    return f"""
<id/rule/birth/{slug}> a kos:JudgmentRule ; dcterms:identifier "{rid}" ;
  kos:implementsCheck <id/birth/step/2/item/9> ; kos:outcome kos:AdditionalProcedure ;{version}
  kos:shape <id/shape/birth/{slug}> .
<id/shape/birth/{slug}> a sh:NodeShape ; sh:targetClass kos:BirthFiling ;
  sh:severity sh:Warning ; sh:property [ sh:path kos:daysLate ; sh:maxInclusive 0 ] .
"""


def _all_rules_ttl():
    return PREFIX + "".join(_rule_ttl(r.id, r.slug) for r in RULE_TABLE)


def test_rule_table_covers_spec():
    ids = [r.id for r in RULE_TABLE]
    assert ids == [
        "B1",
        "B2",
        "B3",
        "B4a",
        "B4b",
        "B4c",
        "B5",
        "B6",
        "B7",
        "B8",
        "B9",
        "B10",
        "B11",
        "B12",
    ]
    assert {r.outcome for r in RULE_TABLE} <= {
        "Reject",
        "NeedsCorrection",
        "NeedsInquiry",
        "AdditionalProcedure",
        "Info",
    }


def test_extract_turtle_from_fence():
    assert extract_turtle("前置き\n```turtle\n<a> <b> <c> .\n```\n") == "<a> <b> <c> ."


def test_check_shapes_rejects_broken_turtle():
    assert check_shapes_text("not turtle", require_rules=False)


def test_check_shapes_accepts_complete_rules():
    assert check_shapes_text(_all_rules_ttl(), require_rules=True) == []


def test_check_shapes_requires_all_rules():
    partial = PREFIX + "".join(_rule_ttl(r.id, r.slug) for r in RULE_TABLE if r.id != "B9")
    errors = check_shapes_text(partial, require_rules=True)
    assert any("B9" in e for e in errors)


def test_check_shapes_requires_version_where_table_says():
    ttl = PREFIX + "".join(_rule_ttl(r.id, r.slug, with_version=r.id != "B4b") for r in RULE_TABLE)
    assert any(
        "B4b" in e and "underVersion" in e for e in check_shapes_text(ttl, require_rules=True)
    )


def test_check_shapes_requires_existing_shape():
    ttl = _all_rules_ttl().replace("id/shape/birth/filing-period> .", "id/shape/birth/none> .")
    assert any("B9" in e and "shape" in e for e in check_shapes_text(ttl, require_rules=True))


def test_check_shapes_detects_invalid_shacl():
    ttl = PREFIX + 'kd:s a sh:NodeShape ; sh:minCount "x" .'
    assert check_shapes_text(ttl, require_rules=False)


def _mini_graphs():
    inst = Graph()
    item = item_iri("birth", 2, (9,))
    inst.add((item, RDF.type, KOS.ReviewCheck))
    inst.add((item, RDFS.label, Literal("届出期間内の届出か。", lang="ja")))
    inst.add((item, KOS.citesProvision, KD["law/koseki-ho/art/49"]))
    laws = Graph()
    v = KD["law/minpo/art/772/version/2024-04-01"]
    laws.add((v, RDF.type, KOS.ProvisionVersion))
    laws.add((v, KOS.versionStatus, KOS.Current))
    return inst, laws


def test_rules_prompt_contains_rule_table_and_versions():
    prompt = build_rules_prompt(*_mini_graphs(), "SCHEMA")
    assert (
        "B4b" in prompt and str(rule_iri("birth", "legitimacy-current")).split("/id/")[1] in prompt
    )
    assert "BIRTH-S2-I9" in prompt and "LAW-MINPO-772-V20240401" in prompt
    assert "validFrom" in prompt and "sh:Warning" in prompt and "SCHEMA" in prompt


def test_integrity_prompt_contains_schema():
    assert "SCHEMA" in build_integrity_prompt("SCHEMA")


def test_rules_without_cited_law_do_not_require_version():
    specs = {r.id: r for r in RULE_TABLE}
    assert specs["B6"].version is None and specs["B7"].version is None
