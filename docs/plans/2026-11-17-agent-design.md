# 審査支援エージェントとトレースの可視化 実装計画

> **実行するエージェントへ：** superpowers:subagent-driven-development（推奨）か superpowers:executing-plans でタスクごとに実装する。進捗は `.superpowers/sdd/2026-11-17-agent-design/progress.md` に記録し、この計画のチェックボックスは付けない（CLAUDE.md）。

**Goal:** 窓口職員が日本語で質問すると、エージェントがオントロジーへのツール呼び出しで答え、その処理を手順書のフロー上の色付けとトレースの JSON で辿れるローカルの Web 画面を作る。

**Architecture:** ツールは素の Python 関数として書き（`tools.py`）、Agent SDK の SDK 内 MCP サーバーで包む（`agent.py`）。ツールは結果と一緒に「触れたノードと状態」を返し、記録係（`trace.py`）がイベントとして積む。フローの色は、判定の後処理（`assess.py`）と参照したノードからコード（`flow.py`）が決め、画面（FastAPI ＋ 素の JS）は描くだけにする。

**Tech Stack:** Python 3.12、claude-agent-sdk 0.2.182（`ClaudeSDKClient`、`create_sdk_mcp_server`、`tool`、`HookMatcher`）、rdflib、pyshacl、semantica 0.7.0（`ContextGraph`）、FastAPI・uvicorn（Task 9 で追加）、jsonschema、pytest。

**Spec:** `docs/specs/2026-11-17-agent-design.md`（§ はこの仕様の節）。前提の仕様は `docs/specs/2026-11-16-ontology-design.md`。

## Global Constraints

- 名前空間は `src/semantica_agent/namespaces.py` の `KOS`・`KD`・`KCASE` だけを使う。IRI と短い ID の変換は `ids.short_id` と `ids.iri_from_short_id` を使う。
- オントロジー（`ontology/` の Turtle、`rules/birth-rules.ttl`）とその仕様は変えない。未確認の項目の扱いは判定の後処理で行う（§5.1.1）。
- フローの色・全体の判定・主張の種類はコードが決める。LLM の申告や回答の文章から決めない（§1「失敗とみなすこと」）。
- 事案の項目の状態は `given`・`none`・`unknown` の 3 つ。`none` と `unknown` はどちらも三つ組を作らない（§5.1）。
- 全体の判定の値：`reject`・`needsCorrection`・`needsInquiry`・`additionalProcedure`・`acceptable`・`pending`（§6.2）。
- エージェントのモデルは `AGENT_MODEL`、既定 `claude-sonnet-5-5`。`max_turns` 既定 20。Web は `127.0.0.1`、ポート既定 8765（`WEB_PORT`）。`run_sparql` は最大 200 行、時間の上限 10 秒。`search_nodes` は最大 20 件。
- `ANTHROPIC_API_KEY` があれば起動時に止める（`settings.load_settings`）。
- エージェントには組み込みのツールを使わせない（`tools=[]`、`allowed_tools` は自作ツールだけ）。`setting_sources=[]`。
- トレースは `output/traces/<session_id>/<turn:03d>.json`（git 管理外）。トークンや環境変数の値を、トレース・ログ・画面に出さない。
- 画面は外部の CDN を読まない。
- Claude を実際に呼ぶテストには `llm` マーカーを付ける。それ以外のテストで SDK を呼ぶと失敗する、既存のフィクスチャを壊さない。
- ファイルは最大 800 行、関数は 50 行以内。ログは `LOG_LEVEL`。例外は握り潰さない。
- コミットは `<type>: <日本語>`。ブランチは `feat/agent-design`。

## Review Focus

1. 職員が触れていない添付書類（出生証明書）：照会の指摘を出さず、添付書類の審査項目を「評価できず」にし、全体は判定保留にする。→ Task 3 の `test_unconfirmed_document_does_not_raise_inquiry`。
1. 出生日が 2024-03-31 と 2024-04-01 の事案：続き柄・嫡出の色は、適用される版のルールだけで決まる。→ Task 2 の `test_applicable_rules_boundary`、Task 4 の `test_legitimacy_color_uses_applicable_rule`。
1. 同じターンで判定を 2 回呼び、2 回目で指摘が消えた：フローは 2 回目の状態になる（1 回目の色が残らない）。→ Task 4 の `test_replay_second_judge_replaces_case_states`。
1. LLM の引用が職員の発言と空白だけ違う、または前のターンの発言にある：通す。どの発言にも無い：その項目を示すエラーを返す。→ Task 1 の `test_quote_check`。
1. `submit_answer` が呼ばれずにターンが終わる、または SDK がエラーを返す：最後の文章を推測の回答として保存し、エラーはイベントに残してトレースを保存する。→ Task 8 の `test_turn_without_submit_answer`、`test_sdk_error_is_saved`。

## ファイル構成

| ファイル                                                       | 役割                                                                                         |
| -------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `src/semantica_agent/case_input.py`                            | 事案の項目の定義、ツールの入力の JSON スキーマ、入力の解釈（3 状態）、引用の照合、事案の RDF |
| `src/semantica_agent/rule_inputs.py`                           | ルールの使う入力の洗い出し、出生日で適用されるルール                                         |
| `src/semantica_agent/assess.py`                                | 判定の後処理（評価できなかったルール、全体の判定）                                           |
| `src/semantica_agent/flow.py`                                  | フローの形、ノードの状態、状態の合成と再生                                                   |
| `src/semantica_agent/tools.py`                                 | ツールの本体（問い合わせ 4 つ、判定、回答）と、相談の状態                                    |
| `src/semantica_agent/claims.py`                                | 主張の検証                                                                                   |
| `src/semantica_agent/trace.py`                                 | トレースの記録・検証・保存（JSON、report.md、ContextGraph、PROV-O）                          |
| `src/semantica_agent/schemas/trace.schema.json`                | トレースの JSON Schema                                                                       |
| `src/semantica_agent/agent.py`                                 | SDK の組み立て、MCP サーバー、フック、1 ターンの実行                                         |
| `src/semantica_agent/prompts/agent.md`                         | システムプロンプト                                                                           |
| `src/semantica_agent/web.py`                                   | FastAPI のアプリと起動                                                                       |
| `src/semantica_agent/web/static/{index.html,app.js,style.css}` | 画面                                                                                         |
| `src/semantica_agent/settings.py`（変更）                      | エージェントと Web の設定を足す                                                              |

______________________________________________________________________

### Task 1: 事案の入力の解釈と引用の照合

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/case_input.py`
- Test: `tests/test_case_input.py`

**Interfaces:**

- Consumes: `KOS`・`KD`・`KCASE`、`ids.short_id`

- Produces:

  - `CASE_FIELDS: tuple[CaseField, ...]`。`@dataclass(frozen=True) CaseField(name: str, kind: Literal["date","time","string","bool","iri","iri_list"], vocab: str | None, label_ja: str)`。`name` はオントロジー仕様 §4.4 の事案側プロパティのローカル名（`childBirthDate` … `addressExists`）。`vocab` は `iri`・`iri_list` の列挙の種類（`role`・`document`・`record-item`）。`statedRelationship`（`嫡出子`／`嫡出でない子`）と `statedFather`（`現在の夫`／`前の夫`／`記載なし`）は `string` で列挙を持つ。
  - `input_schema(ontology: Graph) -> dict`：`judge_birth_case` の JSON スキーマ。列挙値はオントロジーの個体（`KD["role/…"]` など）の短い ID から作る。
  - `@dataclass(frozen=True) FieldValue(name: str, status: Literal["given","none","unknown"], value: object = None, quote: str | None = None, inferred: bool = False, note: str | None = None)`、`@dataclass(frozen=True) CaseInput(fields: tuple[FieldValue, ...], complete_lists: frozenset[str])`。`unknown_fields` プロパティ（`unknown` の名前の集合）。
  - `parse_case_input(args: dict, ontology: Graph) -> CaseInput`。不正（列挙に無い値、型、`given` なのに `value` が無い、`none`・`given` なのに `quote` が無い）は `CaseInputError`（項目名を含むメッセージ）。省いた項目は `unknown`。複数値の項目で `complete` が false なら、`given` の値はそのまま、項目の状態は `given`（一覧が空なら `unknown`）、`complete_lists` に入れない。
  - `check_quotes(case: CaseInput, utterances: Sequence[str]) -> list[str]`：`given`・`none` の引用が、どの発言にも空白（`\s` と全角空白）を除いて含まれない項目名の一覧。
  - `case_graph(case: CaseInput, case_iri: URIRef) -> Graph`：`kos:BirthFiling` と `given` の三つ組だけ。日付は `xsd:date`、時刻は `xsd:time`、IRI の項目は `KD[f"{vocab}/{slug}"]`。

- Step 1：失敗するテストを書く。

```python
def test_omitted_field_is_unknown(onto):
    c = parse_case_input({"childBirthDate": {"status": "given", "value": "2024-04-01", "quote": "4月1日生まれ"}}, onto)
    assert "motherBirthDate" in c.unknown_fields and "childBirthDate" not in c.unknown_fields

def test_none_and_unknown_make_no_triples(onto):
    c = parse_case_input({"motherPrevMarriageEndDate": {"status": "none", "quote": "前婚はない"}}, onto)
    g = case_graph(c, KCASE.t1)
    assert (KCASE.t1, KOS.motherPrevMarriageEndDate, None) not in g
    assert "motherPrevMarriageEndDate" not in c.unknown_fields

def test_list_complete_flag(onto):
    args = {"attachedDocument": {"status": "given", "items": ["DOC-BIRTH-CERTIFICATE"], "complete": False, "quote": "出生証明書あり"}}
    assert "attachedDocument" not in parse_case_input(args, onto).complete_lists

def test_enum_rejected(onto):
    with pytest.raises(CaseInputError, match="notifierRole"):
        parse_case_input({"notifierRole": {"status": "given", "value": "ROLE-UNKNOWN", "quote": "x"}}, onto)

@pytest.mark.parametrize("utterances,bad", [
    (["4月 1日 生まれ"], []), (["前の話", "4月1日生まれ"], []), (["5月生まれ"], ["childBirthDate"]),
])
def test_quote_check(onto, utterances, bad):
    c = parse_case_input({"childBirthDate": {"status": "given", "value": "2024-04-01", "quote": "4月1日生まれ"}}, onto)
    assert check_quotes(c, utterances) == bad

def test_case_graph_matches_fixture_base(onto):
    # tests/fixtures/birth_cases/cases.json の base を given で渡すと、test_birth_rules.build_case と同じ三つ組になる
```

（列挙の短い ID の実際の綴りは `short_id(KD["document/birth-certificate"])` で確かめて、テストに書く。）

- Step 2：`uv run pytest tests/test_case_input.py -v` で FAIL を確かめる。
- Step 3：実装する。フィクスチャ `onto` は `load_ontology(ROOT / "ontology")` を `scope="session"` で `tests/conftest.py` に足す（以降のタスクも使う）。
- Step 4：PASS を確かめる。
- Step 5：コミット：`feat: 事案の入力を 3 つの状態で解釈し、引用を照合する`

### Task 2: ルールの使う入力と、適用されるルール

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/rule_inputs.py`
- Test: `tests/test_rule_inputs.py`

**Interfaces:**

- Consumes: `CASE_FIELDS`（Task 1）、`derive.DERIVED_VALUES`（`DerivedDef.output` と `DerivedDef.inputs`）

- Produces:

  - `rule_inputs(rules: Graph) -> dict[URIRef, frozenset[str]]`：ルール（`kos:JudgmentRule`）ごとに、`kos:shape` から辿れるシェイプ（入れ子の property shape、`sh:path`、`sh:sparql` の `sh:select` の文字列）に現れる `kos:` のローカル名を集め、派生値は `DERIVED_VALUES` の入力に置き換え、`CASE_FIELDS` の名前だけを残す。SPARQL の文字列からは `kos:(\w+)` と完全な IRI の両方を拾う。
  - `applicable_rules(rules: Graph, ontology: Graph, birth: date | None) -> frozenset[URIRef]`：`kos:underVersion` が無いルールは常に適用。版があるルールは、どれかの版で `validFrom <= birth`（無ければ制限なし）かつ `birth < validUntil`（無ければ制限なし）のとき適用。`birth` が None なら版のあるルールは適用しない。

- Step 1：失敗するテストを書く。14 ルールすべての期待値を表にする。下の 6 つは仕様から決まる。残りはシェイプを読んで決め、表に書いてからテストを流す（ルールを変えたら落ちるようにするため）。

```python
EXPECTED = {
    "RULE-BIRTH-FILING-PERIOD": {"childBirthDate", "filingDate"},
    "RULE-BIRTH-MOTHER-AGE": {"motherBirthDate", "childBirthDate"},
    "RULE-BIRTH-SCHOOL-AGE": {"childBirthDate", "filingDate"},
    "RULE-BIRTH-FAMILY-REGISTER": {"familyRegisterExists"},
    "RULE-BIRTH-ADDRESS": {"addressExists"},
    "RULE-BIRTH-BIRTH-CERTIFICATE": {"attachedDocument"},
    # 残り 8 ルールをシェイプから決めて書く
}


def test_rule_inputs_real_rules(rules):
    got = {short_id(r): v for r, v in rule_inputs(rules).items()}
    assert got == EXPECTED


@pytest.mark.parametrize(
    "birth,manual,current",
    [
        (date(2024, 3, 31), True, False),
        (date(2024, 4, 1), False, True),
    ],
)
def test_applicable_rules_boundary(rules, onto, birth, manual, current):
    a = applicable_rules(rules, onto, birth)
    assert (KD["rule/birth/legitimacy-manual"] in a) == manual
    assert (KD["rule/birth/legitimacy-current"] in a) == current
    assert KD["rule/birth/filing-period"] in a
```

- Step 2：FAIL を確かめる。
- Step 3：実装する。`rules` のフィクスチャを `tests/conftest.py` に足す（`scope="session"`）。
- Step 4：PASS を確かめる。
- Step 5：コミット：`feat: ルールの使う入力と、出生日で適用されるルールを決める`

### Task 3: 判定の後処理

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/assess.py`
- Test: `tests/test_assess.py`

**Interfaces:**

- Consumes: `judge.judge`・`Judgment`・`Finding`・`SEVERITY_ORDER`・`BIRTH_REQUIRED_INPUTS`、`CaseInput`・`case_graph`（Task 1）、`rule_inputs`・`applicable_rules`（Task 2）

- Produces:

  - `@dataclass(frozen=True) Assessment(decision: str, has_unconfirmed: bool, unconfirmed: tuple[str, ...], findings: tuple[Finding, ...], info: tuple[Finding, ...], unevaluated: dict[URIRef, tuple[str, ...]], applicable: frozenset[URIRef], provisional_decision: str | None, judgment: Judgment)`。
    - `findings`：適用され、評価できたルールの指摘のうち `kos:Info` 以外（暫定も含む。暫定かは `Finding.provisional`）。
    - `info`：`kos:Info` の指摘（評価できたもの）。
    - `unevaluated`：適用されるルールのうち、使う入力に未確認がある → その未確認の項目名。
  - `assess(case: CaseInput, case_iri: URIRef, ontology: Graph, rules: Graph, inputs: dict[URIRef, frozenset[str]]) -> Assessment`。未確認＝`case.unknown_fields` ∪ `judgment.missing_inputs` のローカル名。ただし `iri_list` の項目は、`complete_lists` に無ければ未確認とみなす（一覧に無いものを「無い」と言えないため）。
  - 判定の決め方（§5.1.1）：暫定でない `findings` の最も重いもの（`SEVERITY_ORDER`、値は `reject` などの小文字始まり）→ 無ければ `unevaluated` があれば `pending` → 無ければ `acceptable`。`has_unconfirmed` は未確認が 1 つでもあるか。`provisional_decision` は暫定の指摘だけで見た判定（無ければ None）。

- Step 1：失敗するテストを書く（事案は Task 1 の `parse_case_input` で、`cases.json` の `base` を `given`・`complete: true` にしたものから作るヘルパー `full_case(**changes)` を使う）。

```python
def test_full_base_case_is_acceptable(onto, rules, inputs):
    assert assess(full_case(), KCASE.t1, onto, rules, inputs).decision == "acceptable"


def test_unconfirmed_document_does_not_raise_inquiry(onto, rules, inputs):
    a = assess(full_case(attachedDocument=None), KCASE.t1, onto, rules, inputs)  # None = 省く
    assert not any(short_id(f.rule) == "RULE-BIRTH-BIRTH-CERTIFICATE" for f in a.findings)
    assert KD["rule/birth/birth-certificate"] in a.unevaluated
    assert a.decision == "pending"


def test_confirmed_missing_document_raises_inquiry(onto, rules, inputs):
    a = assess(
        full_case(
            attachedDocument={"status": "given", "items": [], "complete": True, "quote": "添付なし"}
        ),
        ...,
    )
    assert a.decision == "needsInquiry"


def test_finding_with_unconfirmed_keeps_severity(onto, rules, inputs):
    a = assess(full_case(filingDate="2026-11-20", motherBirthDate=None), ...)
    assert a.decision == "additionalProcedure" and a.has_unconfirmed


def test_info_is_separated(onto, rules, inputs):
    # 2024-04-01 生まれで、手順書と現行で嫡出の結論が分かれる事案（cases.json の該当事案を使う）
    a = assess(...)
    assert a.info and all(f.outcome == KOS.Info for f in a.info)
    assert all(f.outcome != KOS.Info for f in a.findings)
```

- Step 2：FAIL を確かめる。
- Step 3：実装する。`inputs` のフィクスチャは `rule_inputs(rules)` を `conftest.py` に足す。
- Step 4：PASS を確かめる。`tests/test_birth_rules.py` も流し、既存の判定が変わっていないことを確かめる。
- Step 5：コミット：`feat: 未確認の項目を使うルールを評価できずにし、判定保留を返す`

### Task 4: フローの形と状態

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/flow.py`
- Test: `tests/test_flow.py`

**Interfaces:**

- Consumes: `Assessment`（Task 3）、`short_id`

- Produces:

  - `flow_shape(ontology: Graph, business: str) -> dict`：`{"business": "birth", "label": …, "steps": [{"id": "BIRTH-S1", "number": 1, "label": …, "items": [Item…]}]}`。`Item = {"id", "label", "itemLabel", "kind": "check"|"task", "conditions": [label…], "children": [Item…]}`。並びは `kos:stepNumber`、`kos:itemOrder`。
  - `BUSINESSES = ("birth", "marriage", "divorce", "death", "certificate")`。
  - `NodeState`（`str` の Enum）：`finding`・`unevaluated`・`human`・`passed`・`referenced`・`none`。優先度 `finding > unevaluated > human > passed > referenced > none`。
  - `case_states(assessment: Assessment, rules: Graph, ontology: Graph) -> dict[str, dict]`：審査項目の短い ID →`{"state", "outcome"?, "badges": [...], "reason"?}`。
    - 適用されるルールで指摘 → `finding`（`outcome` は最も重いもの）。
    - 適用されるルールが `unevaluated` → `unevaluated`（`reason` に未確認の項目のラベル）。
    - 適用されるルールがあり、どれも指摘も未評価も無い → `passed`。
    - 適用されるルールが無い（`kos:Info` だけのルール、または適用外の版だけ）ものは状態に数えない。
    - ルールの無い出生届の審査項目（`kos:ReviewCheck` で `kos:implementsCheck` に指されない）→ `human`。
    - バッジ：`info`（`kos:Info` の指摘がある）、`provisional`、版（`manual`／`current`。適用されるルールの `kos:underVersion` の `kos:versionStatus`）。
  - `merge_states(case: dict[str, dict], referenced: Iterable[str]) -> dict[str, dict]`：参照は、状態が無い（`none`）ノードだけ `referenced` にする。
  - `step_states(shape: dict, states: dict[str, dict]) -> dict[str, str]`：工程の状態は、属する項目（入れ子を含む）の最も優先度の高い状態。
  - `replay(events: Sequence[dict], initial_case: dict[str, dict]) -> dict[str, dict]`：イベントの `flow` フィールド（`{"case_states": {...}}` は置き換え、`{"referenced": [...]}` は追加）を順に適用し、最後に `merge_states` した結果。
  - `pick_business(ids: Iterable[str]) -> str`：短い ID の接頭辞（`BIRTH-` など）を数え、最も多い業務。同数なら `BUSINESSES` の順。

- Step 1：失敗するテストを書く。

```python
def test_birth_flow_shape(onto):
    s = flow_shape(onto, "birth")
    assert [st["number"] for st in s["steps"]] == [1, 2, 3, 4, 5, 6, 7]
    assert len(s["steps"][1]["items"]) == 13

def test_name_check_is_human(onto, rules, inputs):
    st = case_states(assess(full_case(), …), rules, onto)
    assert st["BIRTH-S2-I4"]["state"] == "human"   # 子の氏名（ルールなし）

@pytest.mark.parametrize("birth", ["2024-03-31", "2024-04-01"])
def test_legitimacy_color_uses_applicable_rule(onto, rules, inputs, birth):
    # 適用される版のルールで指摘なし、手順書と現行で結論が違う事案 → passed ＋ info バッジ
    st = case_states(...)["BIRTH-S2-I5"]
    assert st["state"] == "passed" and "info" in st["badges"]

def test_unevaluated_reason(onto, rules, inputs):
    st = case_states(assess(full_case(motherBirthDate=None), …), rules, onto)
    assert st["BIRTH-S2-I8"]["state"] == "unevaluated" and "母の生年月日" in st["BIRTH-S2-I8"]["reason"]

def test_step_state_is_worst_item(onto):
    ...

def test_replay_second_judge_replaces_case_states():
    ev = [{"flow": {"case_states": {"A": {"state": "finding"}}}},
          {"flow": {"referenced": ["B"]}},
          {"flow": {"case_states": {"A": {"state": "passed"}}}}]
    out = replay(ev, {})
    assert out["A"]["state"] == "passed" and out["B"]["state"] == "referenced"

def test_pick_business():
    assert pick_business(["MARRIAGE-S7", "BIRTH-S7", "MARRIAGE-S2-I4"]) == "marriage"
```

（`BIRTH-S2-I4` が子の氏名か、`BIRTH-S2-I8` が母の生年月日かは、`describe` で確かめてからテストに書く。）

- Step 2：FAIL を確かめる。
- Step 3：実装する。
- Step 4：PASS を確かめる。
- Step 5：コミット：`feat: 手順書のフローの形と、判定から決まるノードの状態`

### Task 5: 問い合わせのツール

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/tools.py`
- Modify: `src/semantica_agent/settings.py`（`Settings` に `agent_model: str`（`AGENT_MODEL`、既定 `claude-sonnet-5-5`）、`agent_max_turns: int = 20`、`web_port: int`（`WEB_PORT`、既定 8765、整数でなければ `ConfigError`）、`sparql_timeout_s: float = 10.0`、`trace_root: Path = Path("output/traces")` を足す）
- Test: `tests/test_tools.py`、`tests/test_settings.py`（追記）

**Interfaces:**

- Consumes: `short_id`・`iri_from_short_id`、`turtle_io.load_ontology`

- Produces:

  - `@dataclass Knowledge(ontology: Graph, rules: Graph, inputs: dict[URIRef, frozenset[str]], cq_dir: Path)`：起動時に 1 回作る読み取り専用の知識。`Knowledge.load(root: Path) -> Knowledge`。
  - `@dataclass ToolResult(payload: dict, nodes: list[str], flow: dict)`：`payload` は LLM に返す JSON、`nodes` は触れたノードの短い ID、`flow` はフローへの反映（`{"referenced": nodes}` か `{"case_states": …}`）。
  - `search_nodes(k: Knowledge, text: str, business: str | None = None, cls: str | None = None) -> ToolResult`：`rdfs:label` の部分一致、最大 20 件。
  - `describe_node(k: Knowledge, node_id: str) -> ToolResult`：§5 の表の項目。存在しない ID は `ToolError`。
  - `run_cq(k: Knowledge, number: int) -> ToolResult`、`CQ_TITLES: dict[int, str]`（各 `.rq` の 1 行目から作る）。
  - `run_sparql(k: Knowledge, query: str, timeout_s: float) -> ToolResult`（async）：SELECT 以外と `\bSERVICE\b`（大文字小文字を無視）は `ToolError`。`anyio.to_thread.run_sync` と `anyio.fail_after` で時間を区切る。上限を超えたら `ToolError("時間の上限…")`（処理中のスレッドは捨てる。仕様の上限の意図はエージェントを止めないこと）。結果は最大 200 行、IRI は短い ID に直す。
  - 行の中の IRI のうち `KD` のものを `nodes` に入れる。

- Step 1：失敗するテストを書く。

```python
def test_search_nodes_finds_waiting_period(knowledge):
    r = search_nodes(knowledge, "待婚期間")
    assert any(n.startswith("MARRIAGE-S2") for n in r.nodes)

def test_describe_node_has_sources(knowledge):
    r = describe_node(knowledge, "BIRTH-S2-I11")
    assert r.payload["sources"] and r.payload["provisions"]

def test_run_cq2_references_step7_of_four_businesses(knowledge):
    r = run_cq(knowledge, 2)
    assert {"BIRTH-S7", "MARRIAGE-S8", "DIVORCE-S7", "DEATH-S7"} <= set(r.nodes)

@pytest.mark.parametrize("q", ["INSERT DATA { <a> <b> <c> }", "SELECT * WHERE { SERVICE <http://x> { ?s ?p ?o } }"])
async def test_run_sparql_rejects(knowledge, q):
    with pytest.raises(ToolError):
        await run_sparql(knowledge, q, 10)

async def test_run_sparql_limits_rows(knowledge):
    r = await run_sparql(knowledge, "SELECT ?s WHERE { ?s ?p ?o }", 10)
    assert len(r.payload["rows"]) == 200 and r.payload["truncated"]

async def test_run_sparql_timeout(knowledge, monkeypatch):
    # 重い処理の代わりに Graph.query を遅くして、0.1 秒で ToolError になる
```

- Step 2：FAIL を確かめる。
- Step 3：実装する（`knowledge` のフィクスチャを `conftest.py` に、`scope="session"`）。
- Step 4：PASS を確かめる。
- Step 5：コミット：`feat: オントロジーへの問い合わせのツール（検索・詳細・CQ・SPARQL）`

### Task 6: 判定のツールと、回答の主張の検証

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/claims.py`
- Modify: `src/semantica_agent/tools.py`
- Test: `tests/test_claims.py`、`tests/test_tools.py`（追記）

**Interfaces:**

- Consumes: Task 1〜5

- Produces:

  - `@dataclass SessionState(session_id: str, utterances: list[str], turn: int, last_assessment: Assessment | None, last_case: CaseInput | None, last_case_states: dict[str, dict], referenced_this_turn: set[str], judge_calls: int)`。`new_session(session_id: str) -> SessionState`。
  - `judge_birth_case(k: Knowledge, s: SessionState, args: dict) -> ToolResult`：`parse_case_input` → `check_quotes`（違反があれば `ToolError`、メッセージに項目名）→ `assess`（事案の IRI は `KCASE[f"{session_id}-{turn}-{judge_calls}"]`）→ `case_states`。`s.last_*` を更新する。`payload` は判定・未確認の項目（ラベル付き）・評価できなかったルール・暫定の判定・指摘（ルール・審査項目・判定の種類・版・メッセージ・値・暫定）・参考の指摘。`flow` は `{"case_states": …}`。
  - `@dataclass(frozen=True) Claim(text: str, kind: Literal["fact","rule","speculation"], nodes: tuple[str, ...], downgraded_reason: str | None = None)`。
  - `verify_claims(raw: list[dict], k: Knowledge, s: SessionState) -> list[Claim]`（`claims.py`）：§5.2 のとおり。存在しない ID は外す。`rule` は `s.last_assessment` の `findings`・`info` のルールか審査項目の短い ID を含む。`fact` は `s.referenced_this_turn` か、このターンの判定のノードを含む。満たさなければ `speculation` に下げ、理由を書く。
  - `submit_answer(k: Knowledge, s: SessionState, args: dict) -> ToolResult`：`payload = {"answer": str, "claims": [Claim を dict に]}`。

- Step 1：失敗するテストを書く。

```python
def test_judge_tool_rejects_bad_quote(knowledge):
    s = new_session("t"); s.utterances.append("4月1日生まれです")
    with pytest.raises(ToolError, match="filingDate"):
        judge_birth_case(knowledge, s, {"filingDate": {"status": "given", "value": "2024-04-10", "quote": "10日に届出"}, ...})

def test_judge_tool_pending_lists_unconfirmed(knowledge):
    s = session_with("4月1日生まれ、母が今日届出")
    r = judge_birth_case(knowledge, s, minimal_args())
    assert r.payload["decision"] == "pending" and "motherBirthDate" in r.payload["unconfirmed"]

def test_rule_claim_without_finding_is_downgraded(knowledge):
    s = judged_session(...)   # 指摘は届出期間だけ
    c = verify_claims([{"text": "住所が無い", "kind": "rule", "nodes": ["RULE-BIRTH-ADDRESS"]}], knowledge, s)
    assert c[0].kind == "speculation" and c[0].downgraded_reason

def test_fact_claim_needs_referenced_node(knowledge):
    s = new_session("t"); s.referenced_this_turn = {"BIRTH-S2-I11"}
    ok, bad = verify_claims([{"text": "a", "kind": "fact", "nodes": ["BIRTH-S2-I11"]},
                             {"text": "b", "kind": "fact", "nodes": ["BIRTH-S2-I1"]}], knowledge, s)
    assert ok.kind == "fact" and bad.kind == "speculation"

def test_unknown_node_id_is_dropped(knowledge): ...
```

- Step 2：FAIL を確かめる。
- Step 3：実装する。
- Step 4：PASS を確かめる。
- Step 5：コミット：`feat: 出生届の判定のツールと、回答の主張の検証`

### Task 7: トレースの記録と保存

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/trace.py`、`src/semantica_agent/schemas/trace.schema.json`
- Modify: `pyproject.toml`（`jsonschema` を依存に明示）
- Test: `tests/test_trace.py`

**Interfaces:**

- Consumes: `flow.replay`・`flow.pick_business`、`Assessment`、`Claim`、`semantica.context.ContextGraph`

- Produces:

  - `@dataclass TraceRecorder(session_id: str, turn: int, question: str, model_requested: str, prompt_path: Path, prompt_hash: str, ontology_info: dict, initial_case_states: dict)`。
    - `add(type: str, **fields) -> dict`：`seq`・`time` を付けたイベントを積み、そのイベントを返す（画面へ流すのに使う）。type は §6.2 の 6 つと `error`。ツールのイベントは `tool`・`args`・`result`・`nodes`・`flow` を持つ。
    - `finish(answer: dict | None, assessment: Assessment | None, case: CaseInput | None, model_responded: str | None, status: Literal["ok","error"]) -> dict`：§6.2 の JSON。`flow` は `replay(events, initial_case_states)`、`business` は `pick_business`（判定があれば `birth`）。
  - `validate_trace(trace: dict) -> None`：`trace.schema.json` で検証し、違反は `TraceError`。
  - `save_trace(trace: dict, root: Path) -> Path`：`<root>/<session_id>/<turn:03d>.json` と `report.md`、`decisions.json`（`ContextGraph.save_to_file`）、`prov.ttl` を書く。書く前に `validate_trace`。
  - `record_decision(cg: ContextGraph, trace: dict) -> str | None`：判定があるときだけ、§6.1 の引数で呼ぶ（confidence は未確認も暫定も無ければ 1.0、それ以外 0.5）。
  - `ontology_info(root: Path) -> dict`：`{"commit": str | None, "dirty": bool | None, "version_info": str}`。git が使えなければ `commit` と `dirty` を None にし、理由をログに出す。
  - `render_report(trace: dict) -> str`：質問、判定と未確認、指摘ごとの根拠（ルール → 審査項目 → 出典 → 条文の版）、主張（種類・ノード・下げた理由）、イベントの一覧。

- Step 1：失敗するテストを書く。

```python
def test_finished_trace_is_valid(tmp_path):
    t = sample_recorder().finish(...)
    validate_trace(t)
    p = save_trace(t, tmp_path)
    assert (
        p.name == "001.json"
        and (p.parent / "report.md").exists()
        and (p.parent / "prov.ttl").exists()
    )


def test_replay_matches_saved_flow():
    t = sample_recorder_with_two_judges().finish(...)
    assert replay(t["events"], t["flow_initial"]) == t["flow"]


def test_invalid_trace_is_rejected():
    with pytest.raises(TraceError):
        validate_trace({"trace_version": "1"})


def test_record_decision_confidence():
    cg = ContextGraph()
    record_decision(cg, trace_with(decision="pending", unconfirmed=["motherBirthDate"]))
    # 記録された判断の confidence が 0.5、outcome が "pending"


def test_no_secret_in_trace(monkeypatch):
    monkeypatch.setenv("SOME_TOKEN", "secret-xyz")
    assert "secret-xyz" not in json.dumps(sample_recorder().finish(...))
```

- Step 2：FAIL を確かめる。
- Step 3：実装する。
- Step 4：PASS を確かめる。
- Step 5：コミット：`feat: トレースを記録し、JSON・報告・判断記録・PROV-O に保存する`

### Task 8: エージェント（SDK の組み立てと 1 ターンの実行）

**スキル：** superpowers:test-driven-development。Agent SDK の使い方は `code.claude.com/docs/en/agent-sdk` を見る（`claude-api` スキルは使わない）。

**Files:**

- Create: `src/semantica_agent/agent.py`、`src/semantica_agent/prompts/agent.md`
- Test: `tests/test_agent.py`

**Interfaces:**

- Consumes: Task 5〜7、`settings.Settings`

- Produces:

  - `MCP_SERVER = "koseki"`、`TOOL_NAMES = ("judge_birth_case", "search_nodes", "describe_node", "run_cq", "run_sparql", "submit_answer")`、`allowed_tool_names() -> list[str]`（`mcp__koseki__<name>`）。
  - `build_options(k: Knowledge, s: SessionState, settings: Settings, recorder_ref: Callable[[], TraceRecorder], today: date) -> ClaudeAgentOptions`：§4.1 のとおり（`tools=[]`、`setting_sources=[]`、`mcp_servers={"koseki": create_sdk_mcp_server(...)}`、`hooks` に `PreToolUse`・`PostToolUse`）。ツールの包みは、`ToolResult` を `recorder.add("tool_result", …)` に積み、`s.referenced_this_turn` を更新し、`{"content": [{"type": "text", "text": json}]}` を返す。`ToolError` は `{"content": …, "is_error": True}` にして、`error` ではなく `tool_result`（`is_error: true`）として積む。フックは呼び出しの開始時刻を `tool_call` のイベントに積む。
  - `class AgentSession`：`__init__(k, settings, client_factory=ClaudeSDKClient, session_id: str | None = None)`。`async ask(text: str) -> AsyncIterator[dict]`：`s.utterances` に足し、ターンを始め、`client.query(text)` → `client.receive_response()` のメッセージを `assistant_text`・`thinking` のイベントにし、積んだイベントを順に yield する。最後に `finish` → `save_trace` → `record_decision` し、`{"type": "turn_end", "trace_path": …, "trace": …}` を yield する。`async close()`。
  - `submit_answer` が呼ばれなければ、最後の `assistant_text` を回答とし、主張は `[Claim(text, "speculation", (), "submit_answer が呼ばれなかった")]`。
  - SDK の例外と `AssistantMessage.error` は `error` のイベントにし、`status="error"` で保存してから例外を出し直さず `turn_end` を返す（画面に出すため）。
  - プロンプト：§4.2 の 5 点。`{today}` を差し込む。ツールの説明（`tool` の description）に、CQ の番号と問いの一覧、列挙値の意味を書く。

- Step 1：失敗するテストを書く。SDK は `client_factory` に偽のクライアントを渡して差し替える（`query` で受けた文に応じて、決めた順に `AssistantMessage`（`ToolUseBlock` を含む）と `ResultMessage` を返し、ツールは包んだ関数を直接呼ぶ）。

```python
async def test_turn_records_tool_events_and_saves(tmp_path, knowledge):
    sess = AgentSession(knowledge, settings_for(tmp_path), client_factory=fake_client(script_judge_then_answer))
    events = [e async for e in sess.ask("2026年11月2日生まれ、11月20日に母が届出")]
    types = [e["type"] for e in events]
    assert types[0] == "user" and "tool_result" in types and types[-1] == "turn_end"
    trace = events[-1]["trace"]
    assert trace["judgment"]["decision"] in {"additionalProcedure", "pending"}
    assert (tmp_path / sess.session_id / "001.json").exists()

async def test_turn_without_submit_answer(...):
    trace = (await last_event(sess.ask("…")))["trace"]
    assert trace["answer"]["claims"][0]["kind"] == "speculation"

async def test_sdk_error_is_saved(...):
    trace = ...
    assert trace["status"] == "error" and any(e["type"] == "error" for e in trace["events"])

def test_options_disable_builtin_tools(knowledge):
    o = build_options(...)
    assert o.tools == [] and o.setting_sources == [] and set(o.allowed_tools) == set(allowed_tool_names())

async def test_second_turn_sees_previous_utterance(...):
    # 1 ターン目の発言の引用が、2 ターン目の judge_birth_case で通る
```

- Step 2：FAIL を確かめる。
- Step 3：実装する。
- Step 4：PASS を確かめる。
- Step 5：コミット：`feat: Agent SDK の審査支援エージェントと、ターンごとのトレース`

### Task 9: Web サーバー

**スキル：** superpowers:test-driven-development

**Files:**

- Create: `src/semantica_agent/web.py`
- Modify: `pyproject.toml`（`fastapi`、`uvicorn` を依存に足して `uv sync`）
- Test: `tests/test_web.py`

**Interfaces:**

- Consumes: `Knowledge`、`AgentSession`、`flow_shape`・`BUSINESSES`、`describe_node`、`trace_root`

- Produces:

  - `create_app(k: Knowledge, settings: Settings, session_factory: Callable[[], AgentSession]) -> FastAPI`。
  - API：`GET /`（`static/index.html`）、`GET /static/*`、`GET /api/flow/{business}`（`flow_shape`、無い業務は 404）、`POST /api/sessions` → `{"session_id"}`、`POST /api/sessions/{id}/messages`（本文 `{"text"}`、応答は `text/event-stream` で `ask` のイベントを `data: <json>\n\n`。処理中なら 409、無い相談は 404）、`GET /api/nodes/{short_id}`（`describe_node` の `payload`、無ければ 404）、`GET /api/traces`（セッション・ターン・質問・判定の一覧）、`GET /api/traces/{session_id}/{turn}`。
  - `main() -> int`：`load_settings` → `Knowledge.load` → 整合性シェイプで検証（`build.stage_validate` と同じ検証を関数に切り出して使う：`validate_integrity(root: Path) -> tuple[bool, str]` を `build.py` に足し、`stage_validate` もそれを使う）→ 失敗なら理由を出して 1 を返す → `uvicorn.run(app, host="127.0.0.1", port=settings.web_port)`。`python -m semantica_agent.web` で動く。

- Step 1：失敗するテストを書く（TestClient、偽の `AgentSession` は決めたイベントを yield する）。

```python
def test_flow_endpoint(client):
    assert [s["number"] for s in client.get("/api/flow/birth").json()["steps"]] == [1, 2, 3, 4, 5, 6, 7]

def test_message_streams_events(client):
    sid = client.post("/api/sessions").json()["session_id"]
    with client.stream("POST", f"/api/sessions/{sid}/messages", json={"text": "質問"}) as r:
        events = [json.loads(l[5:]) for l in r.iter_lines() if l.startswith("data:")]
    assert events[-1]["type"] == "turn_end"

def test_busy_session_returns_409(...): ...
def test_unknown_session_404(client): ...
def test_traces_list_and_get(client, saved_trace): ...
def test_main_stops_on_integrity_failure(monkeypatch, tmp_path):
    assert web.main(["--root", str(broken_root)]) == 1

def test_binds_localhost_only(monkeypatch):
    # uvicorn.run を差し替え、host == "127.0.0.1" を確かめる
```

- Step 2：FAIL を確かめる。
- Step 3：実装する。
- Step 4：PASS を確かめる。`uv run pytest -m "not llm"` も流す。
- Step 5：コミット：`feat: 審査支援の Web サーバー（SSE で処理の進みを送る）`

### Task 10: 画面

**スキル：** superpowers:test-driven-development（サーバー側の配信のテストだけ）。画面の見た目は Step 4 で実際に起動して確かめる。

**Files:**

- Create: `src/semantica_agent/web/static/index.html`、`app.js`、`style.css`
- Test: `tests/test_web.py`（追記）

**Interfaces:**

- Consumes: Task 9 の API。イベントの `flow`、`turn_end` の `trace`（`flow`・`judgment`・`case`・`answer`）。

- Produces：§7.3 の画面。

  - 左：質問の入力と送信、会話（職員の発言、回答の本文）、上部にコードの判定（判定の日本語名、「ほかに未確認あり」、暫定の判定）、主張（種類の印「ルール」「事実」「推測」、ノードのリンク、下げた理由）、入力の解釈の表（項目・状態・値・引用・推測の印）。「新しい相談」のボタン。
  - 右上：「AIの処理」のイベントの列。押すと `replay` と同じ規則（`case_states` は置き換え、`referenced` は追加、最後に合成）で、そのイベントまでの状態を描く。JS の合成は Python の `flow.replay` と同じ規則だけを持ち、状態そのもの（`case_states`）はサーバーが送ったものを使う。
  - 右中：業務のタブと、工程（横並び）・項目（縦の入れ子）。状態ごとの色（§7.2）、工程は項目の最も重い状態。バッジ（参考・暫定・版）。
  - 右下：ノードの詳細（`/api/nodes/{id}`）。
  - 「過去のトレース」の一覧から開いて再生する。
  - 色は CSS の変数で持ち、`prefers-color-scheme` の暗い配色にも対応する。

- Step 1：失敗するテストを書く：`GET /` が 200 で、`app.js` と `style.css` を参照し、外部の URL（`http://`・`https://`）を含まない。`GET /static/app.js` が 200。

- Step 2：FAIL を確かめる。

- Step 3：実装する。

- Step 4：確認する。保存済みのトレースを `tests/fixtures/traces/` に 1 つ置き（Task 9 の偽のセッションで作ったもの）、`uv run python -m semantica_agent.web` で起動して `/api/traces` からそれを開き、色とイベントの再生が描かれることをブラウザで見る。ブラウザを使えないときは、その旨を記録し、Task 11 でユーザーに見てもらう。

- Step 5：コミット：`feat: フローの色付けと処理の再生を見せる画面`

### Task 11: 実際に動かす（LLM を呼ぶ）と、使い方の記載

**スキル：** superpowers:verification-before-completion。LLM を呼ぶ前に、回数をユーザーに伝えて確認を取る（CLAUDE.md）。

**Files:**

- Create: `tests/test_agent_e2e.py`（`llm` マーカー）

- Modify: `README.md`（「審査支援エージェントを使う」の節）

- Step 1：`llm` のテストを書く：(1) `cases.json` の 1 事案（届出期間を過ぎたもの）を日本語で全項目言う → トレースが Schema に合い、判定が正解表と一致し、`judge_birth_case` が呼ばれている。(2)「戸籍法施行規則第48条が関わる工程は？」→ トレースの `flow` で 4 業務の工程 7 の項目のどれかが `referenced`。

- Step 2：ユーザーに「`llm` テスト 2 件で、エージェントのターンが 2 回（ツールの呼び出しを含め、Pro の利用枠をその分使う）」と伝えて確認を取り、`uv run pytest -m llm tests/test_agent_e2e.py -v` を流す。

- Step 3：失敗したら superpowers:systematic-debugging で切り分ける（プロンプトの直しは `prompts/agent.md` だけ）。

- Step 4：`uv run python -m semantica_agent.web` を起動し、ユーザーに画面で 1 回質問してもらい、色付けと再生を見てもらう。

- Step 5：README に、起動の方法、質問の例（A と B）、色の意味、トレースの置き場所を書く。

- Step 6：`uv run ruff check .`、`uv run ruff format --check .`、`uv run pytest -m "not llm" --cov=src/semantica_agent` を流し、カバレッジが 80% 以上であることを確かめる。

- Step 7：コミット：`docs: 審査支援エージェントの使い方を追加`、`test: エージェントの E2E（llm）`

### 最後に

superpowers:requesting-code-review でブランチ全体を 1 回レビューし、指摘を直してから superpowers:finishing-a-development-branch で PR を作る（main へは PR で統合する）。
