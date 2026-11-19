import pytest
from rdflib import Graph
from test_birth_rules import build_case

from semantica_agent.core.namespaces import KCASE, KOS
from semantica_agent.review.case_input import (
    CASE_FIELDS,
    CaseInputError,
    case_graph,
    check_quotes,
    input_schema,
    parse_case_input,
)

BIRTH = {"status": "given", "value": "2024-04-01", "quote": "4月1日生まれ"}
VOCAB_PREFIX = {
    "notifierRole": "ROLE",
    "attachedDocument": "DOCUMENT",
    "recordedItem": "RECORD-ITEM",
}


def base_args(base: dict) -> dict:
    """cases.json の base を、すべて given（一覧は complete）のツール入力にする。"""
    args = {}
    for key, value in base.items():
        if key in ("attachedDocument", "recordedItem"):
            items = [f"{VOCAB_PREFIX[key]}-{v.upper()}" for v in value]
            args[key] = {"status": "given", "items": items, "complete": True, "quote": "q"}
        elif key == "notifierRole":
            args[key] = {"status": "given", "value": f"ROLE-{value.upper()}", "quote": "q"}
        else:
            args[key] = {"status": "given", "value": value, "quote": "q"}
    return args


def test_case_fields_cover_spec():
    names = {f.name for f in CASE_FIELDS}
    assert {"childBirthDate", "attachedDocument", "motherRemarriedBeforeBirth"} <= names
    assert len(names) == len(CASE_FIELDS)


def test_omitted_field_is_unknown(onto):
    c = parse_case_input({"childBirthDate": BIRTH}, onto)
    assert "motherBirthDate" in c.unknown_fields
    assert "childBirthDate" not in c.unknown_fields


def test_none_and_unknown_make_no_triples(onto):
    args = {"motherPrevMarriageEndDate": {"status": "none", "quote": "前婚はない"}}
    c = parse_case_input(args, onto)
    g = case_graph(c, KCASE.t1)
    assert (KCASE.t1, KOS.motherPrevMarriageEndDate, None) not in g
    assert "motherPrevMarriageEndDate" not in c.unknown_fields


def test_list_complete_flag(onto):
    doc = {"status": "given", "items": ["DOCUMENT-BIRTH-CERTIFICATE"], "complete": False}
    c = parse_case_input({"attachedDocument": {**doc, "quote": "出生証明書あり"}}, onto)
    assert "attachedDocument" not in c.complete_lists
    assert "attachedDocument" not in c.unknown_fields


def test_empty_incomplete_list_is_unknown(onto):
    doc = {"status": "given", "items": [], "complete": False, "quote": "x"}
    assert "attachedDocument" in parse_case_input({"attachedDocument": doc}, onto).unknown_fields


def test_enum_rejected(onto):
    with pytest.raises(CaseInputError, match="notifierRole"):
        parse_case_input(
            {"notifierRole": {"status": "given", "value": "ROLE-UNKNOWN", "quote": "x"}}, onto
        )


@pytest.mark.parametrize(
    "arg",
    [
        {"status": "given", "quote": "x"},
        {"status": "given", "value": "2024-04-01"},
        {"status": "none"},
        {"status": "given", "value": "4月1日", "quote": "x"},
        {"status": "maybe"},
    ],
)
def test_invalid_field_rejected(onto, arg):
    with pytest.raises(CaseInputError, match="childBirthDate"):
        parse_case_input({"childBirthDate": arg}, onto)


def test_unknown_field_name_rejected(onto):
    with pytest.raises(CaseInputError, match="nosuch"):
        parse_case_input({"nosuch": BIRTH}, onto)


@pytest.mark.parametrize(
    "utterances,bad",
    [
        (["4月 1日　生まれ"], []),
        (["前の話", "4月1日生まれです"], []),
        (["5月生まれ"], ["childBirthDate"]),
    ],
)
def test_quote_check(onto, utterances, bad):
    c = parse_case_input({"childBirthDate": BIRTH}, onto)
    assert check_quotes(c, utterances) == bad


def test_input_schema_lists_enums(onto):
    s = input_schema(onto)
    role = s["properties"]["notifierRole"]
    assert "ROLE-FATHER" in str(role)
    assert "DOCUMENT-BIRTH-CERTIFICATE" in str(s["properties"]["attachedDocument"])


def test_case_graph_matches_fixture_base(onto, birth_cases):
    c = parse_case_input(base_args(birth_cases["base"]), onto)
    expected = build_case({})
    got = case_graph(c, KCASE.c1)
    assert set(got) == set(expected)
    assert isinstance(got, Graph)


def test_blank_quote_rejected(onto):
    with pytest.raises(CaseInputError, match="childBirthDate"):
        parse_case_input({"childBirthDate": {**BIRTH, "quote": "  　"}}, onto)
