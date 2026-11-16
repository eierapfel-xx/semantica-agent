import copy

from semantica_agent.extract import Row
from semantica_agent.instance_check import validate_instance_output


def with_item(sample, step=1, index=0, **changes):
    out = copy.deepcopy(sample)
    out["steps"][step]["items"][index].update(changes)
    return out


def test_valid_sample_has_no_errors(sample, birth_rows):
    assert validate_instance_output(sample, birth_rows) == []


def test_quote_spanning_rows_is_accepted(sample, birth_rows):
    # 「法務局に受理照」「会する。）」の 2 行にまたがる引用
    assert validate_instance_output(sample, birth_rows) == []


def test_quote_not_in_row_is_error(sample, birth_rows):
    bad = with_item(sample, quote="存在しない文")
    assert any("quote" in e for e in validate_instance_output(bad, birth_rows))


def test_cite_not_in_remarks_is_error(sample, birth_rows):
    bad = with_item(sample, cites=[{"law": "戸籍法", "article": 999}])
    assert any("戸籍法第999条" in e for e in validate_instance_output(bad, birth_rows))


def test_cite_with_normalization_note_skips_text_check(sample, birth_rows):
    cite = {"law": "戸籍法", "article": 999, "normalization_note": "誤記を直した"}
    assert validate_instance_output(with_item(sample, cites=[cite]), birth_rows) == []


def test_cite_unknown_law_is_error(sample, birth_rows):
    bad = with_item(sample, cites=[{"law": "未知法", "article": 1}])
    assert any("未知法" in e for e in validate_instance_output(bad, birth_rows))


def test_unused_rows_are_reported(sample, birth_rows):
    extra = Row("p3-r30", "table", "birth", "", "余分な行", "", 3, 2, 30.0)
    assert any("p3-r30" in e for e in validate_instance_output(sample, birth_rows + [extra]))


def test_unknown_row_id_is_error(sample, birth_rows):
    bad = with_item(sample, row_ids=["p9-r99"])
    assert any("p9-r99" in e for e in validate_instance_output(bad, birth_rows))


def test_unknown_vocab_is_error(sample, birth_rows):
    bad = with_item(sample, documents=["謎の書類"])
    assert any("謎の書類" in e for e in validate_instance_output(bad, birth_rows))


def test_new_vocab_proposals_are_reported(sample, birth_rows):
    out = copy.deepcopy(sample)
    out["new_vocab"] = [{"kind": "document", "name_ja": "謎の書類", "slug": "mystery"}]
    assert any("mystery" in e for e in validate_instance_output(out, birth_rows))


def test_bad_kind_and_alignment(sample, birth_rows):
    errors = validate_instance_output(with_item(sample, kind="x", alignment="maybe"), birth_rows)
    assert any("kind" in e for e in errors) and any("alignment" in e for e in errors)


def test_speculative_requires_reason(sample, birth_rows):
    bad = with_item(sample, speculative=True, reason=None)
    assert any("reason" in e for e in validate_instance_output(bad, birth_rows))


def test_step_numbers_must_match_divisions(sample, birth_rows):
    out = copy.deepcopy(sample)
    out["steps"][1]["number"] = 5
    assert any("区分" in e for e in validate_instance_output(out, birth_rows))


def test_business_mismatch(sample, birth_rows):
    out = copy.deepcopy(sample)
    out["business"] = "death"
    assert any("business" in e for e in validate_instance_output(out, birth_rows))


def test_missing_fields_do_not_crash(birth_rows):
    errors = validate_instance_output({"business": "birth", "steps": [{"items": [{}]}]}, birth_rows)
    assert errors
