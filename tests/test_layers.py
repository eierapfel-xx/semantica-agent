"""パッケージの層と依存の向き。仕様 §3。"""

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "semantica_agent"
LAYERS = {
    "core": set(),
    "review": {"core"},
    "build": {"core", "review"},
    "agent": {"core", "review"},
    "web": {"core", "review", "agent"},
}


def _imported_layers(path: Path) -> set[str]:
    tree = ast.parse(path.read_text("utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
    parts = [n.split(".") for n in names if n.startswith("semantica_agent.")]
    return {p[1] for p in parts if len(p) > 1}


def test_layer_imports_point_one_way():
    violations = []
    for layer, allowed in LAYERS.items():
        files = sorted((PKG / layer).rglob("*.py"))
        assert files, f"{layer} にモジュールがありません"
        for f in files:
            bad = _imported_layers(f) - allowed - {layer}
            violations += [f"{f.relative_to(PKG)}: {b}" for b in sorted(bad)]
    assert violations == []


def test_old_flat_modules_are_gone():
    flat = {p.name for p in PKG.glob("*.py")}
    assert flat == {"__init__.py", "doctor.py"}
