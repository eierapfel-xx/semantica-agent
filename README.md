# semantica-agent

市区町村の窓口業務（戸籍届出など）の手順書を題材に、[semantica](https://github.com/semantica-agi/semantica) でオントロジーを作り、そのオントロジーを使うエージェントを Claude Agent SDK で作る。

## セットアップ

```bash
uv sync
uv run python -m semantica_agent.doctor   # 環境の確認
```

エージェントは Claude Code のログイン状態（Claude Pro）で動く。先に `claude` で一度ログインしておく。

開発の決まりは `AGENTS.md`（`CLAUDE.md` はそのシンボリックリンク）。

## 使い方（審査支援エージェント）

設計は `docs/specs/2026-11-17-agent-design.md`。エージェントは Claude Pro のログインで動き、質問 1 回ごとに Pro の利用枠を使う。

### 起動する

```bash
uv run python -m semantica_agent.web      # http://127.0.0.1:8765/ を開く
```

- モデルは `AGENT_MODEL`（既定 `claude-sonnet-5-5`）、ポートは `WEB_PORT`（既定 8765）。自分のマシンの `127.0.0.1` だけで待ち受ける。
- 起動時にオントロジーを整合性シェイプで検証し、違反があれば起動しない。

### 質問の例

- 事案の審査：「2026年11月2日生まれ。母が11月20日にB市で届出。本籍はA市。」
  - 言っていない項目は「未確認」として扱い、判定は「判定保留」になる。エージェントが聞き返すので、答えを足すと判定し直す。
  - 「出生証明書はありません」のように「無い」と言った項目だけを、無いものとして判定する。添付書類と記載事項は「これだけです」と言ったときだけ、一覧に無いものを無いとみなす。
- 手順・法令の問い合わせ：「戸籍法施行規則第48条が関わる工程は？」「待婚期間の審査は今も要る？」

### 画面の見方

- 左：質問と回答。上の「判定（コードの結果）」はルールの判定そのもので、LLM の文章とは別に出す。主張には根拠の種類（ルール／事実／推測）と根拠のノードが付く。根拠を確かめられなかった主張は推測に下がり、理由が出る。「入力の解釈」で、届出の内容をどう受け取ったか（値・引用・推測）を確かめられる。
- 右上「AIの処理」：ツールの呼び出しなどのイベントの列。押すと、その時点のフローの状態を表示する。
- 右中：手順書のフロー。色の意味は次のとおり。
  - 緑：通過
  - 赤・橙・黄・青緑：指摘（受理不可・補正・照会・追加の手続）
  - 灰の斜線：評価できず（入力が未確認）
  - 紫の枠：人の確認（ルールの無い審査項目）
  - 青の枠：参照
  - 印の「参考」は手順書と現行法で結論が違うこと、「暫定」は未承認の現行版に基づく指摘、「手順書時点」「現行」は適用した法の版を表す。
- 右下：ノードの詳細（手順書の頁と原文、条文の版、e-Gov の出典、ルール）。

### トレース

質問 1 回ごとに `output/traces/<相談>/<ターン>` に残る（git 管理外）。

- `.json`：入力、ツールの呼び出しと結果、触れたノード、判定、回答と主張の検証。形は `src/semantica_agent/agent/schemas/trace.schema.json`。
- `.md`：人が読む報告。
- `.prov.ttl`：PROV-O。
- `decisions.json`：semantica の判断記録。

画面の「過去のトレースを開く」で再生できる。

### エージェントのテスト

```bash
uv run pytest -m "not llm"                    # SDK を差し替えたテスト（Claude を呼ばない）
uv run pytest -m llm tests/test_agent_e2e.py  # 実際に Claude を呼ぶ（2 ターン分の利用枠を使う）
```

## 使い方（オントロジー）

設計は `docs/specs/2026-11-16-ontology-design.md`、生成の記録は `docs/notes/2026-11-16-ontology-generation.md`。オントロジーの本体は `ontology/` にあり（`ontology/generated/` は LLM の生のまま、レビュー前）、次の操作は LLM を呼ばない。

### 出生届を判定してみる

```bash
uv run python -m semantica_agent.build judge --case docs/examples/birth-late.ttl
```

判定（受理できない／補正／照会／追加の手続／指摘なし）と、指摘ごとの根拠（ルール → 審査項目 → 手順書の頁と原文 → 条文の版と e-Gov の出典）を表示する。`docs/examples/birth-late.ttl` を写して値を変えると、別の事案を試せる。

- 届書の続き柄は `"嫡出子"` か `"嫡出でない子"`、届書上の父は `"現在の夫"`・`"前の夫"`・`"記載なし"`。
- `kos:parentsMarriageDate` は、出生時に母が婚姻しているときのその婚姻の日（婚姻していなければ書かない）。前婚の解消日は `kos:motherPrevMarriageEndDate`、出生までの再婚は `kos:motherRemarriedBeforeBirth true`。
- 届出人は `<role/father>`・`<role/mother>`・`<role/cohabitant>`・`<role/physician>`・`<role/midwife>`・`<role/other-attendant>`・`<role/legal-representative>`。
- 必要な入力が欠けていると「欠けた入力」として表示される（そのとき指摘なしでも受理可とは限らない）。
- 試せる事案の例は `tests/fixtures/birth_cases/cases.json`（28 件。正解付き）にもある。

### オントロジーに問い合わせる（competency questions）

`ontology/cq/cq01.rq`〜`cq15.rq` に SPARQL がある（何を問うかは各ファイルの 1 行目）。

```bash
uv run python - <<'PY'
from pathlib import Path
from semantica_agent.turtle_io import load_ontology
g = load_ontology(Path("ontology"))
for row in g.query(Path("ontology/cq/cq06.rq").read_text()):  # 法改正の影響を受ける審査項目
    print(*row)
PY
```

### 検証とテスト

```bash
uv run python -m semantica_agent.build validate   # オントロジーの整合性（SHACL）
uv run pytest -m "not llm"                         # 判定の事案と CQ を含むテスト
```

### オントロジーを生成し直す（LLM を呼ぶ）

Claude Pro の利用枠を使う。段ごとに 1 回ずつ（インスタンスは業務ごとに 1 回）呼ぶ。モデルは `ONTOLOGY_GEN_MODEL`（例：`claude-sonnet-5-5`）で指定する。生成物は `ontology/generated/<段>/` に出るので、レビューして直したものを `ontology/` の所定の場所に置く（手順は仕様 §5.7）。

```bash
uv run python -m semantica_agent.build extract                 # PDF → data/extracted/rows.json（LLM なし）
uv run python -m semantica_agent.build schema                  # スキーマ
uv run python -m semantica_agent.build instances [--business birth]
uv run python -m semantica_agent.build instances --from-run <run_id>   # 保存済みの応答で検証し直す（LLM なし）
uv run python -m semantica_agent.build derived                 # 派生値の定義（LLM なし）
uv run python -m semantica_agent.build amendments              # 現行法の改正（e-Gov から条文を取得）
uv run python -m semantica_agent.build approve <短いID>... --by <確認者> --file ontology/law/amendments.ttl
uv run python -m semantica_agent.build integrity               # 整合性シェイプ
uv run python -m semantica_agent.build rules                   # 出生届の判定ルール
```

LLM の応答の生テキストは `data/generation/<run_id>/` に残る（git 管理外）。
