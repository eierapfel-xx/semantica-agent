# 審査支援エージェント（Claude Code 版）

Agent SDK 版（`python -m semantica_agent.web`）と同じツール・同じシステムプロンプト・同じ形のトレースで、審査支援エージェントを Claude Code から動かす。仕様は `docs/specs/2026-11-19-package-split-and-claude-code.md`。

このディレクトリには設定と起動スクリプトだけを置く。コードは `src/semantica_agent/agent/`（`claude_code.py`・`mcp_server.py`・`spool.py`・`transcript.py`・`turn_close.py`）にある。

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
