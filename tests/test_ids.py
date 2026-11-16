import pytest

from semantica_agent.ids import (
    ProvisionRef,
    amendment_iri,
    article_iri,
    business_iri,
    derived_iri,
    egov_source_iri,
    iri_from_short_id,
    item_iri,
    manual_source_iri,
    provision_iri,
    rule_iri,
    short_id,
    step_iri,
    version_iri,
    vocab_iri,
)
from semantica_agent.namespaces import KD


def test_business_and_step_iri():
    assert business_iri("birth") == KD["birth"]
    assert step_iri("birth", 2) == KD["birth/step/2"]


def test_item_iri_matches_spec():
    assert item_iri("birth", 1, (1, 2)) == KD["birth/step/1/item/1.2"]


def test_provision_iri_with_branch_and_paragraph():
    ref = ProvisionRef("戸籍法", 27, branch=2, paragraph=1)
    assert provision_iri(ref) == KD["law/koseki-ho/art/27-2/para/1"]
    assert article_iri(ref) == KD["law/koseki-ho/art/27-2"]


def test_provision_iri_with_item():
    ref = ProvisionRef("戸籍法施行規則", 11, branch=2, item=4)
    assert provision_iri(ref) == KD["law/koseki-ho-kisoku/art/11-2/item/4"]


def test_unknown_law_is_rejected():
    with pytest.raises(KeyError, match="未知の法令"):
        provision_iri(ProvisionRef("未知法", 1))


def test_version_and_amendment_iri():
    p = provision_iri(ProvisionRef("民法", 772))
    assert version_iri(p, "2024-04-01") == KD["law/minpo/art/772/version/2024-04-01"]
    assert version_iri(p, "manual") == KD["law/minpo/art/772/version/manual"]
    assert amendment_iri("R", 4, 102) == KD["amendment/R4-102"]


def test_version_label_is_validated():
    with pytest.raises(ValueError):
        version_iri(KD["law/minpo/art/772"], "2024/04/01")


def test_other_iris():
    assert manual_source_iri("p3-r14") == KD["source/manual/p3-r14"]
    assert egov_source_iri("minpo-733") == KD["source/egov/minpo-733"]
    assert rule_iri("birth", "legitimacy-current") == KD["rule/birth/legitimacy-current"]
    assert derived_iri("days-late") == KD["derived/days-late"]
    assert vocab_iri("document", "birth-certificate") == KD["document/birth-certificate"]


@pytest.mark.parametrize(
    "iri,sid",
    [
        (KD["birth"], "BIRTH"),
        (KD["birth/step/2"], "BIRTH-S2"),
        (KD["birth/step/2/item/5"], "BIRTH-S2-I5"),
        (KD["birth/step/1/item/1.2"], "BIRTH-S1-I1.2"),
        (KD["law/minpo"], "LAW-MINPO"),
        (KD["law/minpo/art/772"], "LAW-MINPO-772"),
        (KD["law/koseki-ho/art/27-2/para/1"], "LAW-KOSEKI-HO-27-2-P1"),
        (KD["law/koseki-ho-kisoku/art/11-2/item/4"], "LAW-KOSEKI-HO-KISOKU-11-2-I4"),
        (KD["law/minpo/art/772/version/2024-04-01"], "LAW-MINPO-772-V20240401"),
        (KD["law/minpo/art/733/version/manual"], "LAW-MINPO-733-VMANUAL"),
        (KD["amendment/R4-102"], "AMENDMENT-R4-102"),
        (KD["rule/birth/legitimacy-current"], "RULE-BIRTH-LEGITIMACY-CURRENT"),
        (KD["source/manual/p3-r14"], "SRC-P3-R14"),
        (KD["source/egov/minpo-733"], "SRC-EGOV-MINPO-733"),
        (KD["derived/days-late"], "DERIVED-DAYS-LATE"),
        (KD["document/birth-certificate"], "DOCUMENT-BIRTH-CERTIFICATE"),
        (KD["record-item/birth-place"], "RECORD-ITEM-BIRTH-PLACE"),
        (KD["activity/schema-20261116120000"], "ACTIVITY-SCHEMA-20261116120000"),
    ],
)
def test_short_id_round_trip(iri, sid):
    assert short_id(iri) == sid
    assert iri_from_short_id(sid) == iri


def test_short_id_rejects_foreign_iri():
    with pytest.raises(ValueError):
        short_id(KD["unknown-kind/x/y/z"])
