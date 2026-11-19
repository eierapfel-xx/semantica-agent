"""スキーマの LLM 生成と網羅の照合。仕様 §5.3。"""

import logging
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from string import Template

from rdflib import OWL, RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import XSD
from semantica.ontology.llm_generator import LLMOntologyGenerator

from semantica_agent.build.extract import Row, render_rows
from semantica_agent.build.llm_provider import PROVIDER_NAME
from semantica_agent.core.namespaces import KOS, bind_prefixes
from semantica_agent.core.vocab import ENUM_INDIVIDUALS, REQUIRED_CLASSES, REQUIRED_PROPERTIES

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "1.0"
ONTOLOGY_IRI = URIRef(str(KOS).rstrip("#"))
_EXTRA_KEYS = ("label_ja", "comment_ja", "speculative", "reason")
_RANGE_PREFIXES = {"xsd": str(XSD), "rdf": str(RDF)}


def prompt_path(name: str) -> Path:
    return Path(str(resources.files("semantica_agent.build") / "prompts" / f"{name}.md"))


def _bullets(table: dict[str, str]) -> str:
    return "\n".join(f"- `{n}`：{j}" for n, j in table.items())


class KosekiOntologyGenerator(LLMOntologyGenerator):
    def _build_prompt(self, **kwargs) -> str:
        template = Template(prompt_path("schema").read_text(encoding="utf-8"))
        enums = "\n".join(f"- `{k}`：{', '.join(v)}" for k, v in ENUM_INDIVIDUALS.items())
        return template.substitute(
            rows=kwargs.get("text") or "",
            required_classes=_bullets(REQUIRED_CLASSES),
            required_properties=_bullets(REQUIRED_PROPERTIES),
            enums=enums,
        )

    def _normalize_output(self, result, **meta):
        base = super()._normalize_output(result, **meta)
        raw = {
            "classes": result.get("classes") or [],
            "properties": result.get("properties") or [],
        }
        for kind in ("classes", "properties"):
            for norm, src in zip(base[kind], raw[kind], strict=True):
                norm.update({k: src.get(k) for k in _EXTRA_KEYS})
                if kind == "classes" and src.get("parent"):
                    norm["parent"] = src["parent"]
        base["metadata"]["model"] = getattr(self.provider, "last_model", None)
        return base


def generate_schema(
    rows: list[Row], provider: str = PROVIDER_NAME, model: str | None = None, **provider_kwargs
) -> dict:
    gen = KosekiOntologyGenerator(provider=None)
    gen.set_provider(provider, model=model, **provider_kwargs)
    return gen.generate_ontology_from_text(
        render_rows(rows), name="KosekiOntology", base_uri=str(KOS), version=SCHEMA_VERSION
    )


@dataclass(frozen=True)
class CoverageReport:
    missing: tuple[str, ...]
    extra: tuple[str, ...]
    speculative: tuple[str, ...]


def check_schema_coverage(schema: dict) -> CoverageReport:
    classes = {c["name"] for c in schema.get("classes", [])}
    props = {p["name"] for p in schema.get("properties", [])}
    missing = (REQUIRED_CLASSES.keys() - classes) | (REQUIRED_PROPERTIES.keys() - props)
    extra = (classes - REQUIRED_CLASSES.keys()) | (props - REQUIRED_PROPERTIES.keys())
    spec = {
        e["name"]
        for e in [*schema.get("classes", []), *schema.get("properties", [])]
        if e.get("speculative")
    }
    return CoverageReport(tuple(sorted(missing)), tuple(sorted(extra)), tuple(sorted(spec)))


def _check_name(name: str, upper: bool) -> None:
    ok = name.isascii() and name[:1].isalpha() and (name[0].isupper() == upper)
    if not ok:
        rule = "UpperCamelCase" if upper else "lowerCamelCase"
        raise ValueError(f"名前は英語の {rule} にしてください: {name}")


def _range_iri(value: str) -> URIRef:
    prefix, _, local = value.partition(":")
    if local and prefix in _RANGE_PREFIXES:
        return URIRef(_RANGE_PREFIXES[prefix] + local)
    return KOS[value]


def _add_common(g: Graph, node: URIRef, entry: dict) -> None:
    label = entry.get("label_ja") or entry.get("label")
    if label:
        g.add((node, RDFS.label, Literal(label, lang="ja")))
    comment = entry.get("comment_ja") or entry.get("comment")
    if comment:
        g.add((node, RDFS.comment, Literal(comment, lang="ja")))
    if entry.get("speculative"):
        g.add((node, KOS.sourceKind, KOS.Speculation))
        g.add(
            (node, RDFS.comment, Literal(f"推測：{entry.get('reason') or '理由なし'}", lang="ja"))
        )


def schema_dict_to_graph(schema: dict) -> Graph:
    g = bind_prefixes(Graph())
    g.add((ONTOLOGY_IRI, RDF.type, OWL.Ontology))
    g.add((ONTOLOGY_IRI, OWL.versionInfo, Literal(SCHEMA_VERSION)))
    for c in schema.get("classes", []):
        _check_name(c["name"], upper=True)
        node = KOS[c["name"]]
        g.add((node, RDF.type, OWL.Class))
        if c.get("parent"):
            g.add((node, RDFS.subClassOf, KOS[c["parent"]]))
        _add_common(g, node, c)
    for p in schema.get("properties", []):
        _check_name(p["name"], upper=False)
        node = KOS[p["name"]]
        kind = OWL.ObjectProperty if p.get("type") == "object" else OWL.DatatypeProperty
        g.add((node, RDF.type, kind))
        for d in p.get("domain") or []:
            g.add((node, RDFS.domain, KOS[d]))
        for r in p.get("range") or []:
            g.add((node, RDFS.range, _range_iri(r)))
        _add_common(g, node, p)
    for prop, names in ENUM_INDIVIDUALS.items():
        for name in names:
            g.add((KOS[name], RDF.type, OWL.NamedIndividual))
            g.add((KOS[name], RDFS.comment, Literal(f"kos:{prop} の値", lang="ja")))
    return g


def schema_summary(g: Graph) -> str:
    def label(n: URIRef) -> str:
        return str(g.value(n, RDFS.label) or "")

    def local(n) -> str:
        return str(n).removeprefix(str(KOS)).removeprefix(str(XSD)).removeprefix(str(RDF))

    lines = ["## クラス"]
    for c in sorted(g.subjects(RDF.type, OWL.Class)):
        parent = g.value(c, RDFS.subClassOf)
        lines.append(f"- {local(c)}（{label(c)}）" + (f" ⊂ {local(parent)}" if parent else ""))
    lines.append("## プロパティ")
    for kind in (OWL.ObjectProperty, OWL.DatatypeProperty):
        for p in sorted(g.subjects(RDF.type, kind)):
            dom = ",".join(sorted(local(d) for d in g.objects(p, RDFS.domain)))
            rng = ",".join(sorted(local(r) for r in g.objects(p, RDFS.range)))
            lines.append(f"- {local(p)}（{label(p)}）: {dom} → {rng}")
    lines.append("## 列挙値")
    lines.append(", ".join(sorted(local(i) for i in g.subjects(RDF.type, OWL.NamedIndividual))))
    return "\n".join(lines)
