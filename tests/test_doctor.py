from semantica_agent.doctor import CheckResult, check_imports, check_ontology_roundtrip, run_checks


def test_check_imports_reports_semantica_and_agent_sdk():
    results = check_imports()
    names = {r.name for r in results}
    assert {"semantica", "claude_agent_sdk"} <= names
    assert all(r.ok for r in results), [r for r in results if not r.ok]


def test_check_ontology_roundtrip_builds_classes_from_sample():
    result = check_ontology_roundtrip()
    assert result.ok, result.detail


def test_run_checks_returns_only_check_results():
    results = run_checks()
    assert results
    assert all(isinstance(r, CheckResult) for r in results)
