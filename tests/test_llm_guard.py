import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
E2E = "tests/test_agent_e2e.py"


def _collect(*args):
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return out.stdout


def test_llm_tests_are_deselected_without_marker_option():
    out = _collect(E2E)
    assert "test_agent_e2e.py::" not in out
    assert "deselected" in out


def test_llm_tests_are_deselected_with_other_marker_expression():
    out = _collect("-m", "not slow", E2E)
    assert "test_agent_e2e.py::" not in out


def test_llm_tests_are_collected_with_llm_marker():
    out = _collect("-m", "llm", E2E)
    assert "test_agent_e2e.py::" in out
