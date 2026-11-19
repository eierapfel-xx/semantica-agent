#!/usr/bin/env bash
# 審査支援エージェントを Claude Code で起動する。引数に質問を渡すと 1 問で終わる（-p）。
# 中身は semantica_agent.agent.claude_code launch。設定とオプションの説明は README.md。
set -euo pipefail
exec uv run --project "$(cd "$(dirname "$0")/.." && pwd)" --no-sync \
  python -m semantica_agent.agent.claude_code launch "$@"
