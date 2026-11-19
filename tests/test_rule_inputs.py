from datetime import date

import pytest
from rdflib import Graph

from semantica_agent.core.ids import short_id
from semantica_agent.core.namespaces import KD
from semantica_agent.review.rule_inputs import applicable_rules, rule_inputs

LEGIT = {"childBirthDate", "parentsMarriageDate", "motherPrevMarriageEndDate"}
EXPECTED = {
    "RULE-BIRTH-FILING-PERIOD": {"childBirthDate", "filingDate"},
    "RULE-BIRTH-MOTHER-AGE": {"motherBirthDate", "childBirthDate"},
    "RULE-BIRTH-SCHOOL-AGE": {"childBirthDate", "filingDate"},
    "RULE-BIRTH-FAMILY-REGISTER": {"familyRegisterExists"},
    "RULE-BIRTH-ADDRESS": {"addressExists"},
    "RULE-BIRTH-BIRTH-CERTIFICATE": {"attachedDocument", "childBirthDate"},
    "RULE-BIRTH-BIRTH-RECORD-MATCH": {
        "childBirthDate", "certBirthDate", "childBirthTime", "certBirthTime",
        "birthPlaceMunicipality", "certBirthPlace",
    },
    "RULE-BIRTH-FILING-PLACE": {
        "filingMunicipality", "honsekiMunicipality", "notifierMunicipality",
        "birthPlaceMunicipality", "childBirthDate",
    },
    "RULE-BIRTH-LEGITIMACY-CURRENT": LEGIT
    | {"statedRelationship", "motherRemarriedBeforeBirth", "statedFather"},
    "RULE-BIRTH-LEGITIMACY-MANUAL": LEGIT | {"statedRelationship"},
    "RULE-BIRTH-LEGITIMACY-DIFF": LEGIT | {"motherRemarriedBeforeBirth"},
    "RULE-BIRTH-NON-HONSEKI": {"filingMunicipality", "honsekiMunicipality"},
    "RULE-BIRTH-NOTIFIER": {
        "notifierRole", "statedRelationship", "childBirthDate", "parentsMarriageDate",
    },
    "RULE-BIRTH-RECORD-ITEMS": {"recordedItem"},
}  # fmt: skip


def test_rule_inputs_real_rules(rules):
    got = {short_id(r): set(v) for r, v in rule_inputs(rules).items()}
    assert got == EXPECTED


def test_rule_inputs_reads_property_path_and_derived():
    g = Graph().parse(
        data="""
        @prefix kos: <https://semantica-agent.example/koseki/schema#> .
        @prefix sh: <http://www.w3.org/ns/shacl#> .
        <https://semantica-agent.example/koseki/id/rule/birth/x> a kos:JudgmentRule ;
            kos:shape <https://semantica-agent.example/koseki/id/shape/x> .
        <https://semantica-agent.example/koseki/id/shape/x> a sh:NodeShape ;
            sh:property [ sh:path kos:daysLate ; sh:maxInclusive 0 ] .
        """,
        format="turtle",
    )
    assert rule_inputs(g)[KD["rule/birth/x"]] == {"childBirthDate", "filingDate"}


@pytest.mark.parametrize(
    "birth,manual,current", [(date(2024, 3, 31), True, False), (date(2024, 4, 1), False, True)]
)
def test_applicable_rules_boundary(rules, onto, birth, manual, current):
    a = applicable_rules(rules, onto, birth)
    assert (KD["rule/birth/legitimacy-manual"] in a) == manual
    assert (KD["rule/birth/legitimacy-current"] in a) == current
    assert KD["rule/birth/filing-period"] in a
    assert KD["rule/birth/legitimacy-diff"] in a


def test_no_birth_date_keeps_all_rules(rules, onto):
    # 出生日が分からなければ版を選べないので、どのルールも外さない（評価できずは assess で決める）
    a = applicable_rules(rules, onto, None)
    assert KD["rule/birth/filing-place"] in a and KD["rule/birth/legitimacy-current"] in a
