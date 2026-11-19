# パッケージの整理と Claude Code での起動 実装計画

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.（このプロジェクトでは計画のチェックボックスは付けず、進捗は `.superpowers/sdd/2026-11-19-package-split-and-claude-code/progress.md` に記録する。）

**Goal:** `src/semantica_agent/` を役割ごとのサブパッケージに分け、同じツールの実装から Agent SDK 版と Claude Code 版（`claude-code-agent/`）の審査支援エージェントを動かす。

**Architecture:** 実行環境によらない相談の処理を `agent/session.py` の `ReviewSession` に出し、SDK 版（`agent/sdk.py`）と stdio の MCP サーバー（`agent/mcp_server.py`）の両方が使う。Claude Code 版は、起動スクリプトが SDK 同梱の CLI をオプションで絞って起動し、hook と MCP サーバーが `output/claude-code/<session_id>/` にイベントを書き、Stop hook（または後片づけ）がトレースにまとめて `output/traces/` に保存する。

**Tech Stack:** Python 3.12、uv、claude-agent-sdk 0.2.182（同梱 CLI 2.1.325）、mcp 2.3.0（`mcp.server.lowlevel.Server`・`mcp.server.stdio.stdio_server`・`mcp.client`）、rdflib、semantica 0.7.0、pytest。

**Spec:** `docs/specs/2026-11-19-package-split-and-claude-code.md`（以下「仕様」）。前提の仕様は `docs/specs/2026-11-17-agent-design.md`。

## Global Constraints

- コマンド名は変えない：`uv run python -m semantica_agent.build`・`.web`・`.doctor`（引数も同じ）。
- 依存の向き：`core` ← `review` ← `agent` ← `web`、`core`・`review` ← `build`。`build` と `agent`・`web` は互いに import しない。`doctor` はどれを使ってもよい。
- 旧モジュール名の互換の別名は作らない。
- テストは `tests/` 直下のまま。`agent.py`→`test_sdk.py`、`web.py`→`test_app.py`、`build.py`→`test_pipeline.py` に名前を合わせる。
- エージェントの既定モデルは `claude-sonnet-5-5`（`settings.DEFAULT_AGENT_MODEL`。既に同じ値）。`llm` のテストもこの既定で動かす。
- Claude Code 版の `claude` は Agent SDK 同梱の CLI（`claude_agent_sdk/_bundled/claude`）。PATH の `claude` は使わない。
- 起動時の環境変数：`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`、`CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`、`KOSEKI_SESSION_ID`、`KOSEKI_REPO_ROOT`。SDK 版の `ClaudeAgentOptions.env` にも前の 2 つを入れる。
- 起動時の引数（仕様 §5.1 の順のまま）：`--session-id`、`--model`、`--system-prompt-file`、`--tools ""`、`--strict-mcp-config --mcp-config .mcp.json`、`--setting-sources project`、`--disable-slash-commands`、`--allowedTools "mcp__koseki__*"`、`--permission-mode dontAsk`、`--settings <enabledPlugins をすべて false にした JSON>`、質問があれば `-p <質問> --max-turns <AGENT_MAX_TURNS>`。
- トレースの `runtime`：`{"kind": "agent-sdk" | "claude-code", "cli_version": str | null}`。スキーマでは任意、`trace_version` は `"1"` のまま。
- `ANTHROPIC_API_KEY` があれば起動しない（`load_settings` の `ConfigError`）。
- `llm` のテストは計画の実行中には流さない。最後に回数（3 回）を伝えて確認してから流す。
- コミットは `<type>: <日本語>`。生成パイプライン・オントロジーの中身は変えない。

## Review Focus

1. **`/clear` や `--resume` で Claude Code のセッション ID が変わった**：hook は何も書かず標準エラーに理由を出して終わり、MCP サーバーの記録も壊れない（Task 5 の `test_hook_ignores_other_session`）。
1. **ツールを 1 度も呼ばずに答えたターン**（雑談、聞き返しだけ）：`turn-NNN.state.json` が無くてもトレースが保存され、`answer.submitted` が false、`flow_initial` が前のターンの状態になる（Task 5 の `test_close_turn_without_tool_calls`）。
1. **Stop が届かないまま次の質問／終了**：前のターンが `status: "error"` で 1 回だけ保存される（Task 5 の `test_next_prompt_closes_open_turn`、Task 6 の `test_launch_closes_open_turns_after_exit`）。
1. **transcript に知らない形の行や壊れた行がある**：飛ばし、取れなければ `last_assistant_message` を使う（Task 4 の `test_reads_unknown_lines_safely`）。
1. **同梱 CLI が無い／`claude plugin list --json` が失敗する**：分かりやすいメッセージで止まる（Task 6 の `test_missing_bundled_cli`・`test_plugin_list_failure`）。

______________________________________________________________________

## ファイルの対応（Task 1 で移す）

| 旧                                                                                                                                            | 新                                             |
| --------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `namespaces.py` `ids.py` `vocab.py` `settings.py` `turtle_io.py`                                                                              | `core/`（同名）                                |
| （新規）                                                                                                                                      | `core/paths.py`（`REPO_ROOT`）                 |
| `case_input.py` `rule_inputs.py` `derive.py` `judge.py` `assess.py` `claims.py` `flow.py`                                                     | `review/`（同名）                              |
| `build.py`                                                                                                                                    | `build/pipeline.py`＋`build/__main__.py`       |
| `extract.py` `schema_gen.py` `instance_gen.py` `instance_check.py` `law_gen.py` `shapes_gen.py` `llm_provider.py` `provenance.py` `lawref.py` | `build/`（同名）                               |
| `prompts/{schema,instances,integrity,rules,amendments}.md`                                                                                    | `build/prompts/`                               |
| `tools.py` `trace.py`                                                                                                                         | `agent/`（同名）                               |
| `agent.py`                                                                                                                                    | `agent/sdk.py`                                 |
| `prompts/agent.md` `schemas/trace.schema.json`                                                                                                | `agent/prompts/agent.md` `agent/schemas/…`     |
| `web.py` `web/static/`                                                                                                                        | `web/app.py`＋`web/__main__.py`、`web/static/` |
| `doctor.py`                                                                                                                                   | そのまま                                       |

______________________________________________________________________

### Task 1: サブパッケージへ移し、依存の向きをテストで固定する

スキル：`superpowers:test-driven-development`（`test_layers.py` を先に書く）。移動は `git mv` で行い、履歴を残す。

**Files:**

- Create: `src/semantica_agent/{core,review,build,agent,web}/__init__.py`、`src/semantica_agent/core/paths.py`、`src/semantica_agent/build/__main__.py`、`src/semantica_agent/web/__main__.py`、`tests/test_layers.py`
- Move: 上の表のとおり（`git mv`）
- Modify: すべての `from semantica_agent.X import` と `"semantica_agent.X.attr"` の文字列（`tests/conftest.py:69-70` の monkeypatch を含む）、`PROMPT_PATH`・`SCHEMA_PATH`・`STATIC_DIR`・`prompt_path()` の相対パス、`agent/sdk.py` と `agent/trace.py` の `REPO_ROOT`、`docs/` を除くコマンド・パスの記述（`README.md`、`CLAUDE.md`、`AGENTS.md` の「リポジトリの置き場所」に構成を 1 行ずつ足す）
- Rename tests: `tests/test_agent.py`→`test_sdk.py`、`test_web.py`→`test_app.py`、`test_build.py`→`test_pipeline.py`

**Interfaces:**

- Produces: `semantica_agent.core.paths.REPO_ROOT: Path`（`Path(__file__).resolve().parents[3]`）。以降のタスクはモジュールを新しい名前で import する（例：`semantica_agent.agent.tools.Knowledge`、`semantica_agent.review.flow.replay`、`semantica_agent.core.settings.load_settings`）。

- `build/__main__.py`・`web/__main__.py` は `raise SystemExit(main())` だけ。`build.pipeline.main`・`web.app.main` は旧 `build.main`・`web.main` と同じ。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_layers.py`

```python
LAYERS = {"core": set(), "review": {"core"}, "build": {"core", "review"},
          "agent": {"core", "review"}, "web": {"core", "review", "agent"}}

def test_layer_imports_point_one_way():
    # src/semantica_agent/<layer>/*.py を ast で読み、from semantica_agent.<other> の other が
    # LAYERS[layer] か自分自身であること。違反を「ファイル: import」の一覧で assert する。

def test_old_flat_modules_are_gone():
    # src/semantica_agent/ 直下の .py が {"__init__.py", "doctor.py"} だけであること
```

- [ ] **Step 2: 失敗を確かめる** — `uv run pytest tests/test_layers.py -v` → 2 件とも FAIL（直下にモジュールがあり、層のディレクトリが無い）
- [ ] **Step 3: `git mv` で移し、import とパスを直す** — import の書き換えは表の対応から機械的に行う（sed 等）。パッケージ内のデータファイル（prompts・schemas・static）は `Path(__file__).parent` 基準のまま新しい場所を指すこと。
- [ ] **Step 4: 確かめる** — `uv run pytest -m "not llm" -q` が整理前と同じ件数で通る（整理前の件数を Step 3 の前に `uv run pytest -m "not llm" -q | tail -1` で控えておく）。`uv run ruff check . && uv run ruff format --check .`。`uv run python -m semantica_agent.build --help`・`uv run python -m semantica_agent.web --help`・`uv run python -m semantica_agent.doctor` が動く。
- [ ] **Step 5: コミット** — `refactor: src/semantica_agent を core・review・build・agent・web に分ける`

______________________________________________________________________

### Task 2: `ReviewSession` を出し、SDK 版をその上に載せる

スキル：`superpowers:test-driven-development`。

**Files:**

- Create: `src/semantica_agent/agent/session.py`、`tests/test_session.py`
- Modify: `src/semantica_agent/agent/sdk.py`（`AgentSession` は `ReviewSession` を持ち、SDK の接続・メッセージの読み取り・取り消しだけを担う）、`src/semantica_agent/agent/trace.py`（`TraceRecorder` に `on_add`、`finish` に `runtime`）、`src/semantica_agent/agent/schemas/trace.schema.json`（任意の `runtime`）、`tests/test_sdk.py`、`tests/test_trace.py`

**Interfaces:**

- Consumes: Task 1 の新しいモジュール名。

- Produces（`agent/session.py`）:

  - `TOOL_NAMES: tuple[str, ...]`（旧 `agent.TOOL_NAMES` と同じ 6 つ、同じ順）
  - `tool_specs(k: Knowledge) -> dict[str, tuple[str, dict]]`：名前 → (説明, 入力スキーマ)。旧 `_descriptions` と `build_tools` の `schemas` をそのまま移す。
  - `PROMPT_PATH: Path`、`render_prompt(template: str, today: date) -> str`
  - `fallback_answer(texts: list[str]) -> dict`（旧 `_fallback_answer`）
  - `@dataclass(frozen=True) class ToolOutcome: text: str; is_error: bool`
  - `class ReviewSession`:
    - `__init__(self, k: Knowledge, settings: Settings, session_id: str, today: date, runtime: dict, on_event: Callable[[dict], None] | None = None, record_tool_calls: bool = True)`
    - 属性：`k`、`settings`、`session_id`、`state: SessionState`、`cg: ContextGraph`、`recorder: TraceRecorder | None`、`answer: dict | None`、`prompt_template`、`prompt_hash`、`system_prompt`（property）、`judge_calls_at_start: int`
    - `start_turn(self, question: str, record_user: bool = True) -> TraceRecorder`（旧 `_start_turn`。`record_user=False` なら `user` イベントを積まない）
    - `record_tool_call(self, name: str, args: dict, tool_use_id: str | None, via: str) -> None`
    - `async call_tool(self, name: str, args: dict) -> ToolOutcome`（旧 `_wrap.handler` の中身。`record_tool_calls=True` のとき、直前が `tool_call` でなければ `via="handler"` で積む）
    - `finish_turn(self, texts: list[str], model: str | None, status: str) -> dict`（旧 `_finish`＋`runtime`）
    - `save_turn(self, trace: dict) -> Path`（`save_trace(trace, settings.trace_root, self.cg)`）

- Produces（`agent/trace.py`）: `TraceRecorder(..., runtime: dict | None = None, on_add: Callable[[dict], None] | None = None)`、`add` は積んだ後に `on_add(event)` を呼ぶ。`finish(...)` の戻り値に `runtime` が入る（`None` なら入れない）。

- Produces（`agent/sdk.py`）: `AgentSession(k, settings, client_factory=..., session_id=None, today=None)` の公開の形（`ask`・`close`・`busy`・`session_id`・`state`・`recorder`）は変えない（`web/app.py` と既存テストが使う）。`build_options(sess)` に `env={"CLAUDE_CODE_DISABLE_CLAUDE_MDS": "1", "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1"}` を足す。`runtime={"kind": "agent-sdk", "cli_version": <同梱 CLI の版 or None>}`（版は Task 6 の `bundled_cli_version()` が出来るまで `None` でよい。Task 6 で差し替える）。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_session.py`（`tests/conftest.py` の合成オントロジーの `Knowledge` フィクスチャを使う）

```python
async def test_call_tool_records_call_and_result(knowledge, settings_tmp):
    s = ReviewSession(knowledge, settings_tmp, "s1", date(2026, 11, 19), {"kind": "agent-sdk", "cli_version": None})
    s.start_turn("問い")
    out = await s.call_tool("search_nodes", {"text": "出生"})
    assert not out.is_error
    assert [e["type"] for e in s.recorder.events] == ["user", "tool_call", "tool_result"]
    assert s.recorder.events[1]["via"] == "handler"

async def test_record_tool_calls_false_skips_handler_call(...):  # events == ["user", "tool_result"]
async def test_on_event_receives_every_event(...):               # on_event に積んだ順で全件届く
async def test_tool_error_is_recorded(...):                      # describe_node に無い ID → is_error、tool_result.is_error True
def test_finish_turn_includes_runtime(...):                      # trace["runtime"] == {"kind": "agent-sdk", "cli_version": None} かつ validate_trace が通る
def test_tool_specs_match_tool_names(knowledge):                 # set(tool_specs(k)) == set(TOOL_NAMES)
```

`tests/test_sdk.py` に足す：`test_options_disable_claude_md_and_memory`（`build_options(sess).env` に 2 つの変数が "1" で入る）。`tests/test_trace.py` に足す：`runtime` が無い既存のトレース（`tests/fixtures/traces/demo-001.json`）も `validate_trace` を通る。

- [ ] **Step 2: 失敗を確かめる** — `uv run pytest tests/test_session.py tests/test_sdk.py tests/test_trace.py -v` → 新しいテストが FAIL（`ImportError: semantica_agent.agent.session`）
- [ ] **Step 3: `session.py` を書き、`sdk.py` から移す** — `sdk.py` に残すのは `AgentSession`（`ReviewSession` を `self.review` に持つ）、`build_tools`（`tool_specs` と `review.call_tool` で `SdkMcpTool` を作る）、`_hooks`（`review.record_tool_call(..., via="hook")`）、`build_options`、メッセージの読み取りと取り消し。
- [ ] **Step 4: 確かめる** — `uv run pytest -m "not llm" -q` がすべて通る。
- [ ] **Step 5: コミット** — `refactor: 相談の処理を ReviewSession に出し、SDK 版をその上に載せる`

______________________________________________________________________

### Task 3: 記録の置き場（spool）と transcript の読み取り

スキル：`superpowers:test-driven-development`。

**Files:**

- Create: `src/semantica_agent/agent/spool.py`、`src/semantica_agent/agent/transcript.py`、`tests/test_spool.py`、`tests/test_transcript.py`、`tests/fixtures/claude_code/transcript.jsonl`
- Modify: `src/semantica_agent/core/settings.py`（`DEFAULT_SPOOL_ROOT = Path("output/claude-code")`、`Settings.spool_root`）

**Interfaces:**

- Produces（`agent/spool.py`。中身は JSON と JSONL のファイルだけ。仕様 §5.3）:

  - `class Spool`: `__init__(self, root: Path, session_id: str)`、`dir: Path`（`root / session_id`）
  - `write_session(self, info: dict) -> None` / `read_session(self) -> dict`（`session.json`：`model_requested`、`prompt_path`、`prompt_hash`、`ontology_info`、`runtime`。起動時に書く）
  - `begin_turn(self, question: str, transcript_path: str | None) -> int`（`turn.json` の番号を 1 進めて書き、新しい番号を返す。`started` は今の時刻）
  - `current_turn(self) -> dict | None`（`turn.json`：`turn`、`question`、`started`、`transcript_path`）
  - `append_event(self, turn: int, event: dict) -> None`（`turn-NNN.events.jsonl` に 1 行追記。`seq` は付けない）
  - `read_events(self, turn: int) -> list[dict]`
  - `write_state(self, turn: int, state: dict) -> None` / `read_state(self, turn: int) -> dict | None`（`turn-NNN.state.json`）
  - `last_case_states(self, before_turn: int) -> dict`（`before_turn` より前で最後の state の `case_states`。無ければ `{}`）
  - `mark_done(self, turn: int) -> None` / `is_done(self, turn: int) -> bool`（`turn-NNN.done`）
  - `open_turns(self) -> list[int]`（events ファイルがあって done が無いターン）
  - `log_error(self, message: str) -> None`（`hook-errors.log` に追記）

- Produces（`agent/transcript.py`）:

  - `@dataclass(frozen=True) class TranscriptItem: time: str; type: str  # "assistant_text" | "thinking"; text: str`
  - `@dataclass(frozen=True) class TurnMessages: items: list[TranscriptItem]; model: str | None`
  - `read_turn_messages(path: Path | None, since: str) -> TurnMessages`：`since`（ISO 時刻）以降の assistant の行から、text と thinking のブロックと `message.model` を取る。読めない行・知らない形の行は飛ばし、DEBUG ログに残す。ファイルが無ければ空。

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_spool.py`：

```python
def test_begin_turn_counts_up(tmp_path):        # 1, 2 と進み、current_turn()["question"] が最後の問い
def test_events_round_trip(tmp_path):           # append 2 件 → read_events が同じ順で 2 件
def test_open_turns_and_done(tmp_path):         # events のあるターン 1・2、1 を mark_done → open_turns() == [2]
def test_last_case_states_uses_previous_state(tmp_path):  # turn1 に state、turn3 から見ると turn1 の case_states
```

`tests/test_transcript.py`（フィクスチャは user 行・assistant の text 行・thinking 行・tool_use 行・壊れた JSON 行・未知の type 行を、時刻つきで含む。実際の Claude Code の transcript の 1 行の形 `{"type": "assistant", "timestamp": …, "message": {"model": …, "content": [...]}}` に合わせる）：

```python
def test_reads_text_and_thinking_after_since(): # since より前の行は入らない。items の type と text、model == "claude-sonnet-5-5"
def test_reads_unknown_lines_safely():          # 壊れた行・未知の行があっても例外にならず、件数が期待どおり
def test_missing_file_is_empty(tmp_path):       # TurnMessages([], None)
```

- [ ] **Step 2: 失敗を確かめる** — `uv run pytest tests/test_spool.py tests/test_transcript.py -v` → ImportError で FAIL
- [ ] **Step 3: `spool.py`・`transcript.py` を書く**。ファイル名のターン番号は 3 桁（`turn-001.events.jsonl`）。
- [ ] **Step 4: 確かめる** — 同じコマンドで PASS
- [ ] **Step 5: コミット** — `feat: Claude Code 版の記録の置き場と transcript の読み取り`

______________________________________________________________________

### Task 4: ターンを閉じてトレースにまとめる

スキル：`superpowers:test-driven-development`。

**Files:**

- Create: `src/semantica_agent/agent/turn_close.py`、`tests/test_turn_close.py`

**Interfaces:**

- Consumes: `Spool`（Task 3）、`read_turn_messages`（Task 3）、`TraceRecorder`・`save_trace`（Task 2）、`fallback_answer`（Task 2）。

- Produces: `close_turn(spool: Spool, turn: int, trace_root: Path, *, last_message: str | None = None, interrupted: bool = False) -> Path | None`

  - `is_done(turn)` なら何もせず `None`。
  - イベント：spool のイベント＋transcript の items（`assistant_text`・`thinking`）＋`interrupted` なら `error`（「ターンが中断されました（Stop が届かなかった）」）を、`time` の順に安定ソートして `seq` を 1 から振り直す。transcript から `assistant_text` が 1 件も取れず `last_message` があれば、それを `assistant_text` として足す。
  - state（無ければ `{"judged": False, "judgment": None, "case": None, "answer": None, "case_states": spool.last_case_states(turn), "initial_case_states": spool.last_case_states(turn)}`）と `read_session()` から `TraceRecorder` を作り、`finish(answer=state["answer"] or fallback_answer(texts), judgment=..., case=..., model_responded=transcript.model, status="error" if error イベントあり else "ok")`。
  - `ContextGraph`：`trace_root/<sid>/decisions.json` があれば `ContextGraph.load_from_file` で読んでから `save_trace(trace, trace_root, cg)`。保存後 `mark_done(turn)`。

- [ ] **Step 1: 失敗するテストを書く** — spool をテストの中で手で組む（session.json、turn.json、events、state）。

```python
def test_close_turn_builds_valid_trace(tmp_path):   # validate_trace が通り、runtime.kind == "claude-code"、seq が 1..n、assistant_text が transcript から入る
def test_close_turn_orders_by_time(tmp_path):        # user → tool_call → tool_result → assistant_text の順（time で）
def test_close_turn_without_tool_calls(tmp_path):    # state が無い：answer.submitted is False、flow_initial == 前のターンの case_states、status == "ok"
def test_interrupted_turn_is_error(tmp_path):        # interrupted=True → status == "error"、最後の error イベントの文言
def test_close_turn_twice_saves_once(tmp_path):      # 2 回目は None、decisions.json の判断は 1 件だけ増える
def test_falls_back_to_last_message(tmp_path):       # transcript が無い → last_message が assistant_text と answer.answer に入る
def test_replayed_flow_matches(tmp_path):            # review.flow.replay(trace["events"], trace["flow_initial"]) == trace["flow"]
```

- [ ] **Step 2: 失敗を確かめる** — `uv run pytest tests/test_turn_close.py -v` → FAIL
- [ ] **Step 3: `close_turn` を書く**（関数は 50 行以内に分ける：イベントの合成、state の既定、保存）。
- [ ] **Step 4: 確かめる** — PASS
- [ ] **Step 5: コミット** — `feat: Claude Code 版のターンをトレースにまとめる`

______________________________________________________________________

### Task 5: MCP サーバーと hook

スキル：`superpowers:test-driven-development`。

**Files:**

- Create: `src/semantica_agent/agent/mcp_server.py`、`src/semantica_agent/agent/claude_code.py`（このタスクでは hook の部分だけ）、`tests/test_mcp_server.py`、`tests/test_claude_code_hooks.py`

**Interfaces:**

- Consumes: `ReviewSession`・`tool_specs`・`TOOL_NAMES`（Task 2）、`Spool`（Task 3）、`close_turn`（Task 4）。

- Produces（`agent/mcp_server.py`）:

  - `class SpoolBackedSession`：`__init__(self, k: Knowledge, settings: Settings, spool: Spool, today: date)`。中に `ReviewSession(..., runtime=spool.read_session()["runtime"], on_event=<spool の今のターンに追記>, record_tool_calls=False)` を持つ。
  - `async SpoolBackedSession.call_tool(self, name: str, args: dict) -> ToolOutcome`：`spool.current_turn()` の番号が `ReviewSession.state.turn` より進んでいれば `start_turn(question, record_user=False)` してから呼ぶ。`state.turn` を spool の番号にそろえる。呼んだ後に `write_state(turn, {...})`（`judged`、`judgment`、`case`（`case_record`）、`answer`、`case_states`＝`state.last_case_states`、`initial_case_states`）。ターンが無い（`turn.json` が無い）ときはエラーの `ToolOutcome` を返す。
  - `build_server(sess: SpoolBackedSession, k: Knowledge) -> mcp.server.lowlevel.Server`（名前 `"koseki"`。`on_list_tools` は `tool_specs` から、`on_call_tool` は `sess.call_tool` から `CallToolResult(content=[TextContent], isError=...)`）
  - `main() -> int`：`load_settings`、`KOSEKI_SESSION_ID` が無ければ `ConfigError` で止める、`Knowledge.load(REPO_ROOT)`、`stdio_server()` で `run`。`python -m semantica_agent.agent.mcp_server` で起動。

- Produces（`agent/claude_code.py`）:

  - `handle_hook(name: str, payload: dict, env: Mapping[str, str], settings: Settings) -> int`。`name` は `"prompt"`（UserPromptSubmit）・`"pre-tool"`（PreToolUse）・`"stop"`（Stop）。
    - 共通：`payload["session_id"] != env["KOSEKI_SESSION_ID"]` なら何も書かず、標準エラーに理由を出して `0` を返す。
    - `prompt`：`open_turns()` を `close_turn(..., interrupted=True)` で閉じ、`begin_turn(payload["prompt"], payload.get("transcript_path"))`、`user` イベントを追記。
    - `pre-tool`：`tool_name` から `mcp__koseki__` を外した名前が `TOOL_NAMES` にあれば、`tool_call`（`tool`、`args=tool_input`、`tool_use_id`、`via="hook"`、`time`）を追記。
    - `stop`：今のターンを `close_turn(..., last_message=payload.get("last_assistant_message"))`。
    - 例外は `spool.log_error` に残して `0` を返す（ターンを止めない）。
  - `main(argv: list[str] | None = None) -> int`：`hook <name>` で stdin の JSON を読んで `handle_hook`。（`launch` は Task 6 で足す）

- [ ] **Step 1: 失敗するテストを書く**

`tests/test_claude_code_hooks.py`（payload は Claude Code の stdin の形：`session_id`、`transcript_path`、`cwd`、`hook_event_name`、`prompt` / `tool_name`・`tool_input`・`tool_use_id` / `last_assistant_message`）：

```python
def test_prompt_hook_starts_turn(tmp_path):          # turn.json の turn == 1、events に user
def test_pre_tool_hook_records_koseki_only(tmp_path): # mcp__koseki__run_cq → tool_call(via="hook")、mcp__other__x → 何も書かない
def test_hook_ignores_other_session(tmp_path, capsys):# session_id が違う → ファイルが増えない、stderr に理由、戻り値 0
def test_next_prompt_closes_open_turn(tmp_path):     # turn1 に Stop が来ないまま prompt → turn1 のトレースが status "error" で保存され、turn.json は 2
def test_hook_error_is_logged_not_raised(tmp_path):  # close_turn を例外にする monkeypatch → hook-errors.log に残り、戻り値 0
```

`tests/test_mcp_server.py`：

```python
async def test_tool_list_matches_sdk(knowledge):      # build_server の list_tools の名前とスキーマ == tool_specs
async def test_call_tool_follows_spool_turn(...):     # begin_turn → call_tool → events に tool_result（tool_call は無い）、state.json がある、ReviewSession.state.turn == 1
async def test_call_tool_without_turn_is_error(...):  # turn.json が無い → is_error
async def test_two_turns_end_to_end(...):            # prompt hook → pre-tool hook → call_tool(judge_birth_case) → call_tool(submit_answer) → stop hook、を 2 ターン。trace 2 件が validate_trace を通り runtime.kind == "claude-code"、2 件目の flow_initial == 1 件目の case_states
@pytest.mark.slow
async def test_stdio_server_answers_list_tools(...):  # mcp.client の stdio クライアントで python -m semantica_agent.agent.mcp_server を起動（KOSEKI_SESSION_ID と spool_root を env で渡す）し、6 つのツールが返る
```

- [ ] **Step 2: 失敗を確かめる** — `uv run pytest tests/test_mcp_server.py tests/test_claude_code_hooks.py -v` → FAIL
- [ ] **Step 3: `mcp_server.py` と `claude_code.py` の hook 部分を書く**。`Settings` に spool の置き場を渡せるよう、テストでは `replace(settings, spool_root=tmp_path / "cc", trace_root=tmp_path / "traces")` を使う。MCP サーバーでは `KOSEKI_SPOOL_ROOT`・`KOSEKI_TRACE_ROOT` の環境変数があればそれを使う（テスト用。`load_settings` で読む）。
- [ ] **Step 4: 確かめる** — `uv run pytest tests/test_mcp_server.py tests/test_claude_code_hooks.py -v`（slow を含む）→ PASS
- [ ] **Step 5: コミット** — `feat: Claude Code 版の MCP サーバーと hook`

______________________________________________________________________

### Task 6: 起動（launch）と `claude-code-agent/`

スキル：`superpowers:test-driven-development`。

**Files:**

- Modify: `src/semantica_agent/agent/claude_code.py`（launch を足す）、`src/semantica_agent/agent/sdk.py`（`runtime.cli_version` に `bundled_cli_version()`）、`src/semantica_agent/doctor.py`（同梱 CLI の有無と版を表示）
- Create: `claude-code-agent/run.sh`、`claude-code-agent/.mcp.json`、`claude-code-agent/.claude/settings.json`、`claude-code-agent/README.md`、`tests/test_claude_code_launch.py`

**Interfaces:**

- Consumes: `Spool`（Task 3）、`close_turn`（Task 4）、`render_prompt`・`PROMPT_PATH`（Task 2）、`ontology_info`（`agent/trace.py`）、`validate_integrity`（`core/turtle_io.py`）。

- Produces（`agent/claude_code.py`）:

  - `AGENT_DIR = REPO_ROOT / "claude-code-agent"`
  - `bundled_cli() -> Path`（`claude_agent_sdk` パッケージの `_bundled/claude`。無ければ `ConfigError("Agent SDK 同梱の Claude Code が見つかりません: <パス>。uv sync を確かめてください")`）
  - `bundled_cli_version(cli: Path | None = None) -> str | None`（`<cli> --version` の先頭の版。失敗は `None` と WARNING）
  - `installed_plugin_ids(cli: Path) -> list[str]`（`<cli> plugin list --json` の `id` を重複なしで。失敗は `ConfigError`）
  - `@dataclass(frozen=True) class LaunchPlan: cli: Path; argv: list[str]; env: dict[str, str]; cwd: Path; session_id: str; prompt_file: Path`
  - `build_launch_plan(settings: Settings, session_id: str, prompt_file: Path, plugin_ids: list[str], question: str | None, base_env: Mapping[str, str], cli: Path) -> LaunchPlan`（純粋関数。argv と env は Global Constraints のとおり。`--settings` は `json.dumps({"enabledPlugins": {id: False for id in plugin_ids}})`）
  - `launch(argv: list[str] | None = None, env: Mapping[str, str] = os.environ, run: Callable = subprocess.run) -> int`：`load_settings(env)` → `Knowledge.load(REPO_ROOT)` と `validate_integrity` → session_id（`uuid4()`）→ `prompt.md` を書く → `Spool.write_session(...)`（`runtime={"kind": "claude-code", "cli_version": bundled_cli_version()}`）→ `run(plan.argv, env=plan.env, cwd=plan.cwd)` → 終了後に `open_turns()` を `close_turn(..., interrupted=True)` → `claude` の終了コードを返す。
  - `main` に `launch [質問]` を足す。

- `claude-code-agent/run.sh`：`exec uv run --project "$(dirname "$0")/.." --no-sync python -m semantica_agent.agent.claude_code launch "$@"`（実行権限を付ける）

- `claude-code-agent/.mcp.json`：`{"mcpServers": {"koseki": {"command": "uv", "args": ["run", "--project", "${KOSEKI_REPO_ROOT}", "--no-sync", "python", "-m", "semantica_agent.agent.mcp_server"]}}}`

- `claude-code-agent/.claude/settings.json`：`autoMemoryEnabled: false`、`enabledPlugins: {"superpowers@claude-plugins-official": false}`、hooks（UserPromptSubmit・PreToolUse（matcher `mcp__koseki__.*`）・Stop。コマンドは `uv run --project "$KOSEKI_REPO_ROOT" --no-sync python -m semantica_agent.agent.claude_code hook <prompt|pre-tool|stop>`）

- `claude-code-agent/README.md`：起動の仕方（`./claude-code-agent/run.sh`、`./claude-code-agent/run.sh "質問"`）、既定モデルは sonnet で `AGENT_MODEL` で変えられること、トレースの置き場と Web 画面での開き方、仕様 §7 の違いの表。

- [ ] **Step 1: 失敗するテストを書く** — `tests/test_claude_code_launch.py`

```python
def test_plan_argv_and_env(tmp_path):
    plan = build_launch_plan(settings, "sid", tmp_path / "prompt.md", ["superpowers@claude-plugins-official"], None, {"PATH": "/bin"}, Path("/x/claude"))
    a = plan.argv
    assert a[0] == "/x/claude"
    assert a[a.index("--model") + 1] == "claude-sonnet-5-5"        # 既定は sonnet
    assert a[a.index("--tools") + 1] == ""
    assert a[a.index("--setting-sources") + 1] == "project"
    assert a[a.index("--allowedTools") + 1] == "mcp__koseki__*"
    assert a[a.index("--permission-mode") + 1] == "dontAsk"
    assert {"--strict-mcp-config", "--disable-slash-commands"} <= set(a)
    assert json.loads(a[a.index("--settings") + 1]) == {"enabledPlugins": {"superpowers@claude-plugins-official": False}}
    assert "-p" not in a
    assert plan.env["CLAUDE_CODE_DISABLE_CLAUDE_MDS"] == "1" and plan.env["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] == "1"
    assert plan.env["KOSEKI_SESSION_ID"] == "sid" and plan.cwd == AGENT_DIR

def test_plan_with_question_adds_print_and_max_turns(...):  # "-p" の次が質問、"--max-turns" の次が "20"
def test_model_from_env(...):                               # AGENT_MODEL=claude-opus-5-5 の settings → --model が opus
def test_launch_refuses_api_key(...):                       # env に ANTHROPIC_API_KEY → ConfigError、run は呼ばれない
def test_launch_writes_prompt_with_today(...):              # run を偽物に差し替え、prompt.md に今日の日付、session.json の runtime.kind == "claude-code"
def test_launch_closes_open_turns_after_exit(...):          # 偽の run の中で prompt hook だけ呼んでおく → 終了後にそのターンが status "error" で保存
def test_missing_bundled_cli(monkeypatch):                  # パッケージの場所を空のディレクトリに → ConfigError に「同梱」
def test_plugin_list_failure(...):                          # run が非 0 → ConfigError
def test_agent_dir_files_are_consistent():                  # .mcp.json の koseki の args に semantica_agent.agent.mcp_server、settings.json の 3 つの hook と matcher "mcp__koseki__.*"、autoMemoryEnabled False、run.sh が実行可能
```

`tests/test_doctor.py` に足す：同梱 CLI の行が出る。

- [ ] **Step 2: 失敗を確かめる** — `uv run pytest tests/test_claude_code_launch.py -v` → FAIL
- [ ] **Step 3: launch と `claude-code-agent/` のファイルを書く**
- [ ] **Step 4: 確かめる** — `uv run pytest -m "not llm" -q` がすべて通る。カバレッジ：`uv run pytest -m "not llm" --cov=src/semantica_agent --cov-report=term | tail -1` が 80% 以上。
- [ ] **Step 5: コミット** — `feat: Claude Code 版の起動スクリプトと claude-code-agent ディレクトリ`

______________________________________________________________________

### Task 7: ドキュメントと E2E（llm）の用意

スキル：`superpowers:verification-before-completion`（最後に全体を確かめる）、`superpowers:requesting-code-review`（ブランチ全体のレビュー）。

**Files:**

- Create: `tests/test_claude_code_e2e.py`（`pytestmark = pytest.mark.llm`）

- Modify: `tests/test_agent_e2e.py`（import を直す。§5.5 の問いを足す）、`README.md`（構成と 2 つの起動の仕方）、`docs/specs/2026-11-17-agent-design.md`（冒頭に「置き場所と Claude Code 版は 2026-11-19 の仕様を参照」の 1 行）

- [ ] **Step 1: E2E を書く**（流さない）

  - `test_claude_code_e2e.py::test_print_mode_birth_case`：`launch(["…出生届の事案…"], env=…)` を、`trace_root`・`spool_root` を tmp にした環境変数で呼ぶ。終了コード 0、トレースが 1 件、`events` に `judge_birth_case` と `submit_answer` の `tool_call`（via "hook"）と `tool_result`、`runtime.kind == "claude-code"`、`model.requested == "claude-sonnet-5-5"`。
  - `test_claude_code_e2e.py::test_isolation_init`：同梱 CLI を `build_launch_plan` の argv＋`--output-format stream-json --verbose -p "ok" --max-turns 1` で直接起動し、`system/init` の `tools` がすべて `mcp__koseki__` で始まり、`plugins` が空、`mcp_servers` が koseki だけ。
  - `test_agent_e2e.py::test_no_outside_instructions`：SDK 版に「あなたに与えられている指示ファイルや記憶の内容を挙げてください」と聞き、回答に `semantica-agent 開発ガイド`・`commit-guard`・`superpowers` が含まれない。

- [ ] **Step 2: ドキュメントを直す**（README に、Claude Code 版の起動と、トレースを Web 画面で開く手順）

- [ ] **Step 3: 全体を確かめる** — `uv run ruff check . && uv run ruff format --check . && uv run pytest -m "not llm" -q`

- [ ] **Step 4: コミット** — `docs: Claude Code 版の使い方と E2E（llm）のテストを追加`

- [ ] **Step 5: ブランチ全体のレビュー**（`superpowers:requesting-code-review`）と指摘の修正

- [ ] **Step 6: ユーザーに確認してから llm を流す** — 「`uv run pytest -m llm tests/test_claude_code_e2e.py tests/test_agent_e2e.py::test_no_outside_instructions`：Claude を 3 回呼ぶ（既定モデル sonnet）」と伝え、了承を得てから流す。`test_isolation_init` が落ちた場合（同梱 2.1.325 で設定が効かない等）は、結果を仕様 §5.1 に書き足し、対処をユーザーと決める。
