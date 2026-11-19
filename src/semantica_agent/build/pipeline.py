"""オントロジーを段ごとに生成する CLI。仕様 §5.7。

uv run python -m semantica_agent.build <段> [--root DIR]
"""

import argparse
import json
import logging
import sys
from datetime import UTC, date, datetime
from pathlib import Path

from rdflib import RDF, Graph

from semantica_agent.build import law_gen, shapes_gen
from semantica_agent.build.extract import extract_rows, load_rows, rows_for_business, save_rows
from semantica_agent.build.instance_check import InstanceValidationError, validate_instance_output
from semantica_agent.build.instance_gen import generate_instances, instances_to_graph
from semantica_agent.build.law_gen import LawFetchError
from semantica_agent.build.llm_provider import PROVIDER_NAME, extract_json, register_provider
from semantica_agent.build.provenance import record_activity
from semantica_agent.build.schema_gen import (
    check_schema_coverage,
    generate_schema,
    prompt_path,
    schema_dict_to_graph,
    schema_summary,
)
from semantica_agent.core.ids import activity_iri, iri_from_short_id, short_id
from semantica_agent.core.namespaces import KD, KOS
from semantica_agent.core.settings import ConfigError, configure_logging, load_settings
from semantica_agent.core.turtle_io import load_ontology, validate_integrity, write_turtle
from semantica_agent.core.vocab import BUSINESS_SLUGS, LAW_SLUGS
from semantica_agent.review.derive import derived_definitions_graph
from semantica_agent.review.judge import judge

logger = logging.getLogger(__name__)

PDF = Path("docs/domain/手順書.pdf")
ROWS = Path("data/extracted/rows.json")


class StageError(RuntimeError):
    pass


class Ctx:
    def __init__(self, root: Path, stage: str, provider: str):
        self.root = root
        self.stage = stage
        self.provider = provider
        self.started = datetime.now(UTC)
        self.run_id = f"{stage}-{self.started.strftime('%Y%m%d%H%M%S')}"
        self.settings = load_settings()

    def path(self, rel: str | Path) -> Path:
        return self.root / rel

    def onto(self, rel: str) -> Path:
        return self.root / "ontology" / rel

    def llm_kwargs(self) -> dict:
        run_dir = self.root / self.settings.run_root / self.run_id
        return {"model": self.settings.gen_model, "run_dir": run_dir}

    def require(self, rel: str) -> Path:
        p = self.onto(rel)
        if not p.exists():
            raise StageError(
                f"{p} がありません。前の段のレビューを済ませて所定の場所に置いてください"
            )
        return p

    def announce(self, calls: int) -> None:
        print(f"[{self.stage}] LLM の呼び出しの予定：{calls} 回（再要求で最大 {calls * 2} 回）")

    def record(self, *, inputs, outputs, pages=(), prompt=None, model=None) -> None:
        prov_path = self.onto("provenance.ttl")
        g = Graph().parse(prov_path) if prov_path.exists() else Graph()
        g, _ = record_activity(
            g,
            run_id=self.run_id,
            stage=self.stage,
            started=self.started,
            ended=datetime.now(UTC),
            inputs=list(inputs),
            pdf_pages=sorted(set(pages)),
            prompt_path=prompt,
            model=model,
            outputs=list(outputs),
        )
        write_turtle(g, prov_path)

    def rows(self):
        p = self.path(ROWS)
        if not p.exists():
            raise StageError(f"{p} がありません。先に extract を流してください")
        return load_rows(p)


def stage_extract(ctx: Ctx, args) -> None:
    rows = extract_rows(ctx.path(PDF))
    save_rows(rows, ctx.path(ROWS))
    print(f"{len(rows)} 行を {ctx.path(ROWS)} に書きました")


def stage_schema(ctx: Ctx, args) -> None:
    rows = ctx.rows()
    ctx.announce(1)
    schema = generate_schema(rows, provider=ctx.provider, **ctx.llm_kwargs())
    out = ctx.onto("generated/schema/schema.ttl")
    write_turtle(schema_dict_to_graph(schema), out)
    report = check_schema_coverage(schema)
    print(f"不足: {report.missing}\n余分: {report.extra}\n推測: {report.speculative}")
    ctx.record(
        inputs=[ctx.path(ROWS)],
        outputs=[out],
        pages=[r.pdf_page for r in rows],
        prompt=prompt_path("schema"),
        model=schema["metadata"].get("model"),
    )


def _schema_text(ctx: Ctx) -> str:
    return schema_summary(Graph().parse(ctx.require("schema.ttl")))


def _saved_outputs(ctx: Ctx, run_id: str) -> dict[str, dict]:
    """保存済みの応答から、業務ごとに最後の（JSON として読める）応答を返す。"""
    run_dir = ctx.root / ctx.settings.run_root / run_id
    if not run_dir.is_dir():
        raise StageError(f"保存済みの実行がありません: {run_dir}")
    found: dict[str, dict] = {}
    for resp in sorted(run_dir.glob("*-response.txt")):
        try:
            out = extract_json(resp.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if isinstance(out, dict) and out.get("business"):
            meta_path = resp.with_name(resp.name.replace("-response.txt", "-meta.json"))
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            found[out["business"]] = {**out, "metadata": {"model": meta.get("model")}}
    return found


def _instances_output(ctx: Ctx, biz: str, biz_rows, schema_text: str, saved) -> dict:
    if saved is None:
        return generate_instances(
            biz, biz_rows, schema_text, list(LAW_SLUGS), provider=ctx.provider, **ctx.llm_kwargs()
        )
    if biz not in saved:
        raise InstanceValidationError([f"保存済みの実行に {biz} の応答がありません"])
    errors = validate_instance_output(saved[biz], biz_rows)
    if errors:
        raise InstanceValidationError(errors)
    return saved[biz]


def stage_instances(ctx: Ctx, args) -> None:
    schema_text = _schema_text(ctx)
    rows = ctx.rows()
    businesses = [args.business] if args.business else list(BUSINESS_SLUGS.values())
    saved = _saved_outputs(ctx, args.from_run) if args.from_run else None
    ctx.announce(0 if saved is not None else len(businesses))
    failed = []
    for biz in businesses:
        biz_rows = rows_for_business(rows, biz)
        try:
            out = _instances_output(ctx, biz, biz_rows, schema_text, saved)
        except InstanceValidationError as e:
            print(f"[{biz}] 検証エラー:\n" + "\n".join(f"  - {x}" for x in e.errors))
            failed.append(biz)
            continue
        g, laws = instances_to_graph(out, biz_rows, activity_iri(ctx.run_id))
        outs = [
            ctx.onto(f"generated/instances/{biz}.ttl"),
            ctx.onto(f"generated/law/laws-{biz}.ttl"),
        ]
        write_turtle(g, outs[0])
        write_turtle(laws, outs[1])
        ctx.record(
            inputs=[ctx.onto("schema.ttl"), ctx.path(ROWS)],
            outputs=outs,
            pages=[r.pdf_page for r in biz_rows],
            prompt=prompt_path("instances"),
            model=out["metadata"].get("model"),
        )
        print(f"[{biz}] {outs[0]} と {outs[1]} を書きました")
    if failed:
        raise StageError(f"検証で止まった業務: {', '.join(failed)}")


def stage_amendments(ctx: Ctx, args) -> None:
    instances = load_ontology(ctx.onto("instances")) if ctx.onto("instances").exists() else Graph()
    if len(instances) == 0:
        raise StageError("ontology/instances/ が空です。インスタンスを固定してから流してください")
    targets = [(a.law, str(a.article)) for t in law_gen.AMENDMENT_TARGETS for a in t.articles]
    get = law_gen.cached_get()
    texts = [
        law_gen.fetch_article(law, art, http_get=get)
        for law, art in [*targets, *law_gen.CHECK_ARTICLES]
    ]
    revisions = law_gen.fetch_revisions("民法", http_get=get)
    refs = [a for t in law_gen.AMENDMENT_TARGETS for a in t.articles]
    candidates = law_gen.treatment_candidates(instances, refs)
    ctx.announce(1)
    draft, model = law_gen.draft_amendments(
        texts, candidates, provider=ctx.provider, **ctx.llm_kwargs()
    )
    raw = ctx.onto("generated/law/amendments.json")
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(json.dumps(draft, ensure_ascii=False, indent=1), encoding="utf-8")
    errors = law_gen.validate_amendments(draft, texts, revisions, candidates)
    if errors:
        raise StageError("改正の下書きの検証エラー:\n" + "\n".join(f"  - {e}" for e in errors))
    out = ctx.onto("generated/law/amendments.ttl")
    write_turtle(law_gen.amendments_to_graph(draft, texts, activity_iri(ctx.run_id)), out)
    print(f"{out} を書きました。候補：{draft.get('candidates')}")
    ctx.record(inputs=[], outputs=[out, raw], prompt=prompt_path("amendments"), model=model)


def _write_checked(ctx: Ctx, ttl: str, out: Path, *, require_rules: bool, **record) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(ttl, encoding="utf-8")
    ctx.record(outputs=[out], **record)
    errors = shapes_gen.check_shapes_text(ttl, require_rules=require_rules)
    if errors:
        raise StageError(f"{out} の検査エラー:\n" + "\n".join(f"  - {e}" for e in errors))
    print(f"{out} を書きました")


def stage_integrity(ctx: Ctx, args) -> None:
    ctx.announce(1)
    ttl, model = shapes_gen.generate_integrity_shapes(
        _schema_text(ctx), provider=ctx.provider, **ctx.llm_kwargs()
    )
    out = ctx.onto("generated/shapes/integrity.ttl")
    _write_checked(
        ctx,
        ttl,
        out,
        require_rules=False,
        inputs=[ctx.onto("schema.ttl")],
        prompt=prompt_path("integrity"),
        model=model,
    )


def stage_rules(ctx: Ctx, args) -> None:
    instances = Graph().parse(ctx.require("instances/birth.ttl"))
    laws = load_ontology(ctx.require("law"))
    ctx.announce(1)
    ttl, model = shapes_gen.generate_rules(
        instances, laws, _schema_text(ctx), provider=ctx.provider, **ctx.llm_kwargs()
    )
    out = ctx.onto("generated/rules/birth-rules.ttl")
    _write_checked(
        ctx,
        ttl,
        out,
        require_rules=True,
        inputs=[ctx.onto("instances/birth.ttl")],
        prompt=prompt_path("rules"),
        model=model,
    )


def stage_derived(ctx: Ctx, args) -> None:
    out = ctx.onto("law/derived.ttl")
    write_turtle(derived_definitions_graph(), out)
    print(f"{out} を書きました")


def stage_approve(ctx: Ctx, args) -> None:
    path = Path(args.file)
    g = Graph().parse(path)
    for sid in args.ids:
        g = law_gen.approve(g, iri_from_short_id(sid), reviewer=args.by, on=date.today())
    write_turtle(g, path)
    print(f"{len(args.ids)} 件を承認しました: {path}")


def stage_validate(ctx: Ctx, args) -> None:
    conforms, text = validate_integrity(ctx.onto(""))
    print(text)
    if not conforms:
        raise StageError("整合性の検証で違反があります")


OUTCOME_JA = {
    "Reject": "受理できない",
    "NeedsCorrection": "補正・追完が要る",
    "NeedsInquiry": "法務局への受理照会が要る",
    "AdditionalProcedure": "受理できるが追加の手続が要る",
    "Info": "参考",
}


def _local(iri) -> str:
    return str(iri).split("#")[-1]


def _trace_lines(f, onto: Graph) -> list[str]:
    from rdflib import RDFS

    lines = [f"- [{_local(f.outcome)}] {short_id(f.rule)}：{f.message}"]
    if f.value is not None:
        lines.append(
            f"    値：{short_id(f.value) if str(f.value).startswith(str(KD)) else f.value}"
        )
    if f.check is not None:
        lines.append(f"    審査項目：{short_id(f.check)}「{onto.value(f.check, RDFS.label)}」")
        for src in sorted(onto.objects(f.check, KOS.hasSource)):
            page, printed = onto.value(src, KOS.pdfPage), onto.value(src, KOS.printedPage)
            quote = onto.value(src, KOS.quote)
            lines.append(f"      出典：手順書 PDF {page} 頁（印刷 {printed} 頁）「{quote}」")
    for v in f.versions:
        status = onto.value(v, KOS.versionStatus)
        lines.append(f"    条文の版：{short_id(v)}（{_local(status) if status else '-'}）")
        for src in sorted(onto.objects(v, KOS.hasSource)):
            lines.append(f"      出典：{onto.value(src, KOS.url)}")
    if f.provisional:
        lines.append("    ※ 未承認の現行版に基づく暫定の指摘")
    return lines


def stage_judge(ctx: Ctx, args) -> None:
    if not args.case:
        raise StageError("judge には --case（出生届の事案の Turtle）が要ります")
    case = Graph().parse(args.case)
    subjects = sorted(set(case.subjects(RDF.type, KOS.BirthFiling)))
    if len(subjects) != 1:
        raise StageError(
            f"事案のファイルには kos:BirthFiling がちょうど 1 つ要ります（{len(subjects)} 個）"
        )
    onto = load_ontology(ctx.onto(""))
    j = judge(case, subjects[0], onto, Graph().parse(ctx.require("rules/birth-rules.ttl")))
    decision = _local(j.decision) if j.decision else None
    print(f"判定：{decision}（{OUTCOME_JA[decision]}）" if decision else "判定：指摘なし（受理可）")
    if j.missing_inputs:
        print(
            "欠けた入力（評価できないルールがある）："
            + "、".join(_local(p) for p in j.missing_inputs)
        )
    if j.provisional_decision:
        print(f"暫定の判定（未承認の現行版に基づく）：{_local(j.provisional_decision)}")
    for f in j.findings:
        print("\n".join(_trace_lines(f, onto)))


STAGES = {
    "extract": stage_extract,
    "schema": stage_schema,
    "instances": stage_instances,
    "amendments": stage_amendments,
    "integrity": stage_integrity,
    "rules": stage_rules,
    "derived": stage_derived,
    "approve": stage_approve,
    "validate": stage_validate,
    "judge": stage_judge,
}


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="semantica_agent.build")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("ids", nargs="*", help="approve で承認するノードの短い ID")
    p.add_argument("--root", default=".")
    p.add_argument("--business", choices=list(BUSINESS_SLUGS.values()))
    p.add_argument("--provider", default=PROVIDER_NAME, help=argparse.SUPPRESS)
    p.add_argument("--from-run", help="instances で、保存済みの実行の応答を使う（LLM を呼ばない）")
    p.add_argument("--case", help="judge で判定する事案の Turtle ファイル")
    p.add_argument("--by", help="approve の確認者")
    p.add_argument("--file", help="approve の対象ファイル")
    return p


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        ctx = Ctx(Path(args.root).resolve(), args.stage, args.provider)
        configure_logging(ctx.settings)
        register_provider()
        if args.stage == "approve" and not (args.by and args.file and args.ids):
            raise StageError("approve には ID と --by と --file が要ります")
        STAGES[args.stage](ctx, args)
    except (StageError, ConfigError, LawFetchError, FileNotFoundError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
