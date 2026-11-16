"""インスタンスの LLM 生成と Turtle 化（仕様 §5.4）。IRI と出典はコードが決める。"""

import logging
from string import Template

from rdflib import RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV
from semantica.semantic_extract.providers import create_provider

from semantica_agent.extract import Row, render_rows
from semantica_agent.ids import (
    article_iri,
    business_iri,
    item_iri,
    law_iri,
    manual_source_iri,
    provision_iri,
    short_id,
    step_iri,
    version_iri,
    vocab_iri,
)
from semantica_agent.instance_check import (
    InstanceValidationError,
    cite_to_ref,
    has_article,
    ref_text,
    validate_instance_output,
)
from semantica_agent.llm_provider import PROVIDER_NAME
from semantica_agent.namespaces import KOS, bind_prefixes
from semantica_agent.schema_gen import prompt_path
from semantica_agent.vocab import BUSINESS_SLUGS, ITEM_VOCAB_FIELDS

logger = logging.getLogger(__name__)

_KIND_CLASS = {"check": KOS.ReviewCheck, "task": KOS.Task, "note": KOS.StepItem}
_BUSINESS_NAMES = {v: k for k, v in BUSINESS_SLUGS.items()}


def build_instance_prompt(
    business: str, rows: list[Row], schema_text: str, known_laws: list[str]
) -> str:
    vocab = "\n".join(
        f"- {field}（{kind}）：{'、'.join(table)}"
        for field, (kind, table, _, _) in ITEM_VOCAB_FIELDS.items()
    )
    return Template(prompt_path("instances").read_text(encoding="utf-8")).substitute(
        business=business,
        rows=render_rows(rows),
        schema=schema_text,
        laws="、".join(known_laws) or "（なし）",
        vocab=vocab,
    )


def generate_instances(
    business: str,
    rows: list[Row],
    schema_text: str,
    known_laws: list[str],
    provider: str = PROVIDER_NAME,
    **provider_kwargs,
) -> dict:
    llm = create_provider(provider, **provider_kwargs)
    out = llm.generate_structured(build_instance_prompt(business, rows, schema_text, known_laws))
    if not isinstance(out, dict):
        raise InstanceValidationError([f"JSON の最上位がオブジェクトではありません: {type(out)}"])
    errors = validate_instance_output(out, rows)
    if errors:
        raise InstanceValidationError(errors)
    return {**out, "metadata": {"model": getattr(llm, "last_model", None)}}


class _Builder:
    def __init__(self, out: dict, rows: list[Row], activity: URIRef):
        self.biz = out["business"]
        self.rows = {r.row_id: r for r in rows}
        self.act = activity
        self.g = bind_prefixes(Graph())
        self.laws = bind_prefixes(Graph())

    def node(self, g: Graph, iri: URIRef, cls: URIRef, label: str | None = None) -> URIRef:
        g.add((iri, RDF.type, cls))
        g.add((iri, DCTERMS.identifier, Literal(short_id(iri))))
        g.add((iri, KOS.reviewStatus, KOS.LlmDraft))
        g.add((iri, PROV.wasGeneratedBy, self.act))
        if label:
            g.add((iri, RDFS.label, Literal(label, lang="ja")))
        return iri

    def sources(self, g: Graph, subject: URIRef, row_ids: list[str]) -> None:
        for rid in row_ids or []:
            row = self.rows[rid]
            src = manual_source_iri(rid)
            if (src, RDF.type, KOS.SourceReference) not in self.g:
                self.node(self.g, src, KOS.SourceReference)
                for p, v in (
                    (KOS.sourceKind, KOS.ManualSource),
                    (KOS.rowId, Literal(rid)),
                    (KOS.pdfPage, Literal(row.pdf_page)),
                    (KOS.businessName, Literal(_BUSINESS_NAMES.get(self.biz, self.biz), lang="ja")),
                    (
                        KOS.quote,
                        Literal(" ".join(x for x in (row.procedure, row.remarks) if x), lang="ja"),
                    ),
                ):
                    self.g.add((src, p, v))
                if row.printed_page is not None:
                    self.g.add((src, KOS.printedPage, Literal(row.printed_page)))
                if row.division:
                    self.g.add((src, KOS.division, Literal(row.division, lang="ja")))
            g.add((subject, KOS.hasSource, src))

    def cite(self, subject: URIRef, cite: dict, row_ids: list[str]) -> None:
        ref = cite_to_ref(cite)
        law = self.node(self.laws, law_iri(ref.law), KOS.Law, ref.law)
        art_ref = cite_to_ref({**cite, "paragraph": None, "item": None})
        art = self.node(self.laws, article_iri(ref), KOS.LegalProvision, ref_text(art_ref))
        self.laws.add((art, KOS.partOfLaw, law))
        self.laws.add((art, KOS.article, Literal(ref.article)))
        if ref.branch:
            self.laws.add((art, KOS.articleBranch, Literal(ref.branch)))
        prov = provision_iri(ref)
        self.node(self.laws, prov, KOS.LegalProvision, ref_text(ref))
        if prov != art:
            self.laws.add((prov, KOS.partOf, art))
            self.laws.add((prov, KOS.partOfLaw, law))
            for p, v in ((KOS.paragraph, ref.paragraph), (KOS.item, ref.item)):
                if v is not None:
                    self.laws.add((prov, p, Literal(v)))
        ver = self.node(self.laws, version_iri(prov, "manual"), KOS.ProvisionVersion)
        self.laws.add((ver, KOS.versionStatus, KOS.Manual))
        self.laws.add((prov, KOS.hasVersion, ver))
        for n in (law, art, prov, ver):
            self.sources(self.laws, n, row_ids)
        self.g.add((subject, KOS.citesProvision, prov))
        if cite.get("normalization_note"):
            self.g.add(
                (subject, KOS.normalizationNote, Literal(cite["normalization_note"], lang="ja"))
            )

    def item(
        self, step: int, pos: tuple[int, ...], item: dict, parent: URIRef, link: URIRef
    ) -> None:
        iri = self.node(
            self.g, item_iri(self.biz, step, pos), _KIND_CLASS[item["kind"]], item["text"]
        )
        self.g.add((parent, link, iri))
        self.g.add((iri, KOS.itemLabel, Literal(item.get("label") or "")))
        self.g.add((iri, KOS.itemOrder, Literal(pos[-1])))
        self.g.add((iri, KOS.quote, Literal(item["quote"], lang="ja")))
        self.sources(self.g, iri, item["row_ids"])
        remark_rows = item.get("remark_row_ids") or item["row_ids"]
        for cite in item.get("cites") or []:
            if has_article(cite):
                self.cite(iri, cite, remark_rows)
            else:
                note = f"根拠法令（条の指定なし）：{cite.get('law')}"
                self.g.add((iri, RDFS.comment, Literal(note, lang="ja")))
        for field, (kind, table, cls, prop) in ITEM_VOCAB_FIELDS.items():
            for name in item.get(field) or []:
                v = self.node(self.g, vocab_iri(kind, table[name]), KOS[cls], name)
                self.sources(self.g, v, item["row_ids"])
                self.g.add((iri, KOS[prop], v))
        for note in item.get("notes") or []:
            self.g.add((iri, RDFS.comment, Literal(note, lang="ja")))
        if item.get("alignment") == "uncertain":
            self.g.add((iri, KOS.alignment, Literal("uncertain")))
        if item.get("speculative"):
            self.g.add((iri, KOS.sourceKind, KOS.Speculation))
            self.g.add((iri, RDFS.comment, Literal(f"推測：{item['reason']}", lang="ja")))
        if item.get("prerequisite_for") is not None:
            self.g.add((iri, KOS.prerequisiteFor, step_iri(self.biz, item["prerequisite_for"])))
        for i, child in enumerate(item.get("children") or [], start=1):
            self.item(step, (*pos, i), child, iri, KOS.hasSubItem)

    def build(self, out: dict) -> tuple[Graph, Graph]:
        biz = self.node(self.g, business_iri(self.biz), KOS.Business, _BUSINESS_NAMES.get(self.biz))
        titles = [
            r.row_id for r in self.rows.values() if r.kind == "title" and r.business == self.biz
        ]
        self.sources(self.g, biz, titles)
        steps = sorted(out["steps"], key=lambda s: s["number"])
        for prev, nxt in zip(steps, steps[1:], strict=False):
            self.g.add(
                (
                    step_iri(self.biz, prev["number"]),
                    KOS.nextStep,
                    step_iri(self.biz, nxt["number"]),
                )
            )
        for step in steps:
            s = self.node(
                self.g, step_iri(self.biz, step["number"]), KOS.ProcedureStep, step["label"]
            )
            self.g.add((biz, KOS.hasStep, s))
            self.g.add((s, KOS.stepNumber, Literal(step["number"])))
            self.sources(self.g, s, step.get("row_ids"))
            for cite in step.get("cites") or []:
                self.cite(s, cite, step.get("row_ids"))
            for i, item in enumerate(step.get("items") or [], start=1):
                self.item(step["number"], (i,), item, s, KOS.hasItem)
        for note in out.get("notes") or []:
            self.g.add((biz, RDFS.comment, Literal(note["text"], lang="ja")))
            self.sources(self.g, biz, note.get("row_ids"))
        return self.g, self.laws


def instances_to_graph(out: dict, rows: list[Row], activity: URIRef) -> tuple[Graph, Graph]:
    return _Builder(out, rows, activity).build(out)
