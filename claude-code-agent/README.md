# 審査支援エージェント（Claude Code 版）

Agent SDK 版（`python -m semantica_agent.web`）と同じツール・同じシステムプロンプト・同じ形のトレースで、審査支援エージェントを Claude Code から動かす。仕様は `docs/specs/2026-11-19-package-split-and-claude-code.md`。

## 構成

このディレクトリには設定と起動スクリプトだけを置く。システムプロンプト・MCP サーバー・hook の処理・オントロジーはリポジトリ本体にあり、ここからはそれを呼ぶだけ。

```
claude-code-agent/
├── run.sh                 # 起動スクリプト（中身は semantica_agent.agent.claude_code launch）
├── .mcp.json              # MCP サーバー koseki の起動コマンド
├── .claude/settings.json  # hook の登録（UserPromptSubmit・PreToolUse・Stop）と auto memory・プラグインの無効化
└── README.md
```

CLAUDE.md は置かない。システムプロンプトは起動時に `--system-prompt-file` で渡す。

### 部品ごとの、設定の場所と実装元

| 部品                           | どこで指定しているか                      | 実装元（リポジトリ内）                                                                   |
| ------------------------------ | ----------------------------------------- | ---------------------------------------------------------------------------------------- |
| 起動                           | `run.sh`                                  | `src/semantica_agent/agent/claude_code.py`（`launch`・`build_launch_plan`）              |
| システムプロンプト             | `run.sh` が `--system-prompt-file` で渡す | `src/semantica_agent/agent/prompts/agent.md`（`{today}` に今日の日付を入れたものを渡す） |
| ツール（MCP サーバー）         | `.mcp.json` の `koseki`                   | `src/semantica_agent/agent/mcp_server.py`                                                |
| ツールの中身                   | （MCP サーバーから呼ぶ）                  | `src/semantica_agent/agent/session.py`・`tools.py`（SDK 版と共通）、判定は `review/`     |
| オントロジー                   | （MCP サーバーが読む）                    | `ontology/`（スキーマ・SHACL・インスタンスの Turtle）                                    |
| hook（発言・呼び出し・終わり） | `.claude/settings.json` の `hooks`        | `src/semantica_agent/agent/claude_code.py`（`handle_hook`）                              |
| ターンを閉じてトレースを作る   | `Stop` の hook と、`run.sh` の終了後      | `src/semantica_agent/agent/turn_close.py`・`transcript.py`・`trace.py`                   |
| 途中の記録                     | （hook と MCP サーバーが書く）            | `src/semantica_agent/agent/spool.py`                                                     |

### 起動から終了までの流れ

1. `run.sh` が `claude_code launch` を呼ぶ。
1. `launch` の準備：
   - オントロジーを読み込んで検証する。
   - セッション ID を作る。
   - `agent.md` に日付を入れて `output/claude-code/<session_id>/prompt.md` に書く。
   - `session.json` を書く。
1. `launch` が、Agent SDK 同梱の `claude` をこのディレクトリで起動する。起動時には、下の「何を絞っているか」のフラグを付ける。環境変数は次の 4 つを渡す。
   - `KOSEKI_REPO_ROOT`
   - `KOSEKI_SESSION_ID`
   - `KOSEKI_SPOOL_ROOT`
   - `KOSEKI_TRACE_ROOT`
1. `claude` が `.mcp.json` を読み、`uv run --project $KOSEKI_REPO_ROOT python -m semantica_agent.agent.mcp_server` で koseki を起動する。
1. 質問のたびに、`.claude/settings.json` の hook が `python -m semantica_agent.agent.claude_code hook <prompt|pre-tool|stop>` を呼んで記録する。
1. `claude` の終了後に、`launch` が閉じていないターンを閉じる。

`.mcp.json` と hook のコマンドは `$KOSEKI_REPO_ROOT` などの環境変数を前提にしている。このため、`run.sh` を通さずに起動すると動かない。

## 起動

```bash
./claude-code-agent/run.sh                       # 対話で相談する
./claude-code-agent/run.sh "出生届です。…受理できる？"  # 1 問だけ聞いて終わる（-p）
```

- 既定のモデルは sonnet（`claude-sonnet-5-5`）。`AGENT_MODEL` で変えられる。
- Claude Code のログイン（Pro）で動く。`ANTHROPIC_API_KEY` が環境にあると起動しない。
- 起動するのは Agent SDK 同梱の Claude Code（SDK 版と同じ版）。PATH の `claude` は使わない。版は `uv run python -m semantica_agent.doctor` で確かめられる。
- `claude` をこのディレクトリで素のまま起動しない。下の絞り込みが効かず、開発用の CLAUDE.md やプラグインが入る。

## 何を絞っているか

`run.sh` は次のように `claude` を起動する（`semantica_agent.agent.claude_code.build_launch_plan`）。

| 絞るもの                                | 方法                                                                                            |
| --------------------------------------- | ----------------------------------------------------------------------------------------------- |
| システムプロンプト                      | `--system-prompt-file`（`src/semantica_agent/agent/prompts/agent.md` に今日の日付を入れたもの） |
| 組み込みツール（Read・Bash 等）         | `--tools ""`                                                                                    |
| MCP サーバー                            | `--strict-mcp-config --mcp-config .mcp.json`（`koseki` だけ）                                   |
| CLAUDE.md（親・ユーザー）と auto memory | 環境変数 `CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`・`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`                |
| ユーザー・ローカルの設定                | `--setting-sources project`（このディレクトリの `.claude/settings.json` だけ）                  |
| プラグイン                              | `--settings` で、インストール済みのものをすべて `enabledPlugins: false`                         |
| スキル・スラッシュコマンド              | `--disable-slash-commands`                                                                      |
| ツールの許可                            | `--allowedTools "mcp__koseki__*"`、`--permission-mode dontAsk`                                  |

絞り込めないもの：Claude Code 本体が自動で付ける文脈（作業ディレクトリ・OS などの環境、ログインしたアカウントのメールアドレス、環境上の注意書き）と、本体に組み込まれたプラグイン（`…@builtin`）は残る。どちらも同じ CLI で動く SDK 版にも入るので、2 つの版の条件の差にはならない（2026-11-19 の E2E で確認）。

## 記録の仕組み

| 何を                         | 誰が                                                   |
| ---------------------------- | ------------------------------------------------------ |
| 職員の発言、ターンの始まり   | `UserPromptSubmit` の hook                             |
| ツールの呼び出し             | `PreToolUse` の hook（matcher `mcp__koseki__.*`）      |
| ツールの結果・判定・回答     | MCP サーバー（`koseki`）                               |
| LLM の文章・思考・応答モデル | `Stop` の hook が Claude Code の会話の記録から取り出す |

途中の記録は `output/claude-code/<session_id>/`、まとめたトレースは SDK 版と同じ `output/traces/<session_id>/<turn>.json`（＋ `report.md`・PROV-O・`decisions.json`）。トレースの `runtime.kind` が `claude-code` になる。`uv run python -m semantica_agent.web` の画面のトレース一覧から開いて再生できる。

## SDK 版との違い

| 点               | SDK 版                                       | Claude Code 版                                                               |
| ---------------- | -------------------------------------------- | ---------------------------------------------------------------------------- |
| 画面             | Web 画面（フローの色付けを途中から見られる） | ターミナル。トレースは後から Web 画面で開く                                  |
| LLM の文章の記録 | SDK のメッセージから                         | Claude Code の会話の記録（transcript）から                                   |
| ツールの記録     | SDK の hook とツールの実装                   | Claude Code の hook と MCP サーバー                                          |
| ターンの上限     | `max_turns`（既定 20）                       | 1 問だけ聞くとき（`-p`）だけ                                                 |
| 中断されたターン | 取り消しを捕まえて `error` で保存            | 次の質問の開始か、終了後の片づけで `error` で保存                            |
| 会話の切り替え   | 画面の「新しい相談」                         | 起動し直す。`/clear`・`--resume` で会話を変えると記録しない（hook が止める） |

hook の失敗はターンを止めず、`output/claude-code/<session_id>/hook-errors.log` に残る。
