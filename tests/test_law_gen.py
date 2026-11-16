import json
from datetime import date
from pathlib import Path

import pytest
from rdflib import RDF, Graph, Literal

from semantica_agent.ids import ProvisionRef, amendment_iri, article_iri, item_iri, version_iri
from semantica_agent.law_gen import (
    AMENDMENT_TARGETS,
    EGOV_LAW_IDS,
    ArticleText,
    LawFetchError,
    amendments_to_graph,
    approve,
    build_amendments_prompt,
    fetch_article,
    fetch_revisions,
    treatment_candidates,
    validate_amendments,
)
from semantica_agent.namespaces import KD, KOS

FX = Path(__file__).parent / "fixtures"
ACT = KD["activity/t"]


def fixture_get(url):
    if "law_revisions" in url:
        return json.loads((FX / "egov_minpo_revisions.json").read_text(encoding="utf-8"))
    return json.loads((FX / "egov_minpo_excerpt.json").read_text(encoding="utf-8"))


@pytest.fixture
def texts():
    return [
        fetch_article("民法", "733", http_get=fixture_get, today=date(2026, 11, 16)),
        fetch_article("民法", "772", http_get=fixture_get, today=date(2026, 11, 16)),
    ]


@pytest.fixture
def revisions():
    return fetch_revisions("民法", http_get=fixture_get)


@pytest.fixture
def draft():
    return {
        "amendments": [
            {
                "id": "R4-102",
                "law_num": "令和四年法律第百二号",
                "title": "民法等の一部を改正する法律",
                "effective_date": "2024-04-01",
                "provisions": [
                    {
                        "law": "民法",
                        "article": "733",
                        "status": "repealed",
                        "summary_ja": "再婚禁止期間の規定を削除",
                        "quote": "削除",
                    },
                    {
                        "law": "民法",
                        "article": "772",
                        "status": "current",
                        "summary_ja": "婚姻前に懐胎し婚姻後に生まれた子も夫の子と推定",
                        "quote": "婚姻が成立した後に生まれたものも、同様とする",
                    },
                ],
            }
        ],
        "treatments": [
            {
                "item": "MARRIAGE-S2-I4",
                "treatment": "obsolete",
                "amendment": "R4-102",
                "note_ja": "2024年4月1日に再婚禁止期間が廃止された。",
            }
        ],
        "period_rules": [],
        "candidates": [{"title": "押印義務の廃止", "reason": "証人の押印"}],
    }


CANDIDATES = {"MARRIAGE-S2-I4": "女性は待婚期間ではないか。"}


def test_law_ids():
    assert EGOV_LAW_IDS["民法"] == "129AC0000000089"
    assert EGOV_LAW_IDS["戸籍法"] == "322AC0000000224"


def test_amendment_targets_cover_spec():
    ids = {t.id for t in AMENDMENT_TARGETS}
    assert ids == {"H30-59", "R4-102", "R6-33"}


def test_fetch_article_parses_fixture(texts):
    a733, a772 = texts
    assert a733.text.endswith("削除") and a733.url.startswith("https://laws.e-gov.go.jp/")
    assert "嫡出の推定" in a772.text and a772.revision_id.startswith("129AC0000000089_")
    assert a772.fetched == date(2026, 11, 16)


def test_fetch_article_missing_article():
    with pytest.raises(LawFetchError, match="999"):
        fetch_article("民法", "999", http_get=fixture_get)


def test_fetch_article_rejects_unexpected_shape():
    with pytest.raises(LawFetchError):
        fetch_article("民法", "733", http_get=lambda url: {"unexpected": 1})


def test_fetch_revisions(revisions):
    assert any(
        r.law_num == "令和四年法律第百二号" and r.enforcement == date(2024, 4, 1) for r in revisions
    )


def test_valid_draft_has_no_errors(draft, texts, revisions):
    assert validate_amendments(draft, texts, revisions, CANDIDATES) == []


def test_wrong_date_is_error(draft, texts, revisions):
    draft["amendments"][0]["effective_date"] = "2024-05-01"
    assert any("改正履歴" in e for e in validate_amendments(draft, texts, revisions, CANDIDATES))


def test_quote_not_in_text_is_error(draft, texts, revisions):
    draft["amendments"][0]["provisions"][1]["quote"] = "存在しない文"
    assert any("quote" in e for e in validate_amendments(draft, texts, revisions, CANDIDATES))


def test_treatment_for_unknown_item_is_error(draft, texts, revisions):
    draft["treatments"][0]["item"] = "BIRTH-S9-I9"
    assert any("BIRTH-S9-I9" in e for e in validate_amendments(draft, texts, revisions, CANDIDATES))


def test_treatment_candidates_follow_citations():
    g = Graph()
    item = item_iri("marriage", 2, (4,))
    para = KD["law/minpo/art/733"]
    g.add((item, RDF.type, KOS.ReviewCheck))
    g.add((item, KOS.citesProvision, para))
    from rdflib import RDFS

    g.add((item, RDFS.label, Literal("女性は待婚期間ではないか。", lang="ja")))
    cands = treatment_candidates(g, [ProvisionRef("民法", 733)])
    assert cands == {"MARRIAGE-S2-I4": "女性は待婚期間ではないか。"}


def test_prompt_contains_texts_and_candidates(texts):
    p = build_amendments_prompt(texts, CANDIDATES)
    assert "削除" in p and "MARRIAGE-S2-I4" in p and "R4-102" in p


def test_amendments_graph_marks_draft_and_source(draft, texts):
    g = amendments_to_graph(draft, texts, ACT)
    art = article_iri(ProvisionRef("民法", 733))
    v = version_iri(art, "2024-04-01")
    am = amendment_iri("R", 4, 102)
    assert (am, RDF.type, KOS.LegalAmendment) in g
    assert (am, KOS.amends, art) in g and (am, KOS.producesVersion, v) in g
    assert g.value(v, KOS.versionStatus) == KOS.Repealed
    assert g.value(v, KOS.reviewStatus) == KOS.LlmDraft
    assert str(g.value(v, KOS.validFrom)) == "2024-04-01"
    src = g.value(v, KOS.hasSource)
    assert g.value(src, KOS.sourceKind) == KOS.CurrentLawSource
    assert str(g.value(src, KOS.url)).startswith("https://laws.e-gov.go.jp/")
    assert str(g.value(version_iri(art, "manual"), KOS.validUntil)) == "2024-04-01"
    item = item_iri("marriage", 2, (4,))
    assert g.value(item, KOS.currentTreatment) == KOS.Obsolete


def test_approve_returns_new_graph(draft, texts):
    g = amendments_to_graph(draft, texts, ACT)
    v = version_iri(article_iri(ProvisionRef("民法", 733)), "2024-04-01")
    g2 = approve(g, v, reviewer="reviewer", on=date(2026, 11, 20))
    assert g.value(v, KOS.reviewStatus) == KOS.LlmDraft
    assert g2.value(v, KOS.reviewStatus) == KOS.HumanReviewed
    src = g2.value(v, KOS.hasSource)
    assert str(g2.value(src, KOS.reviewer)) == "reviewer"
    assert str(g2.value(src, KOS.reviewedDate)) == "2026-11-20"


def test_approve_unknown_node_fails(draft, texts):
    g = amendments_to_graph(draft, texts, ACT)
    with pytest.raises(KeyError):
        approve(g, KD["nothing"], reviewer="r", on=date(2026, 11, 20))


def test_article_text_is_frozen():
    a = ArticleText("民法", "733", "削除", "https://laws.e-gov.go.jp/law/x", date(2026, 1, 1), "r")
    with pytest.raises(AttributeError):
        a.text = "x"
