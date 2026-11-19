import re
from pathlib import Path

import pytest

from semantica_agent.build.extract import (
    ColumnBounds,
    Row,
    assign_columns,
    extract_rows,
    group_lines,
    load_rows,
    rows_for_business,
    save_rows,
)

PDF = Path(__file__).resolve().parents[1] / "docs" / "domain" / "手順書.pdf"


def w(text, x, top=100.0):
    return {"text": text, "x0": float(x), "top": float(top)}


def test_assign_columns_splits_procedure_and_remarks():
    words = [
        w("②", 60 + 80),
        w("出生届と出生証明書の記載事項と合致しているか確認す", 153),
        w("用意する。（戸籍法第29条", 408),
    ]
    assert assign_columns(words, ColumnBounds(division_end=128, procedure_end=404)) == (
        "",
        "② 出生届と出生証明書の記載事項と合致しているか確認す",
        "用意する。（戸籍法第29条",
    )


def test_assign_columns_keeps_division():
    words = [w("3.", 62), w("システム", 80), w("戸籍情報システムへの登録", 132)]
    assert assign_columns(words, ColumnBounds(128, 404))[0] == "3. システム"


def test_group_lines_tolerates_small_offsets():
    words = [w("a", 132, 256), w("b", 408, 257.5), w("c", 132, 271)]
    lines = group_lines(words)
    assert [[x["text"] for x in line] for line in lines] == [["a", "b"], ["c"]]


def test_save_and_load_round_trip(tmp_path):
    rows = [Row("p2-r1", "table", "birth", "1.受付", "★…", "", 2, 1, 197.0)]
    save_rows(rows, tmp_path / "rows.json")
    assert load_rows(tmp_path / "rows.json") == rows


def test_load_rows_rejects_bad_kind(tmp_path):
    p = tmp_path / "rows.json"
    p.write_text(
        '[{"row_id": "p1-r1", "kind": "bogus", "business": null, "division": "",'
        ' "procedure": "", "remarks": "", "pdf_page": 1, "printed_page": null, "y": 0}]',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="kind"):
        load_rows(p)


@pytest.fixture(scope="session")
def rows():
    return extract_rows(PDF)


def division_numbers(rows, business):
    out = []
    for r in rows_for_business(rows, business):
        m = re.match(r"(\d+)\.", r.division)
        if m and int(m.group(1)) not in out:
            out.append(int(m.group(1)))
    return out


@pytest.mark.slow
def test_divisions_per_business(rows):
    assert division_numbers(rows, "birth") == [1, 2, 3, 4, 5, 6, 7]
    assert division_numbers(rows, "marriage") == [1, 2, 3, 4, 5, 6, 7, 8]
    assert division_numbers(rows, "divorce") == [1, 2, 3, 4, 5, 6, 7]
    assert division_numbers(rows, "death") == [1, 2, 3, 4, 5, 6, 7]
    assert division_numbers(rows, "certificate") == [1, 2, 3, 4, 5]


@pytest.mark.slow
def test_known_remarks_are_in_remarks_column(rows):
    birth = rows_for_business(rows, "birth")
    assert any("戸籍法第25条、第51条" in r.remarks and "届出地" in r.procedure for r in birth)
    assert not any("戸籍法第2" in r.procedure for r in birth if r.kind == "table")


@pytest.mark.slow
def test_page_continuation_keeps_business(rows):
    r = next(r for r in rows if "母の生年月日" in r.procedure)
    assert (r.business, r.pdf_page, r.printed_page) == ("birth", 3, 2)


@pytest.mark.slow
def test_footnotes_are_separate(rows):
    fn = [r for r in rows if r.kind == "footnote"]
    assert any("現に届出の任に当たっている者" in r.procedure for r in fn)
    assert not any("現に届出の任" in r.procedure for r in rows if r.kind == "table")


@pytest.mark.slow
def test_row_ids_are_unique(rows):
    assert len({r.row_id for r in rows}) == len(rows)


@pytest.mark.slow
def test_page_top_note_belongs_to_new_business(rows):
    r = next(r for r in rows if r.pdf_page == 4 and r.kind == "note")
    assert r.business == "marriage"
