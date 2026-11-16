"""現行法の取得（e-Gov 法令 API v2）、改正と現行版の下書き、承認。仕様 §5.5・§6。"""

import json
import logging
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from string import Template

from rdflib import RDF, RDFS, Graph, Literal, URIRef
from rdflib.namespace import DCTERMS, PROV, XSD
from semantica.semantic_extract.providers import create_provider

from semantica_agent.ids import (
    ProvisionRef,
    amendment_iri,
    article_iri,
    derived_iri,
    egov_source_iri,
    iri_from_short_id,
    short_id,
    version_iri,
)
from semantica_agent.llm_provider import PROVIDER_NAME
from semantica_agent.namespaces import KOS, bind_prefixes
from semantica_agent.schema_gen import prompt_path
from semantica_agent.vocab import LAW_SLUGS

logger = logging.getLogger(__name__)

EGOV_API = "https://laws.e-gov.go.jp/api/2"
EGOV_LAW_PAGE = "https://laws.e-gov.go.jp/law/"
HTTP_TIMEOUT = 60
EGOV_LAW_IDS: dict[str, str] = {
    "民法": "129AC0000000089",
    "戸籍法": "322AC0000000224",
    "戸籍法施行規則": "322M40000010094",
    "学校教育法": "322AC0000000026",
    "地方自治法": "322AC0000000067",
}
TREATMENTS = {"valid": KOS.Valid, "changed": KOS.Changed, "obsolete": KOS.Obsolete}
STATUSES = {"current": KOS.Current, "repealed": KOS.Repealed}

HttpGet = Callable[[str], dict]


class LawFetchError(RuntimeError):
    pass


@dataclass(frozen=True)
class ArticleText:
    law: str
    article: str
    text: str
    url: str
    fetched: date
    revision_id: str


@dataclass(frozen=True)
class Revision:
    law: str
    law_num: str
    title: str
    enforcement: date
    revision_id: str


@dataclass(frozen=True)
class AmendmentTarget:
    id: str
    law_num: str
    title: str
    effective: date
    articles: tuple[ProvisionRef, ...]


AMENDMENT_TARGETS: tuple[AmendmentTarget, ...] = (
    AmendmentTarget(
        "H30-59",
        "平成三十年法律第五十九号",
        "成年年齢の引き下げ",
        date(2022, 4, 1),
        (ProvisionRef("民法", 731), ProvisionRef("民法", 737)),
    ),
    AmendmentTarget(
        "R4-102",
        "令和四年法律第百二号",
        "嫡出推定・再婚禁止期間の見直し",
        date(2024, 4, 1),
        (ProvisionRef("民法", 772), ProvisionRef("民法", 733)),
    ),
    AmendmentTarget(
        "R6-33",
        "令和六年法律第三十三号",
        "離婚後の共同親権の導入",
        date(2026, 4, 1),
        (ProvisionRef("民法", 819), ProvisionRef("民法", 765)),
    ),
)
# 判定ルールの確認に要る条文（仕様 §6.4）
CHECK_ARTICLES: tuple[tuple[str, str], ...] = (
    ("戸籍法", "25"),
    ("戸籍法", "43"),
    ("戸籍法", "49"),
    ("戸籍法", "51"),
    ("戸籍法", "52"),
    ("学校教育法", "17"),
    ("地方自治法", "4-2"),
)


def _default_get(url: str) -> dict:
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as res:  # noqa: S310
            return json.loads(res.read().decode("utf-8"))
    except Exception as e:
        raise LawFetchError(f"e-Gov から取得できません: {url}: {e}") from e


def _law_id(law: str) -> str:
    if law not in EGOV_LAW_IDS:
        raise LawFetchError(f"e-Gov の法令 ID が未登録です（EGOV_LAW_IDS に足してください）: {law}")
    return EGOV_LAW_IDS[law]


def _find_article(node, num: str):
    if not isinstance(node, dict) or node.get("tag") == "SupplProvision":
        return None
    if node.get("tag") == "Article" and node.get("attr", {}).get("Num") == num:
        return node
    for child in node.get("children", []):
        found = _find_article(child, num)
        if found is not None:
            return found
    return None


def _text(node) -> str:
    if isinstance(node, str):
        return node
    return "".join(_text(c) for c in node.get("children", []))


def fetch_article(
    law: str, article: str, *, http_get: HttpGet | None = None, today: date | None = None
) -> ArticleText:
    law_id = _law_id(law)
    url = f"{EGOV_API}/law_data/{law_id}?response_format=json&law_full_text_format=json"
    data = (http_get or _default_get)(url)
    try:
        revision_id = data["revision_info"]["law_revision_id"]
        root = data["law_full_text"]
    except (KeyError, TypeError) as e:
        raise LawFetchError(f"e-Gov の応答の形が想定と違います（{law}）: {e}") from e
    node = _find_article(root, article.replace("-", "_"))
    if node is None:
        raise LawFetchError(f"{law}第{article}条が e-Gov の条文に見つかりません")
    return ArticleText(
        law, article, _text(node), EGOV_LAW_PAGE + law_id, today or date.today(), revision_id
    )


def fetch_revisions(law: str, *, http_get: HttpGet | None = None) -> list[Revision]:
    data = (http_get or _default_get)(
        f"{EGOV_API}/law_revisions/{_law_id(law)}?response_format=json"
    )
    try:
        return [
            Revision(
                law,
                r["amendment_law_num"] or "",
                r["amendment_law_title"] or "",
                date.fromisoformat(r["amendment_enforcement_date"]),
                r["law_revision_id"],
            )
            for r in data["revisions"]
            if r.get("amendment_enforcement_date")
        ]
    except (KeyError, TypeError, ValueError) as e:
        raise LawFetchError(f"e-Gov の改正履歴の形が想定と違います（{law}）: {e}") from e


def treatment_candidates(instances: Graph, refs: list[ProvisionRef]) -> dict[str, str]:
    prefixes = [str(article_iri(r)) for r in refs]
    out: dict[str, str] = {}
    for item, prov in instances.subject_objects(KOS.citesProvision):
        p = str(prov)
        if any(p == x or p.startswith(x + "/") for x in prefixes):
            out[short_id(item)] = str(instances.value(item, RDFS.label) or "")
    return dict(sorted(out.items()))


def build_amendments_prompt(texts: list[ArticleText], candidates: dict[str, str]) -> str:
    targets = "\n".join(
        f"- {t.id}：{t.law_num}（{t.title}）施行 {t.effective.isoformat()}、"
        + "、".join(f"{a.law}第{a.article}条" for a in t.articles)
        for t in AMENDMENT_TARGETS
    )
    articles = "\n\n".join(f"### {a.law}第{a.article}条（現行）\n{a.text}" for a in texts)
    cands = "\n".join(f"- {k}：{v}" for k, v in candidates.items()) or "（なし）"
    return Template(prompt_path("amendments").read_text(encoding="utf-8")).substitute(
        targets=targets, articles=articles, candidates=cands
    )


def draft_amendments(
    texts: list[ArticleText], candidates: dict[str, str], provider: str = PROVIDER_NAME, **kw
) -> tuple[dict, str | None]:
    llm = create_provider(provider, **kw)
    out = llm.generate_structured(build_amendments_prompt(texts, candidates))
    if not isinstance(out, dict):
        raise LawFetchError(f"下書きの JSON の最上位がオブジェクトではありません: {type(out)}")
    return out, getattr(llm, "last_model", None)


def _texts_by_key(texts: list[ArticleText]) -> dict[tuple[str, str], ArticleText]:
    return {(t.law, t.article): t for t in texts}


def validate_amendments(
    draft: dict, texts: list[ArticleText], revisions: list[Revision], candidates: dict[str, str]
) -> list[str]:
    errors: list[str] = []
    by_key = _texts_by_key(texts)
    known = {(r.law_num, r.enforcement) for r in revisions}
    ids = {t.id for t in AMENDMENT_TARGETS}

    def check_quote(where: str, law: str, article: str, quote: str | None) -> None:
        t = by_key.get((law, str(article)))
        if t is None:
            errors.append(f"{where}: {law}第{article}条の条文を取得していません")
        elif not quote or quote not in t.text:
            errors.append(f"{where}: quote が{law}第{article}条の現行の条文にありません: {quote!r}")

    for am in draft.get("amendments") or []:
        where = f"改正 {am.get('id')}"
        if am.get("id") not in ids:
            errors.append(f"{where}: 対象の改正ではありません")
        try:
            eff = date.fromisoformat(am.get("effective_date") or "")
        except ValueError:
            eff = None
        if (am.get("law_num"), eff) not in known:
            errors.append(f"{where}: 法律番号・施行日が e-Gov の改正履歴にありません")
        for p in am.get("provisions") or []:
            if p.get("status") not in STATUSES:
                errors.append(f"{where}: status は {tuple(STATUSES)} のいずれか")
            check_quote(where, p.get("law"), p.get("article"), p.get("quote"))
    for t in draft.get("treatments") or []:
        if t.get("item") not in candidates:
            errors.append(f"扱い: {t.get('item')} は候補の審査項目にありません")
        if t.get("treatment") not in TREATMENTS or t.get("amendment") not in ids:
            errors.append(f"扱い: {t.get('item')} の treatment か amendment が不正です")
    for r in draft.get("period_rules") or []:
        check_quote(f"期間 {r.get('slug')}", r.get("law"), r.get("article"), r.get("quote"))
        if not isinstance(r.get("period_days"), int) or r["period_days"] <= 0:
            errors.append(f"期間 {r.get('slug')}: period_days は正の整数")
    return errors


class _AmendmentBuilder:
    def __init__(self, texts: list[ArticleText], activity: URIRef):
        self.by_key = _texts_by_key(texts)
        self.act = activity
        self.g = bind_prefixes(Graph())

    def node(self, iri: URIRef, cls: URIRef, label: str | None = None) -> URIRef:
        self.g.add((iri, RDF.type, cls))
        self.g.add((iri, DCTERMS.identifier, Literal(short_id(iri))))
        self.g.add((iri, KOS.reviewStatus, KOS.LlmDraft))
        self.g.add((iri, PROV.wasGeneratedBy, self.act))
        if label:
            self.g.add((iri, RDFS.label, Literal(label, lang="ja")))
        return iri

    def source(self, subject: URIRef, law: str, article: str, quote: str) -> None:
        t = self.by_key[(law, article)]
        src = egov_source_iri(f"{LAW_SLUGS[law]}-{article}")
        if (src, RDF.type, KOS.SourceReference) not in self.g:
            self.node(src, KOS.SourceReference, f"e-Gov {law}第{article}条")
            self.g.add((src, KOS.sourceKind, KOS.CurrentLawSource))
            self.g.add((src, KOS.url, Literal(t.url, datatype=XSD.anyURI)))
            self.g.add((src, KOS.fetchedDate, Literal(t.fetched)))
            self.g.add((src, KOS.revisionId, Literal(t.revision_id)))
        self.g.add((src, KOS.quote, Literal(quote, lang="ja")))
        self.g.add((subject, KOS.hasSource, src))

    def amendment(self, am: dict) -> None:
        era, rest = am["id"][0], am["id"][1:]
        year, num = (int(x) for x in rest.split("-"))
        eff = date.fromisoformat(am["effective_date"])
        a = self.node(amendment_iri(era, year, num), KOS.LegalAmendment, am.get("title"))
        self.g.add((a, KOS.lawNumber, Literal(am["law_num"])))
        self.g.add((a, KOS.effectiveDate, Literal(eff)))
        for p in am["provisions"]:
            ref = ProvisionRef(p["law"], int(p["article"].split("-")[0]))
            art = article_iri(ref)
            v = self.node(version_iri(art, eff.isoformat()), KOS.ProvisionVersion)
            self.g.add((v, KOS.versionStatus, STATUSES[p["status"]]))
            self.g.add((v, KOS.validFrom, Literal(eff)))
            self.g.add((v, KOS.summary, Literal(p["summary_ja"], lang="ja")))
            self.g.add((art, KOS.hasVersion, v))
            manual = version_iri(art, "manual")
            self.g.add((art, KOS.hasVersion, manual))
            self.g.add((manual, RDF.type, KOS.ProvisionVersion))
            self.g.add((manual, KOS.versionStatus, KOS.Manual))
            self.g.add((manual, KOS.validUntil, Literal(eff)))
            self.g.add((a, KOS.amends, art))
            self.g.add((a, KOS.producesVersion, v))
            for n in (v, a):
                self.source(n, p["law"], p["article"], p["quote"])

    def build(self, draft: dict) -> Graph:
        for am in draft.get("amendments") or []:
            self.amendment(am)
        for t in draft.get("treatments") or []:
            item = iri_from_short_id(t["item"])
            self.g.add((item, KOS.currentTreatment, TREATMENTS[t["treatment"]]))
            self.g.add((item, KOS.currentTreatmentNote, Literal(t["note_ja"], lang="ja")))
        for r in draft.get("period_rules") or []:
            d = self.node(derived_iri(r["slug"]), KOS.DerivedValue, r.get("label_ja"))
            self.g.add((d, KOS.periodDays, Literal(r["period_days"])))
            self.g.add((d, KOS.countFirstDay, Literal(bool(r.get("count_first_day")))))
            self.g.add((d, KOS.extendOnHoliday, Literal(bool(r.get("extend_on_holiday")))))
            ref = ProvisionRef(r["law"], int(r["article"].split("-")[0]))
            self.g.add((d, KOS.citesProvision, article_iri(ref)))
            self.source(d, r["law"], r["article"], r["quote"])
        return self.g


def amendments_to_graph(draft: dict, texts: list[ArticleText], activity: URIRef) -> Graph:
    return _AmendmentBuilder(texts, activity).build(draft)


def approve(g: Graph, node: URIRef, reviewer: str, on: date) -> Graph:
    if (node, KOS.reviewStatus, None) not in g:
        raise KeyError(f"承認するノードがありません: {node}")
    new = bind_prefixes(Graph())
    for t in g:
        new.add(t)
    new.remove((node, KOS.reviewStatus, None))
    new.add((node, KOS.reviewStatus, KOS.HumanReviewed))
    for src in g.objects(node, KOS.hasSource):
        new.add((src, KOS.reviewer, Literal(reviewer)))
        new.add((src, KOS.reviewedDate, Literal(on)))
    return new


def cached_get(http_get: HttpGet | None = None) -> HttpGet:
    """同じ URL を 1 回だけ取得する（法令の全文を条文ごとに取り直さないため）。"""
    cache: dict[str, dict] = {}
    base = http_get or _default_get

    def get(url: str) -> dict:
        if url not in cache:
            cache[url] = base(url)
        return cache[url]

    return get
