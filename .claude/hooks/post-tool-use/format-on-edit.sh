#!/usr/bin/env bash
# PostToolUse(Edit|Write|apply_patch): 編集されたファイルを自動整形する（非ブロック）。
set -euo pipefail

input=$(cat)
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)

if [ -x "$repo_root/.venv/bin/python" ]; then
  PY="$repo_root/.venv/bin/python"
else
  PY="python3"
fi

mapfile -t file_paths < <(printf '%s' "$input" | "$PY" -c '
import json, sys


def patch_paths(command):
    prefixes = (
        "*** Add File: ",
        "*** Update File: ",
        "*** Delete File: ",
        "*** Move to: ",
    )
    for line in command.splitlines():
        for prefix in prefixes:
            if line.startswith(prefix):
                path = line[len(prefix):].strip()
                if path:
                    yield path
                break


try:
    ti = json.load(sys.stdin).get("tool_input", {}) or {}
    paths = []
    for key in ("file_path", "notebook_path"):
        value = ti.get(key)
        if isinstance(value, str) and value:
            paths.append(value)
    command = ti.get("command")
    if not paths and isinstance(command, str):
        paths.extend(patch_paths(command))
    for path in dict.fromkeys(paths):
        print(path)
except Exception:
    pass
' 2>/dev/null) || file_paths=()

for file_path in "${file_paths[@]}"; do
  [ -z "$file_path" ] && continue
  case "$file_path" in
    /*) abs="$file_path" ;;
    *) abs="$repo_root/$file_path" ;;
  esac
  [ -f "$abs" ] || continue

  # リポジトリ外のファイル（~/.claude 配下の memory など）は整形対象にしない。
  # 作業対象はこのリポジトリ直下のみ（AGENTS.md「言語と範囲」）。
  resolved_path=$(realpath -e "$abs" 2>/dev/null) || continue
  case "$resolved_path" in
    "$(realpath -e "$repo_root")"/*) ;;
    *) continue ;;
  esac

  case "$resolved_path" in
    *.py) uv run --no-sync ruff format "$resolved_path" >/dev/null 2>&1 || true ;;
    *.md) uv run --no-sync mdformat "$resolved_path" >/dev/null 2>&1 || true ;;
  esac
done
exit 0
