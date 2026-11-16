# オントロジー構築 実装計画

> **実行するエージェントへ：** superpowers:subagent-driven-development（推奨）か superpowers:executing-plans でタスクごとに実装する。進捗は `.superpowers/sdd/2026-11-16-ontology-design/progress.md` に記録し、この計画のチェックボックスは付けない（CLAUDE.md）。

**Goal:** 手順書から、5 業務の工程・審査項目・法令ノードと、出生届の判定ルールを持つオントロジーを LLM で生成し、SHACL 検証と CQ テストを通す。

**Architecture:** PDF の表をコードで行に取り出し、Agent SDK を包んだ semantica のプロバイダーで、スキーマ → インスタンス → 現行法 → 整合性シェイプ → 判定ルールの順に生成する。IRI・出典・Turtle の並びはコードが決める。判定は、派生値（日数・年齢）を足した事案データに pyshacl を当て、`sh:sourceShape` からルール → 審査項目 → 条文の版を引く。

**Tech Stack:** Python 3.12、semantica 0.7.0（`LLMOntologyGenerator`、`provider_registry`）、claude-agent-sdk、rdflib、pyshacl、pdfplumber、jpholiday（Task 9 で追加）、pytest。

**Spec:** `docs/specs/2026-11-16-ontology-design.md`（§ はこの仕様の節）

## Global Constraints

- 名前空間：`kos:` = `https://semantica-agent.example/koseki/schema#`、`kd:` = `https://semantica-agent.example/koseki/id/`、`kcase:` = `https://semantica-agent.example/koseki/case/`。定義は `src/semantica_agent/namespaces.py` の 1 か所だけ。
- クラスは UpperCamelCase、プロパティは lowerCamelCase の英語。日本語は `rdfs:label "…"@ja`、説明は `rdfs:comment "…"@ja`。
- IRI・短い ID・出典は LLM に決めさせず、コードが決める（§7.1、§5.4）。
- LLM の生成結果は `ontology/generated/<段>/` にそのまま置いてコミットし、レビュー後のものを `ontology/` の所定の場所に別のコミットで置く。テストと `load_ontology` は `ontology/generated/` を読まない。
- `ANTHROPIC_API_KEY` があれば生成を始めずに止める。
- 実際に LLM を呼ぶ段（Task 13）は、呼び出しの回数をユーザーに伝えて確認を取ってから流す。
- 外部の入力（PDF、LLM の応答、e-Gov の応答、Turtle、環境変数）は境界で検証する。失敗したら、何がどう違うかを書いたメッセージで止める。例外は握り潰さない。
- ファイルは最大 800 行、関数は 50 行以内。ログは `LOG_LEVEL` で制御し、既定は `INFO`。
- テスト：`uv run pytest -m "not llm"`。PDF を丸ごと読むものは `slow`、Claude を呼ぶものは `llm`。カバレッジは `src/semantica_agent/` で 80% 以上。
- コミットは `<type>: <日本語>`。ブランチは `feat/ontology-design`。

## Review Focus

1. 頁をまたぐ項目（出生の「母の生年月日」は PDF 3 頁の先頭から続く）：前の頁と同じ業務・区分の続きとして取り出す。→ Task 3 の `test_page_continuation_keeps_business`。
1. 法令名を繰り返さない列挙（「戸籍法施行規則第53条、第53条の2、第11条の2」）と範囲（「第10条の2第3項～第5項」）：法令名を引き継ぎ、範囲を各項に展開する。→ Task 4 の `test_parse_inherits_law_name` と `test_parse_expands_paragraph_range`。
1. 出生日がちょうど 2024-04-01 と 2024-03-31 の事案：版の選択が境界で切り替わる。→ Task 11 の `test_version_boundary`。
1. LLM が JSON を前置きの文やコードフェンスで包む、または途中で切れる：取り出すか、1 回だけ再要求し、それでも駄目ならエラーで止める。→ Task 5 の `test_generate_structured_retries_once`。
1. 同じ入力で生成し直す：IRI と Turtle の並びが同じになり、差分が出ない。→ Task 2 の `test_write_turtle_is_deterministic`、Task 7 の `test_instances_to_graph_is_deterministic`。

## ファイル構成

| ファイル                                                                       | 役割                                                                                          |
| ------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `src/semantica_agent/namespaces.py`                                            | 名前空間の定数と prefix の束縛                                                                |
| `src/semantica_agent/vocab.py`                                                 | §4.2〜§4.4 の名前の表（スキーマ生成の必須概念）、業務・法令・書類などの slug の対応表、列挙値 |
| `src/semantica_agent/ids.py`                                                   | IRI と短い ID の組み立て・相互変換、`ProvisionRef`                                            |
| `src/semantica_agent/settings.py`                                              | 環境変数の読み込みと検証                                                                      |
| `src/semantica_agent/turtle_io.py`                                             | 決まった並びの Turtle 書き出し、オントロジーの読み込み                                        |
| `src/semantica_agent/provenance.py`                                            | PROV-O の生成記録                                                                             |
| `src/semantica_agent/extract.py`                                               | PDF → 行（`Row`）                                                                             |
| `src/semantica_agent/lawref.py`                                                | 備考の条文の解析と照合                                                                        |
| `src/semantica_agent/llm_provider.py`                                          | Agent SDK のプロバイダー                                                                      |
| `src/semantica_agent/schema_gen.py`                                            | スキーマの生成と網羅の照合                                                                    |
| `src/semantica_agent/instance_gen.py`                                          | インスタンスの生成・検証・Turtle 化                                                           |
| `src/semantica_agent/law_gen.py`                                               | e-Gov の取得、改正と現行版の下書き、承認                                                      |
| `src/semantica_agent/derive.py`                                                | 派生値の計算                                                                                  |
| `src/semantica_agent/shapes_gen.py`                                            | 整合性シェイプと判定ルールの生成                                                              |
| `src/semantica_agent/judge.py`                                                 | 事案データの判定                                                                              |
| `src/semantica_agent/build.py`                                                 | CLI（段ごとの実行）                                                                           |
| `src/semantica_agent/prompts/{schema,instances,amendments,integrity,rules}.md` | プロンプト                                                                                    |
| `ontology/…`                                                                   | §4.1 の表のとおり                                                                             |
| `ontology/cq/cq01.rq`〜`cq15.rq`                                               | CQ の SPARQL                                                                                  |
| `tests/fixtures/mini_ontology.ttl`                                             | 数ノードの合成オントロジー                                                                    |
| `tests/fixtures/birth_cases/*.ttl`、`expected.json`                            | 出生届の事案と正解表                                                                          |

______________________________________________________________________

### Task 1: 事案側のプロパティの洗い出しと名前の表

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/namespaces.py`、`src/semantica_agent/vocab.py`
- Test: `tests/test_namespaces.py`、`tests/test_vocab.py`
- Modify（必要なら）：`docs/specs/2026-11-16-ontology-design.md` §4.4

**Interfaces:**

- Produces:

  - `KOS`、`KD`、`KCASE: rdflib.Namespace`、`PREFIXES: dict[str, str]`（`kos`、`kd`、`kcase`、`prov`、`sh`、`dcterms`、`rdfs`、`owl`、`xsd`）、`bind_prefixes(g: Graph) -> Graph`
  - `REQUIRED_CLASSES: dict[str, str]`（ローカル名 → 日本語ラベル。§4.2 の 17 クラスと `Filing`、`BirthFiling`）
  - `REQUIRED_PROPERTIES: dict[str, str]`（§4.3 と §4.4 の全プロパティ）
  - `ENUM_INDIVIDUALS: dict[str, tuple[str, ...]]`（`versionStatus`：`Manual`、`Current`、`Repealed`。`currentTreatment`：`Valid`、`Changed`、`Obsolete`。`outcome`：`Reject`、`NeedsCorrection`、`NeedsInquiry`、`AdditionalProcedure`、`Info`。`reviewStatus`：`LlmDraft`、`HumanReviewed`、`HumanEdited`。`sourceKind`：`ManualSource`、`CurrentLawSource`、`Speculation`）
  - `BUSINESS_SLUGS: dict[str, str]`（`"戸籍届出（出生）": "birth"`、`"戸籍届出（婚姻）": "marriage"`、`"戸籍届出（離婚）": "divorce"`、`"戸籍届出（死亡）": "death"`、`"戸籍謄本等の交付": "certificate"`）
  - `LAW_SLUGS: dict[str, str]`（正式名 → slug。`戸籍法: koseki-ho`、`戸籍法施行規則: koseki-ho-kisoku`、`民法: minpo`、`住民基本台帳法: juki-ho`、`人口動態調査令: jinko-dotai-rei`、`母子保健法施行規則: boshi-hoken-kisoku`、`法の適用に関する通則法: tsusoku-ho`、`墓地、埋葬等に関する法律: bochi-maiso-ho`、`地方公共団体の手数料の標準に関する政令: tesuryo-seirei`、`学校教育法: gakko-kyoiku-ho`）、`LAW_ALIASES: dict[str, str]`（`住基法 → 住民基本台帳法`）
  - `DOCUMENT_SLUGS`、`CONDITION_SLUGS`、`ROLE_SLUGS`、`ORGANIZATION_SLUGS`、`RECORD_ITEM_SLUGS: dict[str, str]`（日本語名 → slug）。§4.2 の例をすべて初期値として入れる。LLM が表に無い名前を出したら Task 7 が止まり、人がここに足す。

- [ ] **Step 1:** §4.7 の B1〜B12 の各ルールが読む事案側の値を列挙し、§4.4 の表と突き合わせる。足りないものがあれば §4.4 に追記し、仕様の変更としてユーザーに確認を取る（足りなければここで止まる）。結果を progress.md に記録する。

- [ ] **Step 2: 失敗するテストを書く**

```python
def test_namespaces_match_spec():
    assert str(KOS) == "https://semantica-agent.example/koseki/schema#"
    assert str(KD) == "https://semantica-agent.example/koseki/id/"


def test_required_names_follow_case_rules():
    assert all(n[0].isupper() and n.isascii() for n in REQUIRED_CLASSES)
    assert all(n[0].islower() and n.isascii() for n in REQUIRED_PROPERTIES)


def test_required_classes_cover_spec():
    assert {
        "Business",
        "ProcedureStep",
        "StepItem",
        "Task",
        "ReviewCheck",
        "Condition",
        "DocumentType",
        "RecordItem",
        "PartyRole",
        "Organization",
        "Law",
        "LegalProvision",
        "ProvisionVersion",
        "LegalAmendment",
        "SourceReference",
        "JudgmentRule",
        "DerivedValue",
        "Filing",
        "BirthFiling",
    } <= REQUIRED_CLASSES.keys()


def test_slugs_are_unique_and_ascii():
    for table in (LAW_SLUGS, DOCUMENT_SLUGS, CONDITION_SLUGS, ROLE_SLUGS):
        assert len(set(table.values())) == len(table)
        assert all(s.isascii() for s in table.values())
```

- [ ] **Step 3:** `uv run pytest tests/test_namespaces.py tests/test_vocab.py -v` を流し、ImportError で FAIL することを確かめる。
- [ ] **Step 4:** 上の Interfaces のとおりに実装する。
- [ ] **Step 5:** テストが PASS することを確かめる。
- [ ] **Step 6:** コミットする：`feat: 名前空間とオントロジーの名前の表を追加`

### Task 2: IRI・短い ID、Turtle の入出力、生成の記録

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/ids.py`、`src/semantica_agent/turtle_io.py`、`src/semantica_agent/provenance.py`
- Test: `tests/test_ids.py`、`tests/test_turtle_io.py`、`tests/test_provenance.py`

**Interfaces:**

- Consumes: Task 1 の `KD`、`KOS`、`LAW_SLUGS`、`BUSINESS_SLUGS`、`bind_prefixes`

- Produces:

  - `@dataclass(frozen=True) ProvisionRef(law: str, article: int, branch: int | None = None, paragraph: int | None = None, item: int | None = None)`。`law` は正式名。
  - `business_iri(slug) -> URIRef`、`step_iri(business: str, step: int)`、`item_iri(business: str, step: int, position: tuple[int, ...])`、`provision_iri(ref: ProvisionRef)`、`article_iri(ref)`（項・号を落とした条のノード）、`version_iri(provision: URIRef, label: str)`（`label` は `"manual"` か `"YYYY-MM-DD"`）、`amendment_iri(era: str, year: int, number: int)`、`manual_source_iri(row_id: str)`、`egov_source_iri(slug: str)`、`rule_iri(business, slug)`、`derived_iri(slug)`、`vocab_iri(kind: str, slug: str)`（`kind` は `document`、`condition`、`role`、`organization`、`record-item`）
  - `short_id(iri: URIRef) -> str`、`iri_from_short_id(s: str) -> URIRef`（1 対 1）
  - `write_turtle(g: Graph, path: Path) -> None`（並びを固定）、`load_ontology(root: Path) -> Graph`（`root` の下の `*.ttl` を読み、`generated/` と `cq/` を除く）
  - `file_sha256(path: Path) -> str`、`record_activity(g: Graph, *, run_id: str, stage: str, started: datetime, ended: datetime, inputs: list[Path], pdf_pages: list[int], prompt_path: Path | None, model: str | None, outputs: list[Path]) -> tuple[Graph, URIRef]`（`g` を変えず、Activity を足した新しいグラフと Activity の IRI を返す）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_item_iri_matches_spec():
    assert item_iri("birth", 1, (1, 2)) == KD["birth/step/1/item/1.2"]

def test_provision_iri_with_branch_and_paragraph():
    ref = ProvisionRef("戸籍法", 27, branch=2, paragraph=1)
    assert provision_iri(ref) == KD["law/koseki-ho/art/27-2/para/1"]
    assert article_iri(ref) == KD["law/koseki-ho/art/27-2"]

def test_version_and_amendment_iri():
    p = provision_iri(ProvisionRef("民法", 772))
    assert version_iri(p, "2024-04-01") == KD["law/minpo/art/772/version/2024-04-01"]
    assert amendment_iri("R", 4, 102) == KD["amendment/R4-102"]

@pytest.mark.parametrize("iri,sid", [
    (KD["birth/step/2/item/5"], "BIRTH-S2-I5"),
    (KD["birth/step/1/item/1.2"], "BIRTH-S1-I1.2"),
    (KD["law/minpo/art/772"], "LAW-MINPO-772"),
    (KD["rule/birth/legitimacy-current"], "RULE-BIRTH-LEGITIMACY-CURRENT"),
    (KD["source/manual/p3-r14"], "SRC-P3-R14"),
])
def test_short_id_round_trip(iri, sid):
    assert short_id(iri) == sid
    assert iri_from_short_id(sid) == iri

def test_write_turtle_is_deterministic(tmp_path):
    # 同じトリプルを別の順で足した 2 つのグラフが、同じバイト列で書き出される
    ...
    assert (tmp_path / "a.ttl").read_bytes() == (tmp_path / "b.ttl").read_bytes()

def test_load_ontology_skips_generated(tmp_path):
    # ontology/generated/x.ttl のトリプルは読まれない
    ...

def test_record_activity_links_inputs_and_model(tmp_path):
    g, act = record_activity(Graph(), run_id="r1", stage="schema", ..., model="claude-x")
    assert (act, RDF.type, PROV.Activity) in g
    assert (act, KOS.model, Literal("claude-x")) in g
```

短い ID の規則：業務と工程・項目は `{BUSINESS}-S{n}-I{位置}`、条文は `LAW-{SLUG}-{条}[-{枝番}][-P{項}][-I{号}]`、版は `{条文の ID}-V{manual|YYYYMMDD}`、ルールは `RULE-{BUSINESS}-{SLUG}`、出典は `SRC-{row_id}`、`SRC-EGOV-{SLUG}`、語彙は `{KIND}-{SLUG}`。すべて大文字、slug の `-` はそのまま。

- [ ] **Step 2:** テストが FAIL することを確かめる。
- [ ] **Step 3:** 実装する。`write_turtle` は rdflib の `longturtle` で書き出し、主語の IRI 順・述語順に並べる。`longturtle` で並びが安定しなければ、主語ごとに並べ替えて組み立てる。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: IRI・短い ID・Turtle の入出力・生成の記録を追加`

### Task 3: 手順書の表の取り出し

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/extract.py`
- Test: `tests/test_extract.py`

**Interfaces:**

- Consumes: Task 1 の `BUSINESS_SLUGS`

- Produces:

  - `@dataclass(frozen=True) Row(row_id: str, kind: Literal["table", "footnote", "note", "title"], business: str | None, division: str, procedure: str, remarks: str, pdf_page: int, printed_page: int | None, y: float)`
  - `extract_rows(pdf_path: Path) -> list[Row]`、`save_rows(rows, path: Path) -> None`、`load_rows(path: Path) -> list[Row]`（JSON。読み込み時に型を検証する）
  - `rows_for_business(rows, business_slug: str) -> list[Row]`

- [ ] **Step 1: 失敗するテストを書く**（列の振り分けの Unit テストは、語の座標のリストを入力にした小さな関数 `assign_columns(words, bounds) -> tuple[str, str, str]` で書く）

```python
def test_assign_columns_splits_procedure_and_remarks():
    words = [
        w("②", 60),
        w("出生届と出生証明書の記載事項と合致しているか確認す", 80),
        w("用意する。（戸籍法第29条", 330),
    ]
    assert assign_columns(words, ColumnBounds(division_end=55, procedure_end=320)) == (
        "",
        "② 出生届と出生証明書の記載事項と合致しているか確認す",
        "用意する。（戸籍法第29条",
    )


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
    assert not any("戸籍法第" in r.procedure for r in birth if r.kind == "table")


@pytest.mark.slow
def test_page_continuation_keeps_business(rows):
    r = next(r for r in rows if "母の生年月日" in r.procedure)
    assert (r.business, r.pdf_page, r.printed_page) == ("birth", 3, 2)


@pytest.mark.slow
def test_footnotes_are_separate(rows):
    assert any(r.kind == "footnote" and "現に届出の任に当たっている者" in r.procedure for r in rows)
```

`rows` は `docs/domain/手順書.pdf` を 1 回だけ読む session スコープのフィクスチャ。`division_numbers` はテスト内の補助関数（区分の先頭の数字を出現順に重複なしで並べる）。

- [ ] **Step 2:** FAIL を確かめる（`uv run pytest tests/test_extract.py -m "slow or not slow" -v`）。
- [ ] **Step 3:** 実装する。列の境界は、各頁の見出しの語「区分」「業務手順」「備考」の x 座標から決める（見出しが無い続きの頁は前の頁の境界を使う）。行は `y` の近さ（許容差は定数）でまとめる。印刷頁は頁の下端の「- n -」から読む。
- [ ] **Step 4:** PASS を確かめる。`uv run python -m semantica_agent.build extract`（Task 12 で用意する前は関数を直接呼ぶ）の結果を目で見て、列の振り分けの誤りが無いかを progress.md に記録する。
- [ ] **Step 5:** コミットする：`feat: 手順書の表を行に取り出す`

### Task 4: 備考の条文の解析と照合

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/lawref.py`
- Test: `tests/test_lawref.py`

**Interfaces:**

- Consumes: `ProvisionRef`（Task 2）、`LAW_SLUGS`、`LAW_ALIASES`（Task 1）

- Produces:

  - `parse_provisions(text: str) -> list[ProvisionRef]`（Task 7 で LLM の出力を照合するための、決定的な解析）
  - `provision_appears_in(ref: ProvisionRef, remarks: str) -> bool`（全角数字・空白・「第27条2」の誤記を正規化してから照合）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_parse_single():
    assert parse_provisions("戸籍法第25条") == [ProvisionRef("戸籍法", 25)]


def test_parse_inherits_law_name():
    assert parse_provisions("戸籍法施行規則第53条、第53条の2、第11条の2") == [
        ProvisionRef("戸籍法施行規則", 53),
        ProvisionRef("戸籍法施行規則", 53, branch=2),
        ProvisionRef("戸籍法施行規則", 11, branch=2),
    ]


def test_parse_expands_paragraph_range():
    assert parse_provisions("戸籍法第10条の2第３項～第5項") == [
        ProvisionRef("戸籍法", 10, 2, p) for p in (3, 4, 5)
    ]


def test_parse_alias_and_fullwidth():
    assert parse_provisions("住基法第9条第２項") == [ProvisionRef("住民基本台帳法", 9, paragraph=2)]


def test_parse_typo_branch():
    assert parse_provisions("戸籍法第27条2第1項") == [ProvisionRef("戸籍法", 27, 2, 1)]


def test_parse_law_name_with_comma():
    assert parse_provisions("墓地、埋葬等に関する法律第5条") == [
        ProvisionRef("墓地、埋葬等に関する法律", 5)
    ]


def test_parse_without_dai():
    assert parse_provisions("民法第764条、739条") == [
        ProvisionRef("民法", 764),
        ProvisionRef("民法", 739),
    ]


def test_appears_in():
    assert provision_appears_in(ProvisionRef("戸籍法", 52, paragraph=2), "戸籍法第52条第1項、第2項")
    assert not provision_appears_in(ProvisionRef("戸籍法", 53), "戸籍法第52条第1項")
```

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する。法令名は `LAW_SLUGS` と `LAW_ALIASES` の名前を長い順に照合し、条文の参照は正規表現でとる。法令名の無い条文は、直前の法令名を引き継ぐ。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: 備考の条文を解析・照合する`

### Task 5: Agent SDK のプロバイダーと設定

**スキル：** superpowers:test-driven-development。Agent SDK の使い方は `code.claude.com/docs/en/agent-sdk` を見る（`claude-api` スキルは使わない）。

**Files:**

- Create: `src/semantica_agent/settings.py`、`src/semantica_agent/llm_provider.py`
- Test: `tests/test_settings.py`、`tests/test_llm_provider.py`

**Interfaces:**

- Produces:

  - `@dataclass(frozen=True) Settings(gen_model: str, log_level: str, run_root: Path)`、`load_settings(env: Mapping[str, str] = os.environ) -> Settings`。`ONTOLOGY_GEN_MODEL`（既定は定数 `DEFAULT_GEN_MODEL = "claude-opus-5-5"`）、`LOG_LEVEL`（既定 `INFO`）、`run_root` は `data/generation`。`ANTHROPIC_API_KEY` があれば `ConfigError` を投げる。
  - `PROVIDER_NAME = "claude_agent_sdk"`、`register_provider() -> None`（何度呼んでもよい）
  - `class ClaudeAgentSDKProvider(BaseProvider)`：`__init__(self, model: str | None = None, run_dir: Path | None = None, query_fn=None, **kwargs)`、`generate(self, prompt: str, **kwargs) -> str`、`generate_structured(self, prompt: str, **kwargs) -> dict | list`、属性 `last_model: str | None`。`query_fn` の既定は `claude_agent_sdk.query`（テストで差し替える）。
  - 呼び出しの記録：`run_dir/NNN-prompt.md`、`NNN-response.txt`、`NNN-meta.json`（`model`、`started`、`ended`）。

- [ ] **Step 1: 失敗するテストを書く**（`query_fn` には、`AssistantMessage(model=…, content=[TextBlock(…)])` を返す非同期ジェネレーターのフィクスチャを渡す）

````python
def test_load_settings_rejects_api_key():
    with pytest.raises(ConfigError, match="ANTHROPIC_API_KEY"):
        load_settings({"ANTHROPIC_API_KEY": "x"})


def test_generate_returns_text_and_model(tmp_path):
    p = ClaudeAgentSDKProvider(
        model="m", run_dir=tmp_path, query_fn=fake_query(["OK"], model="m-actual")
    )
    assert p.generate("hi") == "OK"
    assert p.last_model == "m-actual"
    assert (tmp_path / "001-prompt.md").read_text() == "hi"


def test_generate_structured_strips_fence(tmp_path):
    p = ClaudeAgentSDKProvider(
        run_dir=tmp_path, query_fn=fake_query(['前置き\n```json\n{"a": 1}\n```'])
    )
    assert p.generate_structured("x") == {"a": 1}


def test_generate_structured_retries_once(tmp_path):
    q = fake_query(['{"a": ', '{"a": 2}'])
    p = ClaudeAgentSDKProvider(run_dir=tmp_path, query_fn=q)
    assert p.generate_structured("x") == {"a": 2}
    assert "JSON" in q.prompts[1]  # 再要求のプロンプトにエラーの内容が入る


def test_generate_structured_fails_after_retry(tmp_path):
    p = ClaudeAgentSDKProvider(run_dir=tmp_path, query_fn=fake_query(["no", "still no"]))
    with pytest.raises(ProcessingError, match="JSON"):
        p.generate_structured("x")


def test_registered_provider_is_used_by_semantica():
    register_provider()
    assert provider_registry.get("claude_agent_sdk") is ClaudeAgentSDKProvider


@pytest.mark.llm
def test_real_call_returns_json(tmp_path):
    p = ClaudeAgentSDKProvider(run_dir=tmp_path)
    assert p.generate_structured('{"ok": true} とだけ JSON で返して') == {"ok": True}
````

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する。`ClaudeAgentOptions(allowed_tools=[], max_turns=1, model=…, system_prompt=…)`。同期の入口からは `anyio.run` で呼ぶ。
- [ ] **Step 4:** PASS を確かめる（`llm` は除く）。
- [ ] **Step 5:** コミットする：`feat: Agent SDK を包んだ semantica のプロバイダーを追加`

### Task 6: スキーマの生成と網羅の照合

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/schema_gen.py`、`src/semantica_agent/prompts/schema.md`
- Test: `tests/test_schema_gen.py`

**Interfaces:**

- Consumes: `REQUIRED_CLASSES`、`REQUIRED_PROPERTIES`、`ENUM_INDIVIDUALS`（Task 1）、`Row`（Task 3）、`PROVIDER_NAME`（Task 5）、`bind_prefixes`
- Produces:
  - `class KosekiOntologyGenerator(LLMOntologyGenerator)`：`_build_prompt(**kwargs) -> str` は `prompts/schema.md` を読み、`{rows}`、`{required_classes}`、`{required_properties}` を埋める。`_normalize_output` は `label_ja`、`comment_ja`、`speculative`、`reason` を残す。
  - `generate_schema(rows: list[Row], provider: str = PROVIDER_NAME) -> dict`
  - `@dataclass(frozen=True) CoverageReport(missing: tuple[str, ...], extra: tuple[str, ...], speculative: tuple[str, ...])`、`check_schema_coverage(schema: dict) -> CoverageReport`
  - `schema_dict_to_graph(schema: dict) -> Graph`（`owl:Class`・`owl:ObjectProperty`・`owl:DatatypeProperty`、label と comment は `@ja`、`ENUM_INDIVIDUALS` の個体、`owl:versionInfo`）
  - `schema_summary(g: Graph) -> str`（Task 7 のプロンプトに入れる、名前・種類・ラベルの一覧）

プロンプト（`schema.md`）に書く中身は §5.3 の 1〜6。出力の JSON の例を 1 つ入れる。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_prompt_contains_required_names_and_rows(rows_sample):
    p = KosekiOntologyGenerator(provider=None)._build_prompt(text=render_rows(rows_sample))
    assert "ReviewCheck" in p and "citesProvision" in p and "p2-r5" in p


def test_coverage_reports_missing_and_extra():
    schema = {
        "classes": [{"name": "Business"}, {"name": "Foo", "speculative": True}],
        "properties": [],
    }
    r = check_schema_coverage(schema)
    assert "ReviewCheck" in r.missing and r.extra == ("Foo",) and r.speculative == ("Foo",)


def test_schema_dict_to_graph_keeps_japanese_label():
    g = schema_dict_to_graph(
        {"classes": [{"name": "Business", "label_ja": "業務"}], "properties": []}
    )
    assert (KOS.Business, RDFS.label, Literal("業務", lang="ja")) in g


def test_generate_schema_uses_registered_provider(monkeypatch, rows_sample):
    # provider_registry に偽のプロバイダーを登録し、その JSON が正規化されて返る
    ...
```

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: スキーマを LLM で生成し網羅を照合する`

### Task 7: インスタンスの生成・検証・Turtle 化

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/instance_gen.py`、`src/semantica_agent/prompts/instances.md`
- Test: `tests/test_instance_gen.py`、`tests/fixtures/instances_birth_sample.json`（出生の受付・審査の数項目ぶんの手書きの LLM 出力）

**Interfaces:**

- Consumes: `Row`、`rows_for_business`、`parse_provisions`、`provision_appears_in`、`ids.*`、`schema_summary`、各 slug の表
- Produces:
  - LLM の出力の形（プロンプトにも書く）：

```json
{"business": "birth",
 "steps": [{"number": 2, "label": "審査", "row_ids": ["p2-r20"],
   "items": [{"label": "○", "kind": "check|task|note", "text": "届出期間内の届出か。",
     "quote": "届出期間内の届出か", "row_ids": ["p3-r9"],
     "conditions": [], "documents": [], "record_items": [], "roles": [], "escalates_to": [],
     "cites": [{"law": "戸籍法", "article": 49, "branch": null, "paragraph": null, "item": null,
                "normalization_note": null}],
     "notes": [], "alignment": "ok", "speculative": false, "reason": null,
     "prerequisite_for": null, "children": []}]}]}
```

- `build_instance_prompt(business: str, rows: list[Row], schema_text: str, known_laws: list[str]) -> str`

- `validate_instance_output(out: dict, rows: list[Row]) -> list[str]`（エラーの一覧。空なら合格。§5.4 の 4 つの検査と、slug が表にあるかの検査）

- `instances_to_graph(out: dict, rows: list[Row], activity: URIRef) -> tuple[Graph, Graph]`（業務のグラフ、法令のグラフ）。項目の位置は兄弟の中の出現順（1 始まり）。番号付きのラベル（(n)、丸数字）の数字と出現順が違えば警告をログに出す。`kind` が `check` なら `kos:ReviewCheck`、`task` なら `kos:Task`、`note` なら `kos:StepItem`。出典 `kos:SourceReference` は `row_ids` の行から作り（`kos:sourceKind kos:ManualSource`、頁・印刷頁・業務名・区分・`row_id`・引用）、全ノードに `dcterms:identifier`・`kos:reviewStatus kos:LlmDraft`・`prov:wasGeneratedBy activity` を付ける。条文は項のノードと条のノードを作り `kos:partOf` でつなぎ、手順書時点の版 `version/manual`（`kos:versionStatus kos:Manual`）を付ける。

- `generate_instances(business: str, rows: list[Row], schema_text: str, known_laws: list[str], provider: str = PROVIDER_NAME) -> dict`（検証で落ちたら `InstanceValidationError(errors)`）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_valid_sample_has_no_errors(sample, birth_rows):
    assert validate_instance_output(sample, birth_rows) == []


def test_quote_not_in_row_is_error(sample, birth_rows):
    bad = with_item(sample, quote="存在しない文")
    assert any("quote" in e for e in validate_instance_output(bad, birth_rows))


def test_cite_not_in_remarks_is_error(sample, birth_rows):
    bad = with_item(sample, cites=[{"law": "戸籍法", "article": 999}])
    assert any("戸籍法第999条" in e for e in validate_instance_output(bad, birth_rows))


def test_unused_rows_are_reported(sample, birth_rows):
    assert any(
        "p3-r30" in e for e in validate_instance_output(sample, birth_rows + [extra_row("p3-r30")])
    )


def test_unknown_slug_is_error(sample, birth_rows):
    bad = with_item(sample, documents=["unknown-doc"])
    assert any("unknown-doc" in e for e in validate_instance_output(bad, birth_rows))


def test_graph_has_source_from_rows_not_llm(sample, birth_rows):
    g, _ = instances_to_graph(sample, birth_rows, KD["activity/t"])
    src = g.value(item_iri("birth", 2, (1,)), KOS.hasSource)
    assert src == manual_source_iri("p2-r21")
    assert g.value(src, KOS.pdfPage) == Literal(2)


def test_law_graph_links_paragraph_to_article(sample, birth_rows):
    _, laws = instances_to_graph(sample, birth_rows, KD["activity/t"])
    assert (
        provision_iri(ProvisionRef("戸籍法", 52, paragraph=1)),
        KOS.partOf,
        article_iri(ProvisionRef("戸籍法", 52)),
    ) in laws


def test_instances_to_graph_is_deterministic(sample, birth_rows, tmp_path):
    # 2 回変換して write_turtle した結果がバイト単位で同じ
    ...
```

`birth_rows` は合成の `Row` のリスト（PDF を読まない）。

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する。プロンプト `instances.md` には §5.4 の 1〜6 と、「※」の注記・括弧書きも独立した項目にして親を意味で決めること（§5.1 の追記）を書く。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: インスタンスを LLM で生成し検証して Turtle にする`

### Task 8: 現行法の取得・下書き・承認

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/law_gen.py`、`src/semantica_agent/prompts/amendments.md`
- Test: `tests/test_law_gen.py`、`tests/fixtures/egov_minpo_733.json` などの e-Gov 応答のフィクスチャ

**Interfaces:**

- Produces:

  - `EGOV_LAW_IDS: dict[str, str]`（正式名 → e-Gov の法令 ID。民法・戸籍法・戸籍法施行規則・学校教育法。実装時に e-Gov 法令 API v2 の法令一覧で確かめて定数にする）
  - `@dataclass(frozen=True) ArticleText(law: str, article: str, text: str, url: str, fetched: date)`
  - `fetch_article(law: str, article: str, *, http_get=None) -> ArticleText`（`http_get` はテストで差し替える。応答の形を検証し、条文が無ければ `LawFetchError`）
  - `AMENDMENT_TARGETS`：§6.2 の 3 改正（法律番号・施行日・影響する条文）と、§6.4 の確認対象の条文（戸籍法25・43・49・51・52条、学校教育法17条）の一覧
  - `draft_amendments(texts: list[ArticleText], provider: str = PROVIDER_NAME) -> dict`、`amendments_to_graph(draft: dict, texts: list[ArticleText], activity: URIRef) -> Graph`（`kos:LegalAmendment`、現行版・廃止の版（`validFrom`）、`kos:CurrentLawSource` の出典（URL・取得日・条文の引用）、`kos:currentTreatment` と注記を、影響する審査項目に付けるトリプル。すべて `kos:LlmDraft`）
  - `approve(g: Graph, node: URIRef, reviewer: str, on: date) -> Graph`（`kos:HumanReviewed` にし、出典に確認日と確認者を足した新しいグラフ）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_fetch_article_parses_fixture():
    a = fetch_article("民法", "733", http_get=fixture_get("egov_minpo_733.json"))
    assert a.url.startswith("https://laws.e-gov.go.jp/") and a.text


def test_fetch_article_rejects_unexpected_shape():
    with pytest.raises(LawFetchError):
        fetch_article("民法", "733", http_get=lambda url: {"unexpected": 1})


def test_amendments_graph_marks_draft_and_source(draft_sample, texts):
    g = amendments_to_graph(draft_sample, texts, KD["activity/t"])
    v = version_iri(provision_iri(ProvisionRef("民法", 733)), "2024-04-01")
    assert g.value(v, KOS.versionStatus) == KOS.Repealed
    assert g.value(v, KOS.reviewStatus) == KOS.LlmDraft
    assert g.value(g.value(v, KOS.hasSource), KOS.sourceKind) == KOS.CurrentLawSource


def test_approve_returns_new_graph():
    g2 = approve(g, v, reviewer="reviewer", on=date(2026, 11, 20))
    assert g.value(v, KOS.reviewStatus) == KOS.LlmDraft
    assert g2.value(v, KOS.reviewStatus) == KOS.HumanReviewed
```

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: 現行法を e-Gov から取得して改正を下書きする`

### Task 9: 派生値の計算

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/derive.py`
- Modify: `pyproject.toml`（`jpholiday` を追加。`uv add jpholiday`）
- Test: `tests/test_derive.py`

**Interfaces:**

- Produces:

  - `DERIVED_VALUES`：`daysFromMarriageToBirth`、`daysFromPrevMarriageEndToBirth`、`filingDeadline`、`daysLate`、`motherAgeAtBirth`、`childAgeAtFiling` のそれぞれに、定義ノードの slug・計算に使う事案のプロパティ・根拠の条文
  - `@dataclass(frozen=True) PeriodRule(days: int, count_first_day: bool, extend_on_holiday: bool)`。値は、Task 8 の現行法の下書き（戸籍法43条・49条）で確かめた結果をオントロジーの `kos:DerivedValue` から読む。
  - `is_closed_day(d: date) -> bool`（土日・`jpholiday`・12/29〜1/3。`jpholiday` に対象の年の祝日が無ければ `HolidayDataError`）
  - `filing_deadline(event: date, rule: PeriodRule) -> date`、`days_between(a: date, b: date) -> int`、`age_on(birth: date, on: date) -> int`
  - `derive(case: Graph, case_iri: URIRef, ontology: Graph) -> Graph`（元の事案のグラフに派生値を足した新しいグラフ。各値に `prov:wasDerivedFrom`（元の値の述語）と `prov:wasGeneratedBy`（定義ノード）を付ける）

- [ ] **Step 1: 失敗するテストを書く**

```python
RULE_14 = PeriodRule(days=14, count_first_day=True, extend_on_holiday=True)


def test_deadline_counts_first_day():
    # 2026-11-02 を 1 日目に数えると 14 日目は 11-15（日曜）なので、11-16（月）に延びる
    assert filing_deadline(date(2026, 11, 2), RULE_14) == date(2026, 11, 16)


def test_deadline_without_extension():
    assert filing_deadline(date(2026, 11, 2), replace(RULE_14, extend_on_holiday=False)) == date(
        2026, 11, 15
    )


def test_deadline_skips_new_year():
    assert filing_deadline(date(2026, 12, 18), RULE_14) == date(2027, 1, 4)


@pytest.mark.parametrize("days", [199, 200])
def test_days_from_marriage_boundary(days):
    assert days_between(date(2025, 1, 1), date(2025, 1, 1) + timedelta(days=days)) == days


def test_age_on_birthday_eve():
    assert age_on(date(1976, 5, 10), date(2026, 5, 9)) == 49
    assert age_on(date(1976, 5, 10), date(2026, 5, 10)) == 50


def test_derive_adds_values_with_provenance(birth_case, mini_ontology):
    g = derive(birth_case, KCASE.c1, mini_ontology)
    assert g.value(KCASE.c1, KOS.daysLate) is not None
    assert (KCASE.c1, KOS.daysLate, None) not in birth_case  # 元を変えない
```

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: 事案データの派生値（日数・年齢）を計算する`

### Task 10: 整合性シェイプと判定ルールの生成

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/shapes_gen.py`、`src/semantica_agent/prompts/integrity.md`、`src/semantica_agent/prompts/rules.md`、`tests/fixtures/mini_ontology.ttl`
- Test: `tests/test_shapes_gen.py`

**Interfaces:**

- Produces:

  - `RULE_TABLE`：§4.7 の B1〜B12（ID、審査項目の説明、ルールの説明、判定の種類、法の版）を定数で持つ。プロンプトに入れる。
  - `generate_integrity_shapes(schema_text: str, provider: str = PROVIDER_NAME) -> str`（Turtle 文字列）
  - `generate_rules(instances: Graph, laws: Graph, schema_text: str, provider: str = PROVIDER_NAME) -> str`（Turtle 文字列）。プロンプトに §4.5（判定の種類と severity の対応）、§4.6.1（版の選び方：`sh:target` の SPARQL ターゲットで出生日と `validFrom`/`validUntil` を比べる）、B4a は比較用に常に評価することを書く。
  - `check_shapes_text(ttl: str, *, require_rules: bool) -> list[str]`（読めるか、pyshacl でシェイプとして読めるか。`require_rules` なら、各 `kos:JudgmentRule` に `kos:implementsCheck`・`kos:underVersion`（B4c を除く）・`kos:shape`・`kos:outcome` があり、`RULE_TABLE` の ID がすべてそろっているか）

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_check_shapes_rejects_broken_turtle():
    assert check_shapes_text("not turtle", require_rules=False)


def test_check_shapes_requires_all_rules(partial_rules_ttl):
    errors = check_shapes_text(partial_rules_ttl, require_rules=True)
    assert any("B9" in e for e in errors)


def test_rules_prompt_contains_rule_table_and_versions(mini_graphs):
    prompt = build_rules_prompt(*mini_graphs, "schema")
    assert "B4b" in prompt and "validFrom" in prompt and "sh:sourceShape" in prompt
```

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: 整合性シェイプと判定ルールを LLM で下書きする`

### Task 11: 事案データの判定

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/judge.py`
- Test: `tests/test_judge.py`（`tests/fixtures/mini_ontology.ttl` に、手書きのルール 2 つ（B9 と B4b 相当）を入れて試す）

**Interfaces:**

- Consumes: `derive`（Task 9）、`load_ontology`（Task 2）

- Produces:

  - `@dataclass(frozen=True) Finding(rule: URIRef, outcome: URIRef, check: URIRef | None, versions: tuple[URIRef, ...], focus: URIRef, message: str, provisional: bool)`。`provisional` は、ルールの版が `kos:LlmDraft` のとき True。
  - `@dataclass(frozen=True) Judgment(case: URIRef, findings: tuple[Finding, ...], decision: URIRef | None, derived: Graph)`。`decision` は、`provisional` でない Finding のうち最も重い `kos:outcome`（`Reject` > `NeedsCorrection` > `NeedsInquiry` > `AdditionalProcedure`）。無ければ None（受理可）。
  - `judge(case: Graph, case_iri: URIRef, ontology: Graph, rules: Graph) -> Judgment`。pyshacl の結果の `sh:sourceShape` から、`kos:shape` で逆引きしてルールを特定する。ルールに対応しない結果があれば `JudgeError`。

- [ ] **Step 1: 失敗するテストを書く**

```python
def test_late_filing_gives_additional_procedure(ont, rules):
    j = judge(case(birth="2026-11-02", filed="2026-11-20"), KCASE.c1, ont, rules)
    assert j.decision == KOS.AdditionalProcedure
    f = j.findings[0]
    assert f.rule == KD["rule/birth/filing-period"] and f.check == KD["birth/step/2/item/9"]


def test_in_time_filing_has_no_findings(ont, rules):
    assert (
        judge(case(birth="2026-11-02", filed="2026-11-16"), KCASE.c1, ont, rules).decision is None
    )


@pytest.mark.parametrize("birth,applies", [("2024-03-31", False), ("2024-04-01", True)])
def test_version_boundary(ont, rules, birth, applies):
    j = judge(legitimacy_case(birth=birth), KCASE.c1, ont, rules)
    assert any(f.rule == KD["rule/birth/legitimacy-current"] for f in j.findings) == applies


def test_llm_draft_version_is_provisional(ont_with_draft_version, rules):
    j = judge(legitimacy_case(birth="2025-01-01"), KCASE.c1, ont_with_draft_version, rules)
    assert all(f.provisional for f in j.findings) and j.decision is None
```

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: 事案データを判定シェイプで判定し根拠を引く`

### Task 12: 段ごとの CLI

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/build.py`
- Test: `tests/test_build.py`

**Interfaces:**

- Produces: `uv run python -m semantica_agent.build <段>`。段：

  - `extract` → `data/extracted/rows.json`
  - `schema` → `ontology/generated/schema/schema.ttl` と網羅の報告（標準出力）
  - `instances [--business SLUG]` → `ontology/generated/instances/{slug}.ttl`、`ontology/generated/law/laws-{slug}.ttl`（入力は固定済みの `ontology/schema.ttl`。無ければ止める）
  - `amendments` → `ontology/generated/law/amendments.ttl`
  - `integrity` → `ontology/generated/shapes/integrity.ttl`
  - `rules` → `ontology/generated/rules/birth-rules.ttl`
  - `approve IRI_OR_SHORT_ID --by NAME --file PATH` → 指定ファイルの中のノードを承認
  - `validate` → `ontology/`（generated を除く）を整合性シェイプで検証し、結果を表示。違反があれば終了コード 1

- 各段は `run_id`（`{段}-{YYYYMMDDHHMMSS}`）を振り、`ontology/provenance.ttl` に `record_activity` の結果を書き足す。LLM を呼ぶ段は、始める前に呼び出しの予定回数を表示する。

- `main(argv: list[str] | None = None) -> int`

- [ ] **Step 1: 失敗するテストを書く**（LLM の段は、`provider_registry` に偽のプロバイダーを登録して流す）

```python
def test_instances_requires_fixed_schema(tmp_project):
    assert main(["instances", "--business", "birth", "--root", str(tmp_project)]) == 1


def test_validate_reports_violation(tmp_project_with_bad_node):
    assert main(["validate", "--root", str(tmp_project_with_bad_node)]) == 1


def test_stage_records_provenance(tmp_project, fake_provider):
    main(["schema", "--root", str(tmp_project)])
    g = Graph().parse(tmp_project / "ontology/provenance.ttl")
    assert len(list(g.subjects(RDF.type, PROV.Activity))) == 1
```

- [ ] **Step 2:** FAIL を確かめる。
- [ ] **Step 3:** 実装する（`--root` の既定はリポジトリの直下）。
- [ ] **Step 4:** PASS を確かめる。
- [ ] **Step 5:** コミットする：`feat: オントロジーを段ごとに生成する CLI を追加`

### Task 13: 生成を流し、レビューして固定する（LLM を実際に呼ぶ）

**スキル：** superpowers:verification-before-completion。人の承認が要る箇所では止まってユーザーに確認する。

この Task はコードではなく、生成物を作るタスク。各段で「生成 → `ontology/generated/` にコミット → レビュー → 修正して所定の場所にコミット」を繰り返す。

- [ ] **Step 1:** 呼び出しの予定回数をユーザーに伝えて確認を取る。目安：スキーマ 1、インスタンス 5、改正 1、整合性シェイプ 1、ルール 1、再要求を入れて合計 10〜20 回。
- [ ] **Step 2:** `build extract` を流し、`rows.json` の列の振り分けを PDF と見比べる。
- [ ] **Step 3:** `build schema` を流し、生のままコミットする（`feat: スキーマを LLM で生成`）。網羅の報告の `missing` と `extra`、推測の理由をレビューし、直したものを `ontology/schema.ttl` に置いて別のコミットにする（`fix: スキーマを手で修正（理由）`）。直した理由は progress.md と、ノードの `rdfs:comment`（`kos:HumanEdited`）に残す。
- [ ] **Step 4:** `build instances` を業務ごとに流す。検証エラーで止まった業務は、エラーの内容（slug の不足、使い残しの行など）に応じて、表（`vocab.py`）を足すか再生成する。生のままコミットし、レビュー（§5.7 の 5）を済ませて `ontology/instances/` と `ontology/law/laws.ttl` に置く。`alignment: uncertain` の項目は PDF の原本と照合した結果を progress.md に残す。
- [ ] **Step 5:** `build amendments` を流す。ユーザーに、条文の引用と下書きを並べた一覧を見せて承認を取る。承認されたノードに `build approve` を流す。
- [ ] **Step 6:** `build integrity` と `build rules` を流す。生のままコミットし、ルールを条文と照合して直し、`kos:HumanEdited` と理由を残して所定の場所に置く。
- [ ] **Step 7:** `build validate` で整合性の違反が 0 件になることを確かめる。

### Task 14: 出生届の事案と正解表、判定の結合テスト

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `tests/fixtures/birth_cases/*.ttl`、`tests/fixtures/birth_cases/expected.json`
- Test: `tests/test_birth_rules.py`

**Interfaces:**

- Consumes: `judge`、`load_ontology`、固定済みの `ontology/rules/birth-rules.ttl`

- `expected.json` の 1 件：`{"case": "late-filing.ttl", "decision": "AdditionalProcedure", "rules": ["RULE-BIRTH-FILING-PERIOD"], "basis": ["戸籍法第49条第1項 …の引用"], "approved_by": null}`

- [ ] **Step 1:** 事案を書く。B1〜B12 の各ルールについて、当たる例と当たらない例を 1 つずつ。加えて、嫡出の判定が手順書の基準と現行の基準で分かれる例（婚姻後 150 日の出生、前婚解消後 250 日で母が再婚済みの出生）と、2024-03-31・2024-04-01 生まれの組。

- [ ] **Step 2:** 正解表を、条文の引用を付けて下書きする。ユーザーに見せて承認を取り、承認された件の `approved_by` を埋める。

- [ ] **Step 3: テストを書く**

```python
@pytest.mark.parametrize("case", load_expected(), ids=lambda c: c["case"])
def test_birth_case(case, ontology, rules):
    j = judge(load_case(case["case"]), KCASE.c1, ontology, rules)
    assert short(j.decision) == case["decision"]
    assert {short_id(f.rule) for f in j.findings if not f.provisional} == set(case["rules"])


def test_every_finding_traces_to_source(ontology, rules):
    for c in load_expected():
        for f in judge(load_case(c["case"]), KCASE.c1, ontology, rules).findings:
            assert f.check is None or ontology.value(f.check, KOS.hasSource) is not None
            assert all(ontology.value(v, KOS.hasSource) for v in f.versions)


def test_all_expected_are_approved():
    assert all(c["approved_by"] for c in load_expected())
```

- [ ] **Step 4:** 流す。落ちたら、tests.md の順（テストの隔離 → モックの境界 → 実装）で切り分ける。ルールの誤りなら `birth-rules.ttl` を直し、`kos:HumanEdited` と理由を残す。
- [ ] **Step 5:** コミットする：`test: 出生届の判定ルールを事案と正解表で固定する`

### Task 15: Competency questions

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `ontology/cq/cq01.rq`〜`cq15.rq`

- Test: `tests/test_competency_questions.py`

- [ ] **Step 1:** §8 の期待する答えを、取り出した行と PDF の原本で照合して確定する。仕様と違えば、仕様の §8 を改訂してユーザーに伝える。

- [ ] **Step 2: テストを書く**。CQ1〜CQ12 は答えの集合を短い ID で比べる。CQ13〜CQ15 は辿れること・形を確かめる。

```python
def test_cq02_kisoku_48(ontology):
    assert run_cq(ontology, "cq02") == {"BIRTH-S7", "MARRIAGE-S8", "DIVORCE-S7", "DEATH-S7"}


def test_cq07_minpo_733(ontology):
    rows = run_cq_rows(ontology, "cq07")
    assert rows == [
        {"status": "Repealed", "amendment": "AMENDMENT-R4-102", "validFrom": "2024-04-01"}
    ]


def test_cq13_rule_traces_to_egov(ontology):
    chain = run_cq_rows(ontology, "cq13")
    assert chain[0]["rule"] == "RULE-BIRTH-LEGITIMACY-CURRENT"
    assert chain[0]["sourceKind"] == "CurrentLawSource" and chain[0]["url"].startswith(
        "https://laws.e-gov.go.jp/"
    )
```

（他の CQ も同じ形で、§8 の期待する答えをそのまま集合にする。）

- [ ] **Step 3:** 流して PASS を確かめる。落ちたら、問い（SPARQL）の誤りか、オントロジーの誤りかを切り分ける。オントロジーの誤りなら Task 13 の手順で直す。
- [ ] **Step 4:** コミットする：`test: competency questions を SPARQL で固定する`

### Task 16: 仕上げ

**スキル：** superpowers:verification-before-completion、superpowers:requesting-code-review（ブランチ全体を 1 回）、superpowers:finishing-a-development-branch（PR の選択肢）

- [ ] **Step 1:** `uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest -m "not llm" --cov=src/semantica_agent --cov-report=term-missing` を流し、カバレッジが 80% 以上であることを確かめる。
- [ ] **Step 2:** `uv run pytest -m "slow"` を流す。
- [ ] **Step 3:** 生成と人の修正で分かったこと（LLM の生成がどこまで使えたか、どこを直したか）を `docs/notes/2026-11-ontology-generation.md` にまとめる（検証の材料になるため）。
- [ ] **Step 4:** ブランチ全体のコードレビューを受け、指摘に対応する。
- [ ] **Step 5:** PR を作る（日本語のタイトル、変更の概要、テスト結果）。
