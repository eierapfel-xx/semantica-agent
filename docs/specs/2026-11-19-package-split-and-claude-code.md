# パッケージの整理と Claude Code での起動

- 日付：2026-11-19
- 前提：`docs/specs/2026-11-17-agent-design.md`（審査支援エージェント。PR #3 でマージ済み）。この仕様は、そのエージェントの**置き場所**と**動かし方**を変える。ツール・判定・トレースの中身は変えない。
- 対象：`src/semantica_agent/` のパッケージ構成、Claude Code で審査支援エージェントを起動するためのディレクトリ。

## 1. 目的

### なぜやるか

- `src/semantica_agent/` に、役割の違うコードが平らに並んでいる。オントロジーの生成パイプライン、判定ロジック、エージェント、Web サーバーの 4 つで、生成パイプラインはエージェントの実行に使わない。どこまでがエージェントか、ファイルを見ても分からない（ユーザーの指摘）。
- エージェントは Agent SDK で作った。Agent SDK は中で Claude Code を動かしている。それなら、Claude Code の MCP・hook・設定でも同じ動きを取れるのではないか、を確かめたい（ユーザーの関心）。
- このリポジトリは開発用のプロジェクトなので、ここで `claude` を起動すると開発用の CLAUDE.md やスキルが入る。審査用は下の階層に別の Claude Code のプロジェクトとして作る（ユーザーの決定）。

### ゴール

- `src/semantica_agent/` を役割ごとのサブパッケージに分ける。依存の向きを一方向にし、テストで確かめる。
- 既存のコマンド（`python -m semantica_agent.build`・`.web`・`.doctor`）は、同じ名前のまま動く。
- 審査支援エージェントのツールを、Agent SDK 版と Claude Code 版で**同じ実装**から出す。
- リポジトリ直下の `claude-code-agent/` で起動スクリプトを実行すると、Claude Code で審査支援エージェントが動く。SDK 版と同じツール、同じシステムプロンプト、同じ形のトレース（`output/traces/`）。
- Claude Code 版のトレースも、既存の Web 画面のトレース一覧から開いて再生できる。

### ゴールにしないこと

- ツール、判定ルール、システムプロンプトの文面、トレースの中身の変更（§6 の `runtime` の追加を除く）。
- SDK 版の動きの変更。ただし §5.5 の、CLAUDE.md と auto memory を読ませない設定は SDK 版にも足す（条件をそろえるため）。
- Web 画面から Claude Code 版を動かすこと。
- パッケージを複数の配布物（uv の workspace 等）に分けること。
- SDK 版と Claude Code 版の回答の比較評価（別の仕様で行う）。

### 失敗とみなすこと（動いても失敗）

- Claude Code 版で、開発用の CLAUDE.md、ユーザーの CLAUDE.md、auto memory、プラグイン（superpowers 等）、組み込みツール（Read・Bash 等）のどれかがエージェントに見えている。手順書や `.ttl` を直接読んで答えられると、「LLM＋オントロジー」の比較の条件が崩れる。
- Claude Code 版のトレースが、LLM の自己申告から作られている（ツール呼び出しの記録は MCP サーバーと hook、LLM の文章は Claude Code の記録から取る）。
- 整理の前後で、テストの結果やトレースの形が変わる（`runtime` の追加とパスの変更を除く）。
- `ANTHROPIC_API_KEY` が環境にあるまま `claude` が起動され、従量課金になる。

## 2. 進め方の選択（Approaches）

### 2.1 Claude Code での起動の仕方

| 案            | 内容                                                                                                                          | 長所                       | 短所                                                                               |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------- | ---------------------------------------------------------------------------------- |
| 1             | 下の階層のディレクトリの設定ファイルだけで絞り、素の `claude` で起動する。プロンプトは `CLAUDE.md` に置く                     | 普段どおりの起動           | Claude Code 既定のシステムプロンプト（コーディング支援）が残り、SDK 版と条件が違う |
| **2（採用）** | 下の階層のディレクトリに起動スクリプトを置き、CLI のオプションでシステムプロンプト・ツール・読み込む設定を SDK 版と同じに絞る | SDK 版と条件をそろえられる | 起動はスクリプト経由になる                                                         |
| 3             | 開発中のセッションからサブエージェントとして呼ぶ                                                                              | 手軽                       | 親の会話・設定と分けられず、ターンの区切りもあいまい                               |

**案 2 を採用**（ユーザーの決定）。

### 2.2 パッケージの分け方（設計者の判断）

| 案            | 内容                                                         | 判断                                                              |
| ------------- | ------------------------------------------------------------ | ----------------------------------------------------------------- |
| **1（採用）** | 1 つの配布物の中をサブパッケージに分ける                     | 依存・仮想環境が 1 つのまま、役割と依存の向きをはっきりさせられる |
| 2             | uv の workspace で生成・エージェント・Web を別の配布物にする | 共通コードの扱いと依存の管理が増える。検証用のリポジトリには重い  |

## 3. パッケージの構成

```
src/semantica_agent/
  doctor.py                 環境の確認（python -m semantica_agent.doctor。場所は変えない）
  core/                     どこからでも使う土台
    namespaces.py ids.py vocab.py settings.py turtle_io.py
  review/                   判定ロジック（LLM を使わない）
    case_input.py rule_inputs.py derive.py judge.py assess.py claims.py flow.py
  build/                    オントロジーの生成パイプライン（エージェントの実行では使わない）
    __main__.py             python -m semantica_agent.build
    pipeline.py             （旧 build.py）
    extract.py schema_gen.py instance_gen.py instance_check.py law_gen.py
    shapes_gen.py llm_provider.py provenance.py lawref.py
    prompts/                schema.md instances.md integrity.md rules.md amendments.md
  agent/                    審査支援エージェント（実行環境によらない部分＋2 つの実行環境）
    tools.py                Knowledge とツールの関数（旧 tools.py）
    session.py              1 つの相談の状態・ターンの開始と終了・ツールの呼び出しの記録（旧 agent.py から実行環境によらない部分を出す）
    trace.py                トレースの記録・検証・保存（旧 trace.py）
    sdk.py                  Agent SDK 版（旧 agent.py の残り：ClaudeSDKClient、SDK の hook）
    mcp_server.py           Claude Code 版の stdio MCP サーバー
    claude_code.py          Claude Code 版の起動（引数の組み立て）と hook の処理
    prompts/agent.md
    schemas/trace.schema.json
  web/                      Web 画面（エージェントを使う側）
    __main__.py             python -m semantica_agent.web
    app.py                  （旧 web.py）
    static/
```

- **依存の向き**：`core` ← `review` ← `agent` ← `web`、`core`・`review` ← `build`。`build` と `agent`・`web` は互いに import しない。`derive.py` は生成（導出の定義を書き出す）と判定の両方が使うので `review` に置く。
- 依存の向きは、`tests/test_layers.py` で各モジュールの import を調べて固定する。
- 旧モジュール名の互換（`semantica_agent.tools` 等を残す別名）は作らない。リポジトリの中の import をすべて新しい名前に直す。
- `python -m semantica_agent.build`・`.web`・`.doctor` と、その引数は変えない。CLAUDE.md・AGENTS.md・README のコマンドもそのまま使える。
- テストは `tests/` の直下に置いたまま（`.claude/rules/tests.md` の決まり）、import を直す。モジュールの名前を変えたもの（`agent.py` → `agent/sdk.py`、`web.py` → `web/app.py`、`build.py` → `build/pipeline.py`）は、テストのファイル名も合わせる（`test_sdk.py`・`test_app.py`・`test_pipeline.py`）。
- `ontology/` を読む場所（`Knowledge.load` がリポジトリのルートから `ontology/` を読む）は変えない。リポジトリのルートを求める処理は `core` の 1 か所にまとめる。

### 3.1 `agent/session.py`（実行環境によらない部分）

旧 `agent.py` の `AgentSession` のうち、次を `ReviewSession` として出す。SDK 版と Claude Code 版の両方がこれを使う。

- `Knowledge`、`SessionState`、`ContextGraph`、`TraceRecorder` を持つ。
- `start_turn(question)`：ターンを進め、記録を始める（旧 `_start_turn`）。
- `call_tool(name, args)`：ツールの関数を呼び、結果とエラーを記録する（旧 `_wrap` の中身）。SDK の `@tool` と MCP サーバーの両方から呼ぶ。
- `finish_turn(texts, model, status)`：トレースを組み立てる（旧 `_finish`）。
- ツールの名前・説明・入力スキーマ（旧 `_descriptions`・`build_tools` の `schemas`）もここに置き、両方の実行環境で同じものを使う。

`TraceRecorder` に、イベントを積むたびに呼ぶ関数（`on_add`）を渡せるようにする。Claude Code 版はこれでイベントをファイルにも書く（§5.3）。

## 4. Claude Code 版のディレクトリ

```
claude-code-agent/
  run.sh                    起動スクリプト（中身は uv run python -m semantica_agent.agent.claude_code launch）
  .mcp.json                 koseki の MCP サーバー
  .claude/settings.json     hook、auto memory の停止、プラグインの無効化
  README.md                 起動の仕方、SDK 版との違い（§7）
```

- 中身は設定と起動スクリプトだけにし、コードは `src/semantica_agent/agent/` に置く。
- `claude-code-agent/` には CLAUDE.md を置かない（システムプロンプトは起動時に渡す）。
- 審査の作業ファイル（描き出したシステムプロンプト、イベントの記録）は `output/claude-code/<session_id>/` に置く（git 管理外）。

## 5. 起動と記録の仕組み

### 5.1 起動（`claude_code.py launch`）

1. `load_settings()` で設定を読む。`ANTHROPIC_API_KEY` があれば止める（既存と同じ）。
1. オントロジーを読み、整合性シェイプで検証する（Web と同じ。通らなければ止める）。
1. セッション ID（UUID）を作る。
1. `prompts/agent.md` に今日の日付を差し込み、`output/claude-code/<session_id>/prompt.md` に書く。
1. 次の環境変数と引数で `claude` を起動する（`claude-code-agent/` を作業ディレクトリにする）。`claude` は PATH 上のものではなく、**Agent SDK に同梱の CLI**（`claude_agent_sdk/_bundled/claude`）を使う。SDK 版と同じ版（2026-11-19 時点で 2.1.325。PATH 上は 2.1.328）で動かし、条件をそろえるため（設計者の判断）。同梱の CLI が見つからなければ止める。起動した `claude` の版をトレースの `runtime.cli_version`（§6）に残す。
1. `claude` の終了を待ち（`exec` で置き換えない）、終わったら §5.4 の片づけを行う。

```
環境変数:
  CLAUDE_CODE_DISABLE_CLAUDE_MDS=1     親・ユーザーの CLAUDE.md と auto memory を読まない
  CLAUDE_CODE_DISABLE_AUTO_MEMORY=1
  KOSEKI_SESSION_ID=<session_id>       MCP サーバーと hook が同じ相談を指すため
  KOSEKI_REPO_ROOT=<リポジトリのルート>  .mcp.json と hook が uv run --project に使う
  AGENT_MODEL 等                        load_settings と同じものを引き継ぐ
引数:
  --session-id <session_id>
  --model <AGENT_MODEL>               既定は claude-sonnet-5-5（sonnet）
  --system-prompt-file output/claude-code/<session_id>/prompt.md
  --tools ""                           組み込みツールを使わせない
  --strict-mcp-config --mcp-config .mcp.json
  --setting-sources project            ユーザー・ローカルの設定を読まない
  --disable-slash-commands             スキルとコマンドを使わせない
  --allowedTools "mcp__koseki__*"
  --permission-mode dontAsk            許可していないものは確かめずに拒否する
  --settings <JSON>                    インストール済みのプラグインをすべて false にした enabledPlugins
  [-p <質問>]                          起動スクリプトに質問を渡したときだけ（1 問で終わる）
```

- 引数を組み立てる処理は関数に分け、テストで固定する（実際には起動しない）。

- エージェントを動かすときの既定のモデルは、SDK 版・Claude Code 版とも、テスト（`llm`）を含めて sonnet（`claude-sonnet-5-5`。`settings.DEFAULT_AGENT_MODEL`）にする（ユーザーの決定）。`AGENT_MODEL` で変えられる。

- 公式ドキュメントで確かめたこと（2026-11-19、CLI 2.1.328）：

  - 上の階層の CLAUDE.md は `--setting-sources` でも `--system-prompt-file` でも止まらない。`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` で止まる。
  - project の settings は起動ディレクトリの `.claude/settings.json` から読む。親の `.claude/settings.json`（commit-guard 等）は読まない。
  - `--tools ""` は組み込みツールだけを外し、MCP ツールは残る。
  - `--system-prompt-file` は対話モードでも使える。
  - `--bare` は API キーでしか動かないので使わない。

- ドキュメントで確かめられなかったこと：`--setting-sources project` のとき、ユーザー単位でインストールしたプラグインが入るか。そのため `--settings` の `enabledPlugins` で明示的に切り、§8 の確認で実際に入っていないことを見る。

- 公式ドキュメントは 2.1.328 で確かめた。同梱の 2.1.325 で同じに効くかは、§8 の E2E（`system/init` の確認）で見る。

### 5.2 MCP サーバー（`mcp_server.py`）

- `.mcp.json` の `koseki` として、`uv run --project ${KOSEKI_REPO_ROOT} --no-sync python -m semantica_agent.agent.mcp_server` で起動する。stdio で、Claude Code のセッションの間ずっと動く。
- 起動時にオントロジーを 1 回読み、`ReviewSession` を 1 つ作る。`KOSEKI_SESSION_ID` が無ければ止める。
- ツール（`judge_birth_case` ほか 6 つ）を、§3.1 の名前・説明・スキーマで出し、`ReviewSession.call_tool` を呼ぶ。MCP の Python SDK（`mcp`、既に依存に入っている）を使う。
- ターンの区切りは MCP サーバーからは見えない。ツールを呼ばれるたびに `output/claude-code/<session_id>/turn.json`（§5.3）を読み、ターンの番号が進んでいたら `start_turn` を呼ぶ。

### 5.3 hook とイベントの記録

`output/claude-code/<session_id>/` に、ターンごとのファイルを置く。

| ファイル                | 書く側                | 中身                                                                                                                 |
| ----------------------- | --------------------- | -------------------------------------------------------------------------------------------------------------------- |
| `turn.json`             | UserPromptSubmit hook | 今のターンの番号、職員の発言、開始時刻、`transcript_path`                                                            |
| `turn-NNN.events.jsonl` | hook と MCP サーバー  | トレースのイベント（1 行 1 件、追記）。`user`・`tool_call` は hook、`tool_result`・`answer`・`error` は MCP サーバー |
| `turn-NNN.state.json`   | MCP サーバー          | ターンの終わりに要る状態（判定、事案、回答、ターンの初めのフローの状態、判定を呼んだか）                             |

`.claude/settings.json` の hook（コマンドは `uv run --project "$KOSEKI_REPO_ROOT" --no-sync python -m semantica_agent.agent.claude_code hook <名前>`）：

- **UserPromptSubmit**：ターンの番号を進め、`turn.json` と `user` イベントを書く。
- **PreToolUse**（matcher `mcp__koseki__.*`）：`tool_call` イベント（ツール名、引数、`tool_use_id`、`via: "hook"`）を書く。SDK 版の PreToolUse と同じ役目。
- **Stop**：ターンを閉じる。`transcript_path` から、このターンの LLM の文章（`assistant_text`）・思考（`thinking`）・応答したモデル名を取り出し、イベントの記録とまとめて時刻の順に並べ、`seq` を振り直す。`turn-NNN.state.json` と合わせて `TraceRecorder.finish` 相当でトレースを作り、`save_trace` で `output/traces/<session_id>/<turn>.json`・`report.md` に保存する。`ContextGraph` は、セッションのフォルダに前のターンの `decisions.json` があれば読み込んでから追記する。
- hook は stdin の `session_id` が `KOSEKI_SESSION_ID` と違えば、何も書かずにエラーを標準エラーに出して終わる（`/clear` 等で会話が変わった場合。§7）。
- hook の失敗はターンを止めない（終了コード 0 以外でもブロックしない種類の失敗にする）。失敗はトレースの `error` イベントか、書けなければ `output/claude-code/<session_id>/hook-errors.log` に残す。
- `PostToolUse` は使わない（ツールの結果は MCP サーバーが記録する。SDK 版でもログを出すだけ）。

### 5.4 Stop が来ないで終わったターン（設計者の判断）

Esc での中断、`-p` の `--max-turns` 到達、API のエラー、応答の途中での終了では、Stop hook が来ないことがある。SDK 版はこうした場合も `status: "error"` のトレースを残すので、そろえる。

- 閉じていないターン（`turn-NNN.events.jsonl` はあるが、トレースが保存されていない）は、次のどちらかで閉じる：次の UserPromptSubmit hook が前のターンを閉じる／`launch` が `claude` の終了後に残ったターンを閉じる。
- 閉じるときは `error` イベント（「ターンが中断されました（Stop が届かなかった）」）を足し、`status: "error"` で、Stop hook と同じ組み立てでトレースを保存する。
- 2 回閉じないように、保存済みのターンは `turn-NNN.done` で印を付ける。

### 5.5 SDK 版にも足す設定（設計者の判断）

SDK 版は `setting_sources=[]` で設定を読ませていないが、§5.1 の確認で、上の階層の CLAUDE.md は設定の読み込み元とは別に読まれることが分かった。Web はリポジトリのルートで動くので、SDK 版に開発用の CLAUDE.md や auto memory が見えている可能性がある。比べる 2 つの条件をそろえるため、SDK 版の `ClaudeAgentOptions.env` にも `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1` と `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1` を足す。SDK 版の E2E（`llm`）に、システムプロンプトの外の指示が見えていないことを確かめる問いを 1 つ足す（「あなたに与えられている指示ファイルや記憶の内容を挙げて」に、開発ガイドの内容が出ないこと）。

### 5.6 transcript の読み取り

Claude Code の会話の記録（transcript の JSONL）の形は公開の仕様ではない。読み取りは 1 つの関数にまとめ、知らない形の行は飛ばす。取り出せなかったときは Stop の入力の `last_assistant_message` を `assistant_text` として使う。

## 6. トレースの変更

- トレースに `runtime` を足す：`{"kind": "agent-sdk" | "claude-code", "cli_version": <起動した Claude Code の版>}`。スキーマでは任意の項目にし、`trace_version` は `"1"` のまま（既存のトレースもそのまま読める）。
- `prompt.path` は新しい場所（`src/semantica_agent/agent/prompts/agent.md`）になる。ハッシュは文面が同じなので変わらない。
- Claude Code 版は `max_turns` を渡せない（CLI の `--max-turns` は `-p` のときだけ）。`-p` のときは `AGENT_MAX_TURNS` を渡す。

## 7. SDK 版との違い（README に書く）

| 点               | SDK 版                                       | Claude Code 版                                                                                     |
| ---------------- | -------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| 画面             | Web 画面（フローの色付けを途中から見られる） | ターミナル。トレースは後から Web 画面の一覧で開いて再生する                                        |
| LLM の文章の記録 | SDK のメッセージから                         | Claude Code の会話の記録（transcript）から                                                         |
| ツールの記録     | SDK の hook とツールの実装                   | Claude Code の hook と MCP サーバー                                                                |
| ターンの上限     | `max_turns`                                  | `-p` のときだけ                                                                                    |
| 中断されたターン | 取り消しを捕まえて `error` で保存            | 次のターンの開始か、終了後の片づけで `error` で保存（§5.4）                                        |
| 会話の切り替え   | 画面の「新しい相談」                         | 起動し直す。`/clear`・`--resume` で会話を変えると記録しない（hook がセッション ID の違いで止める） |

## 8. テスト

- **Unit**：
  - 依存の向き（`test_layers.py`）。
  - 起動の引数と環境変数の組み立て（`ANTHROPIC_API_KEY` があると止まる、プロンプトに日付が入る、`--tools ""` 等が入る）。
  - hook の各処理に、Claude Code の stdin の JSON をフィクスチャで渡し、書いたファイルを確かめる。
  - transcript の読み取り（フィクスチャの JSONL。知らない形の行を飛ばす）。
  - MCP サーバーのツールの一覧（名前・スキーマが SDK 版と同じ）。
- **Integration**：hook と MCP サーバーの処理を、ターン 2 回ぶん順に直接呼び、`output/traces/` に保存されたトレースがスキーマを通り、`runtime` が `claude-code` で、再生した `flow` が一致することを確かめる。MCP サーバーは、`mcp` の stdio クライアントで実際に起動して 1 回ツールを呼ぶテストも 1 つ置く（`slow`）。
- **E2E（`llm`）**：起動スクリプトに `-p` で出生届の事案を 1 件渡し、トレースが 1 件でき、`judge_birth_case` と `submit_answer` が記録されていることを確かめる。あわせて、`--output-format stream-json` の `system/init` で、ツールが `mcp__koseki__*` だけ、プラグインが空であることを確かめる（§5.1 の確かめられなかった点）。あわせて §5.5 の SDK 版の確認を 1 問。Claude Pro の利用枠を合計 3 回ほど使う（流す前に回数を伝えて確認する）。
- 整理の前後で既存のテストがすべて通ること。カバレッジは 80% 以上を保つ。

## 9. 実装する側に任せること

- `ReviewSession` と SDK 版の `AgentSession` の間の細かい分け方（§3.1 の役目を満たす範囲で）。
- イベントの記録ファイルの細かい形（§5.3 の役目を満たす範囲で）。
- インストール済みのプラグインの一覧の取り方（`claude plugin list` の出力、または設定ファイルから）。
- `run.sh` の細かい書き方（引数をそのまま `launch` に渡す）。
- README の文面。
