# semantica-agent 開発ガイド

市区町村の窓口業務（戸籍の出生・婚姻・離婚・死亡の届出、戸籍謄本等の交付）の手順書を題材に、[semantica](https://github.com/semantica-agi/semantica) でオントロジーを作り、そのオントロジーを使うエージェントを Claude Agent SDK で作るリポジトリ。題材の原本は `docs/domain/手順書.pdf`。

目的は、エージェントにオントロジーを持たせることが役に立つかを検証すること。想定する場面は**窓口職員の審査支援**で、届出の内容を受け取り、受理できるか・何が足りないかを根拠付きで返す。検証で特に見たいのは**トレーサビリティ**（なぜその結論になったか、AI がどう判断したかを後から辿れること）。

## 言語と範囲

- 回答、計画、仕様書、設計メモは日本語で書く。
- 作業対象はこのディレクトリ直下のファイルだけ。worktree で作業するときは `.claude/worktrees/<名前>/` 直下のプロジェクトだけを操作する。

## スキルの使い方

当てはまるスキルがあれば使う。ユーザーの指示はスキルより優先する。このプロジェクトで既定の動きを変えているもの：

- `superpowers:using-git-worktrees`：ユーザーから明示の指示があるときだけ使う。使わないときは feature ブランチを切ってその場で作業する。準備は「Git」の節の手順に従う。
- `superpowers:writing-plans`：計画は `docs/plans/YYYY-MM-DD-<feature>.md` に置く。
- `superpowers:executing-plans`：同じセッションで自分が全タスクを実装するときに使う。タスクの間で止まらず、レビューは最後にブランチ全体を 1 回行う。
- `superpowers:subagent-driven-development`：同じセッションで、独立したタスクをサブエージェントに分担させるときに使う。
- `superpowers:requesting-code-review`：SDD の各タスクの後、大きな機能が完成した後、main へのマージ前にレビューする。
- `claude-api`：このプロジェクトのエージェントは Claude Agent SDK で作る。`claude-api` スキルは Claude API（Client SDK）用で Agent SDK のコードは扱わないため、Agent SDK の使い方は公式ドキュメント（`code.claude.com/docs/en/agent-sdk`）を見る。
- スキルがリポジトリ全体のテストを求めたときは `uv run pytest` を流す（`llm` マーカーのテストは除く。理由は「テスト」の節）。

## 仕様と計画

- 複雑な変更、複数ファイルの改修、仕様の変更は、着手前に仕様と計画をファイルとして書く（Plan Mode は使わない）。仕様の正は `docs/specs/`。
- 仕様は `docs/specs/YYYY-MM-DD-<topic>.md`、計画は `docs/plans/YYYY-MM-DD-<feature>.md` に置く。サブディレクトリは切らない。
- 仕様と計画を書いたら人間に確認を取り、確認が済んでから実装を始める。
- 計画には、各タスクでどのスキルを使うかを書く。
- 実装の進捗（Task Ledger、実行中の決定）は、計画を実行するスキルが `.superpowers/sdd/<計画のファイル名>/progress.md` に記録する。計画ファイルのチェックボックスは付けない。これは git 管理外の使い捨てで、最終レビューが通るとスキルが消す。残す必要がある成果や決定は仕様書や `docs/` のメモにまとめる。

## コマンド

- 環境構築：`uv sync`
- 環境の確認：`uv run python -m semantica_agent.doctor`
- Lint：`uv run ruff check .`
- フォーマット：`uv run ruff format --check .`
- テスト：`uv run pytest -m "not llm"`
- semantica の CLI：`uv run semantica --help`
- semantica の MCP サーバー：`uv run semantica-mcp`（Claude Code からは `.mcp.json` で `semantica` として使える）

PreToolUse hook の `commit-guard` が次を行う：

- `git commit` の前に `ruff check`、`ruff format --check`、`pytest` を実行し、失敗したらコミットを止める。`pytest` は `tests/` を `-m "not slow and not llm"` で実行する。
- main への直接コミットを止める。
- main への push を止める（送り先を判定できない push も止める）。
- データや大容量ファイルがステージされていたらコミットを止める。閾値は `COMMIT_GUARD_MAX_FILE_MB`（既定 5MB）。`data/`・`output/` の配下と、`.parquet`・`.npy`・`.pkl`・`.sqlite` などの拡張子はサイズに関わらず止める。オントロジー（`ontology/` の `.ttl` 等）はコミットしてよい。意図的にコミットするときだけ `COMMIT_GUARD_ALLOW_LARGE=1` を付ける。

PostToolUse hook の `format-on-edit` が、編集した `.py` を `ruff format`、`.md` を `mdformat` で整形する。

## コーディング

- 既存のオブジェクトを破壊的に変更せず、新しいオブジェクトを作って返す。
- ファイルは 200〜400 行を目安に最大 800 行、関数は 50 行以内、ネストは 4 段以内。
- 値はハードコードせず、定数か設定にする。オントロジーの名前空間 URI は 1 か所で定義して使い回す。
- ログは `LOG_LEVEL` で制御し、既定は `INFO`。`DEBUG` には、トラブルシュートに十分な情報を残す。
- 例外を握り潰さない。外部データ（PDF、オントロジーファイル、設定、環境変数）は境界で検証し、失敗したら分かりやすいメッセージで止める。
- docstring は最小限にする（既存の慣習がある箇所はそれに合わせる）。
- オントロジーの書き方は `.claude/rules/ontology.md`、審査支援エージェントの書き方は `.claude/rules/agent.md`。

## テスト

- TDD で進める（テストを先に書き、失敗を確かめてから実装する）。
- テストを書くときの決まり（置き場所、マーカー、LLM の扱い、カバレッジ）は `.claude/rules/tests.md`。
- `llm` マーカーのテストは Claude を実際に呼び、Claude Pro の利用枠を消費する。既定では流さず、エージェントの動きを確かめたいときだけ `uv run pytest -m llm` で流す。

## 秘密情報

- エージェントは Claude Code のログイン（Claude Pro）で動かす。API キーは使わない。`ANTHROPIC_API_KEY` が環境にあるとログインより優先されて従量課金になるので、設定しない。
- Pro のログインで動かせるのは自分のマシンで自分が使う範囲だけ。他人に提供する形にするときは API キーへの切り替えを仕様で決める（Agent SDK のドキュメントの注記）。
- 他に秘密情報が要るときは `.env` か実行環境の環境変数に置き、コミットしない。必要な環境変数は起動時に確かめ、無ければ明確に失敗させる。
- `.claude/settings.json` の deny ルールで、`.env`（worktree の中も含む）は読めない。止まるのは Read ツールと `cat`・`grep` などの読み取りコマンドで、`python3 -c "open('.env')"` のようにスクリプトがファイルを開く経路は止まらない。この経路で秘密情報を表示しない。
- トークンをログ、エラーメッセージ、成果物に出さない。
- 露出が疑われたら作業を止め、露出箇所を除き（履歴に残った場合は手順を立てる）、シークレットをローテーションし、同じ漏えいが他に無いか点検する。

## Git

- ブランチ名は `feat/<slug>`、`fix/<slug>`、`chore/<slug>`。
- コミットは `<type>: <日本語の説明>`。type は `feat`、`fix`、`refactor`、`docs`、`test`、`chore`、`perf`、`ci`。
- PR は日本語のタイトルにし、変更の概要とテスト結果を書く。
- main へは直接コミットも push もしない（どちらも commit-guard が止める）。main への統合は PR を作って `gh pr merge` でマージする。`finishing-a-development-branch` では PR の選択肢を使う（ローカルでマージして push する経路は hook に止められる）。hook を迂回する手段（`gh api` で ref を直接作る等）は使わない。リモートが無い間は、ブランチをローカルに残してユーザーに統合方法を確認する。
- worktree で作業するように指示されたときは、Claude Code の `EnterWorktree`（場所は `.claude/worktrees/<名前>/`）で作る。worktree には git 管理外のファイルが入らないので、作業の前に次を行う。
  - `.env` と `data/`：worktree の直下に、本体の `.env` と `data/` へのシンボリックリンクを張る（`ln -s <本体のパス>/.env .env`、`ln -s <本体のパス>/data data`）。`.env` はコピーしない（deny ルールで読めないため）。`.gitignore` の `.env` と `/data` はリンクにも一致するので、未追跡ファイルにはならない。
  - 依存を `uv sync` で入れる。

## 開発の進め方

- 全体の流れは「手順書 → オントロジー（クラス・プロパティ・SHACL 制約）→ インスタンス（各業務の手順・審査項目・根拠法令）→ 審査支援エージェント → 検証」。各段の成果物はファイルとして残し、次の段はそのファイルを入力にする。
- 各段に着手する前に、仕様書（`docs/specs/`）でその段の設計を決めて確認を取る。

### オントロジーの生成

- オントロジーは LLM で生成する（ユーザーの決定）。semantica の `LLMOntologyGenerator` を使い、LLM には Claude Agent SDK を包んだ自作のプロバイダーを semantica のプロバイダー登録の仕組み（`semantica.semantic_extract.registry`）で差し込む。semantica 組み込みの `anthropic` プロバイダーは API キーが要るので使わない。
- 組み込みの生成プロンプトは英語の汎用のもので、手順書の表（区分・業務手順・備考の法令）を細かく取り出すには足りない。プロンプトは自前で用意し、仕様書で中身を決める。
- 生成結果はそのまま使わず、`ontology/` に Turtle で保存して差分をレビューし、SHACL 検証と competency questions の SPARQL テストを通す。生成に使ったプロンプト・モデル・入力（ページ）を生成物のメタデータに残す。
- オントロジーを変えたら、SHACL 検証と competency questions の SPARQL テストを通す。

### 審査支援エージェントとトレーサビリティ

- エージェントは Claude Agent SDK で作り、オントロジーへの問い合わせ（SPARQL、ルール推論、SHACL 検証）はツールとして渡す（SDK のカスタムツールか semantica の MCP サーバー）。
- トレーサビリティのために、1 回の審査ごとに「入力（届出の内容）→ 呼んだツールと引数 → 参照したオントロジー上のノード（業務・工程・審査項目・法令）→ 適用したルールと判定 → 結論」を記録として残す。記録には semantica の判断記録（`ContextGraph.record_decision` 等）と PROV-O の出典管理を使い、後から読める形（JSON と人が読む報告）で出力する。
- 答えの中で、オントロジーから引いた事実・ルールで判定したこと・LLM が補った推測を区別して示させる。根拠のノードを示せない主張は推測として扱う。
- エージェントの実際の呼び出しはローカルで行う（Claude Pro の利用枠を使う）。回数の多い評価を回すときは、事前に回数をユーザーに確認する。

### 検証

- 同じ審査ケースを「LLM＋手順書の文章」と「LLM＋オントロジー」で解かせて比べる。見るのは判定の正しさ、根拠の示しやすさ（トレーサビリティ）、同じ入力での答えのぶれ。
- オントロジーの強みが出そうな観点として、次をケースに含める。
  - 条件付きの判定：嫡出子の判定（婚姻後 200 日・前婚解消後 300 日）、届出期間の経過、非本籍地での届出、代理人による請求。
  - 抜け漏れの検査：届出に足りない書類・記載事項を SHACL で列挙する。
  - 業務をまたいだ問い：例「戸籍法施行規則第48条が関わる工程はどれか」。
  - 法改正の影響範囲：手順書は古く、女性の待婚期間（民法733条）は 2024 年に廃止、未成年者の婚姻の父母の同意は 2022 年の成年年齢引き下げで不要になった。法令ノードから依存する審査項目を辿れるかを見る。手順書の記述と現行法の違いは、オントロジー上で区別して持つ（どう持つかは仕様で決める）。
- 検証の結果と考察は `docs/` に残す。

## リポジトリの置き場所

- `docs/specs/`、`docs/plans/`：仕様と計画（直下に置く）
- `docs/domain/`：題材の原本（`手順書.pdf`）と、業務・法令の背景知識のメモ
- `ontology/`：オントロジー（スキーマ・SHACL・インスタンス）の Turtle ファイル。git 管理する
- `src/semantica_agent/`：オントロジー構築とエージェントのコード
- `tests/`：テスト
- `data/`、`output/`：中間生成物と実行結果。git 管理外（commit-guard もコミットを止める）

## よくある落とし穴

- semantica の生成機能は 2 つある。`OntologyGenerator` は LLM を使わないルールベースの機能で、このプロジェクトでは使わない（生成は `LLMOntologyGenerator`）。以下の 2 点はルールベースの方の挙動で、扱うデータを渡すときの参考に残す。
- `OntologyGenerator` は型名を ASCII に正規化してクラス名にする。日本語の型名（`届出` など）はすべて `Entity` に潰れて衝突し、`ValidationError` になる。型名・プロパティ名は英語で付け、日本語は `rdfs:label "…"@ja` に持たせる。
- 同じく `OntologyGenerator` は 2 回以上出現した型だけをクラスにする（1 件だけの型は黙って捨てられる）。`ProcedureStep` のような CamelCase は `Procedurestep` に正規化され、`base_uri` 末尾の `#` も落ちる。名前を厳密に決めたいスキーマは自動生成に頼らず、Turtle で直接書くか rdflib で組み立てる。
- semantica 0.7.0 は Python 3.11〜3.13 のみ対応。このリポジトリは 3.12 に固定している（`.python-version`）。
- シェルに別プロジェクトの `VIRTUAL_ENV` が残っていると `uv run` が警告を出す（動作はこのプロジェクトの `.venv` で行われる）。気になるときは `unset VIRTUAL_ENV`。
