"""開発環境が使える状態かを確かめる。`uv run python -m semantica_agent.doctor` で実行する。"""

import importlib
import logging
import os
import shutil
import sys
from dataclasses import dataclass

from semantica_agent.core.settings import ConfigError

logger = logging.getLogger(__name__)

REQUIRED_MODULES = ("semantica", "semantica.ontology", "rdflib", "pyshacl", "claude_agent_sdk")
SAMPLE_BASE_URI = "https://example.org/doctor#"
# semantica のクラス推論は、型名を ASCII に正規化し、2 回以上出た型だけをクラスにする。
# 日本語の型名は全部 "Entity" に潰れて衝突エラーになるので、型名は英語で書く。
SAMPLE_DATA = {
    "entities": [
        {"name": "出生届", "type": "Notification"},
        {"name": "婚姻届", "type": "Notification"},
        {"name": "受付", "type": "Step"},
        {"name": "審査", "type": "Step"},
    ],
    "relationships": [
        {"source": "出生届", "target": "受付", "type": "hasStep"},
        {"source": "婚姻届", "target": "審査", "type": "hasStep"},
    ],
}


@dataclass(frozen=True)
class CheckResult:
    name: str
    ok: bool
    detail: str


def check_imports() -> list[CheckResult]:
    results = []
    for name in REQUIRED_MODULES:
        try:
            module = importlib.import_module(name)
        except ImportError as exc:
            results.append(CheckResult(name, False, f"import に失敗: {exc}"))
            continue
        version = getattr(module, "__version__", "")
        results.append(CheckResult(name, True, version))
    return results


def check_ontology_roundtrip() -> CheckResult:
    from semantica.ontology import OntologyGenerator

    ontology = OntologyGenerator(base_uri=SAMPLE_BASE_URI).generate_ontology(SAMPLE_DATA)
    classes = ontology.get("classes", [])
    logger.debug("doctor ontology: %s", ontology)
    if not classes:
        return CheckResult("ontology", False, "サンプルからクラスが生成されなかった")
    return CheckResult("ontology", True, f"{len(classes)} classes")


def check_claude_cli() -> CheckResult:
    # Agent SDK は同梱の CLI を使うが、Pro のログインは `claude` で済ませておく必要がある。
    path = shutil.which("claude")
    if path is None:
        return CheckResult("claude CLI", False, "`claude` が PATH に無い。ログインに使う")
    return CheckResult("claude CLI", True, path)


def check_bundled_cli() -> CheckResult:
    # Claude Code 版（claude-code-agent/run.sh）は、SDK 版と同じ同梱の CLI で動かす。
    from semantica_agent.agent.claude_code import bundled_cli, bundled_cli_version

    name = "Claude Code（SDK 同梱）"
    try:
        cli = bundled_cli()
    except ConfigError as e:
        return CheckResult(name, False, str(e))
    version = bundled_cli_version(cli)
    return CheckResult(name, version is not None, version or f"版を取れません: {cli}")


def run_checks() -> list[CheckResult]:
    return [*check_imports(), check_ontology_roundtrip(), check_claude_cli(), check_bundled_cli()]


def main() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    results = run_checks()
    for r in results:
        mark = "OK " if r.ok else "NG "
        print(f"{mark} {r.name:<20} {r.detail}")
    print(f"python {sys.version.split()[0]}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
