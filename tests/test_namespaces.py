from rdflib import Graph

from semantica_agent.namespaces import KCASE, KD, KOS, PREFIXES, bind_prefixes


def test_namespaces_match_spec():
    assert str(KOS) == "https://semantica-agent.example/koseki/schema#"
    assert str(KD) == "https://semantica-agent.example/koseki/id/"
    assert str(KCASE) == "https://semantica-agent.example/koseki/case/"


def test_prefixes_match_namespaces():
    assert PREFIXES["kos"] == str(KOS)
    assert {"kd", "kcase", "prov", "sh", "dcterms", "rdfs", "owl", "xsd"} <= PREFIXES.keys()


def test_bind_prefixes_returns_graph_with_prefixes():
    g = bind_prefixes(Graph())
    assert dict(g.namespaces())["kos"].toPython() == str(KOS)
