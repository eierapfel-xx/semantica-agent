from semantica_agent.ids import ProvisionRef as P
from semantica_agent.lawref import normalize, parse_provisions, provision_appears_in


def test_parse_single():
    assert parse_provisions("戸籍法第25条") == [P("戸籍法", 25)]


def test_parse_inherits_law_name():
    assert parse_provisions("戸籍法施行規則第53条、第53条の2、第11条の2") == [
        P("戸籍法施行規則", 53),
        P("戸籍法施行規則", 53, branch=2),
        P("戸籍法施行規則", 11, branch=2),
    ]


def test_parse_expands_paragraph_range():
    assert parse_provisions("戸籍法第10条の2第３項～第5項") == [
        P("戸籍法", 10, 2, p) for p in (3, 4, 5)
    ]


def test_parse_paragraph_list():
    assert parse_provisions("戸籍法第52条第1項、第2項") == [
        P("戸籍法", 52, paragraph=1),
        P("戸籍法", 52, paragraph=2),
    ]


def test_parse_alias_and_fullwidth():
    assert parse_provisions("住基法第9条第２項") == [P("住民基本台帳法", 9, paragraph=2)]


def test_parse_typo_branch():
    assert parse_provisions("戸籍法第27条2第1項") == [P("戸籍法", 27, 2, 1)]


def test_parse_paragraph_without_dai():
    assert parse_provisions("民法第790条1項、戸籍法第62条") == [
        P("民法", 790, paragraph=1),
        P("戸籍法", 62),
    ]


def test_parse_law_name_with_comma():
    assert parse_provisions("墓地、埋葬等に関する法律第5条") == [P("墓地、埋葬等に関する法律", 5)]


def test_parse_without_dai():
    assert parse_provisions("民法第764条、739条") == [P("民法", 764), P("民法", 739)]


def test_parse_item_and_skip_appendix():
    assert parse_provisions("戸籍法施行規則第11条の2第4号") == [P("戸籍法施行規則", 11, 2, item=4)]
    assert parse_provisions("戸籍法施行規則第12条、第14条、附録第15号書式") == [
        P("戸籍法施行規則", 12),
        P("戸籍法施行規則", 14),
    ]


def test_parse_ignores_text_without_articles():
    assert parse_provisions("戸籍法、戸籍法施行規則に定められた記載事項。法務省HP2") == []


def test_parse_joined_line_breaks():
    assert parse_provisions("戸籍法第29条、第49条、戸籍 法施行規則第55条") == [
        P("戸籍法", 29),
        P("戸籍法", 49),
        P("戸籍法施行規則", 55),
    ]


def test_normalize():
    assert normalize("第１１条 の２") == "第11条の2"


def test_appears_in():
    assert provision_appears_in(P("戸籍法", 52, paragraph=2), "戸籍法第52条第1項、第2項")
    assert provision_appears_in(P("戸籍法", 52), "戸籍法第52条第1項、第2項")
    assert not provision_appears_in(P("戸籍法", 53), "戸籍法第52条第1項")
    assert not provision_appears_in(P("戸籍法", 52, paragraph=3), "戸籍法第52条第1項")
