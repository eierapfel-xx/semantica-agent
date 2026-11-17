import time

import pytest

from semantica_agent.tools import (
    Knowledge,
    ToolError,
    describe_node,
    run_cq,
    run_sparql,
    search_nodes,
)


def test_search_nodes_finds_waiting_period(knowledge):
    r = search_nodes(knowledge, "待婚期間")
    assert any(n.startswith("MARRIAGE-S2") for n in r.nodes)
    assert r.flow == {"referenced": r.nodes}


def test_search_nodes_filters_and_limits(knowledge):
    r = search_nodes(knowledge, "の", business="birth")
    assert 0 < len(r.nodes) <= 20 and all(n.startswith("BIRTH-") for n in r.nodes)
    r2 = search_nodes(knowledge, "届出", cls="ReviewCheck")
    assert all(h["classes"] == ["ReviewCheck"] for h in r2.payload["hits"])


def test_describe_node_has_sources(knowledge):
    r = describe_node(knowledge, "BIRTH-S2-I11")
    p = r.payload
    assert p["label"] == "届出期間内の届出か。"
    assert p["sources"][0]["quote"]
    assert p["provisions"] and p["parents"] == [{"id": "BIRTH-S2", "label": "審査"}]
    assert "RULE-BIRTH-FILING-PERIOD" in [x["id"] for x in p["rules"]]
    assert r.nodes == ["BIRTH-S2-I11"]


def test_describe_rule_and_versions(knowledge):
    p = describe_node(knowledge, "RULE-BIRTH-LEGITIMACY-CURRENT").payload
    assert p["properties"]["outcome"] == ["NeedsCorrection"]


def test_describe_unknown_node(knowledge):
    with pytest.raises(ToolError, match="NOPE"):
        describe_node(knowledge, "NOPE-1")


def test_run_cq2_references_step7_of_four_businesses(knowledge):
    r = run_cq(knowledge, 2)
    assert {"BIRTH-S7", "MARRIAGE-S8", "DIVORCE-S7", "DEATH-S7"} <= set(r.nodes)
    assert knowledge.cq_titles[2].startswith("戸籍法施行規則第48条")


def test_run_cq_bad_number(knowledge):
    with pytest.raises(ToolError):
        run_cq(knowledge, 99)


@pytest.mark.parametrize(
    "q",
    [
        "INSERT DATA { <urn:a> <urn:b> <urn:c> }",
        "SELECT * WHERE { SERVICE <http://x> { ?s ?p ?o } }",
        "CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }",
        "SELEC broken",
    ],
)
async def test_run_sparql_rejects(knowledge, q):
    with pytest.raises(ToolError):
        await run_sparql(knowledge, q, 10)


async def test_run_sparql_limits_rows(knowledge):
    r = await run_sparql(knowledge, "SELECT ?s WHERE { ?s ?p ?o }", 10)
    assert len(r.payload["rows"]) == 200 and r.payload["truncated"]


async def test_run_sparql_short_ids(knowledge):
    q = (
        "PREFIX kos: <https://semantica-agent.example/koseki/schema#> "
        "SELECT ?s WHERE { ?s kos:stepNumber 7 }"
    )
    r = await run_sparql(knowledge, q, 10)
    assert "BIRTH-S7" in r.nodes and {"s": "BIRTH-S7"} in r.payload["rows"]


async def test_run_sparql_timeout(knowledge, monkeypatch):
    def slow(self, *a, **kw):
        time.sleep(1)
        return []

    monkeypatch.setattr(type(knowledge.ontology), "query", slow)
    with pytest.raises(ToolError, match="時間"):
        await run_sparql(knowledge, "SELECT ?s WHERE { ?s ?p ?o }", 0.1)


def test_knowledge_load_missing_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        Knowledge.load(tmp_path)


def test_describe_versions_carry_egov_sources(knowledge):
    p = describe_node(knowledge, "BIRTH-S2-I5").payload
    versions = [v for prov in p["provisions"] for v in prov["versions"]]
    assert any(s.get("url", "").startswith("https://") for v in versions for s in v["sources"])
