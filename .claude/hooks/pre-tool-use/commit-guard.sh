#!/usr/bin/env bash
# PreToolUse(Bash): main への直接コミット・main への push・データ/大容量ファイルの混入を禁止し、コミット前に品質チェックを行う。
set -euo pipefail

input=$(cat)
CG_START_CWD="$PWD"
export CG_START_CWD
repo_root=$(git rev-parse --show-toplevel 2>/dev/null || pwd)
cd "$repo_root"

if [ -x "$repo_root/.venv/bin/python" ]; then
  PY="$repo_root/.venv/bin/python"
else
  PY="python3"
fi

branch=$(git branch --show-current 2>/dev/null || echo "")

# コマンドを分類する：commit / push-main / push-unknown / none。
#   push-main    … main を送り先に含む push（main は PR を `gh pr merge` でマージして更新する）
#   push-unknown … push だが送り先を判定できない。止める側に倒す（fail closed）
# refspec なしの push や `HEAD` の送り先は、コマンド中の `cd` / `git -C` の移動先で現在のブランチを調べて決める。
# 相対パスの起点は payload の cwd（無ければ repo root へ移動する前の CG_START_CWD）。
kind=$(printf '%s' "$input" | "$PY" -c '
import json, os, shlex, subprocess, sys

try:
    data = json.load(sys.stdin)
except Exception:
    print("none")
    sys.exit(0)
cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""
# 相対パスの cd はセッションの cwd から解決する（hook は repo root に移動してから動くため）。
start_cwd = data.get("cwd") or os.environ.get("CG_START_CWD") or os.getcwd()

# git global flags that take a SEPARATE-argument value (must skip flag + its value).
VALUE_FLAGS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix", "--exec-path", "--config-env"}
# git push のオプションのうち、値を別の引数で取るもの。
PUSH_VALUE_FLAGS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec"}
SHELLS = {"bash", "sh", "zsh", "dash", "fish"}
# シェルの区切り・リダイレクト。punctuation_chars で独立したトークンになる。
OPERATOR_CHARS = set("();<>|&")
PRIORITY = {"none": 0, "commit": 1, "push-unknown": 2, "push-main": 2}


class Unparsable(Exception):
    pass


def split(s):
    try:
        lex = shlex.shlex(s, posix=True, punctuation_chars=True)
        lex.whitespace_split = True
        return list(lex)
    except ValueError:
        # 解釈できないコマンドに push が含まれていれば、送り先が分からないので止める。
        if "push" in s.split():
            raise Unparsable()
        return s.split()


def is_operator(tok):
    return tok != "" and set(tok) <= OPERATOR_CHARS


def branch_at(cwd):
    try:
        out = subprocess.run(["git", "-C", cwd, "branch", "--show-current"], capture_output=True, text=True, check=True)
    except Exception:
        return None
    return out.stdout.strip()


def is_main_dst(dst):
    # 空（コロンだけの matching push）、ワイルドカード、heads/main も main を更新しうる。
    return dst == "" or "*" in dst or dst == "main" or dst.endswith("heads/main")


def classify_push(args, cwd):
    positional = []
    tags_only = False
    i = 0
    while i < len(args):
        a = args[i]
        if is_operator(a):
            # 2>&1 の 2 はリダイレクトの fd 番号で、refspec ではない。
            if positional and positional[-1].isdigit() and a.startswith((">", "<")):
                positional.pop()
            break
        if a in ("--all", "--mirror"):
            return "push-main"
        if a == "--tags":
            tags_only = True
        elif a in PUSH_VALUE_FLAGS:
            i += 1
        elif not a.startswith("-"):
            positional.append(a)
        i += 1
    refspecs = positional[1:]
    needs_branch = not refspecs and not tags_only
    for spec in refspecs:
        spec = spec.lstrip("+")
        if ":" in spec:
            if is_main_dst(spec.split(":", 1)[1]):
                return "push-main"
        elif is_main_dst(spec):
            return "push-main"
        elif spec in ("HEAD", "@"):
            needs_branch = True
    if not needs_branch:
        return "none"
    # refspec なし・HEAD は、その場所の現在のブランチを送る。
    branch = branch_at(cwd)
    if branch is None:
        return "push-unknown"
    return "push-main" if branch == "main" else "none"


def worst(a, b):
    return a if PRIORITY[a] >= PRIORITY[b] else b


def scan(tokens, cwd):
    # commit を見つけても走査を続け、main への push があればそれを優先して返す。
    # bash -c "..." / eval ... 等の入れ子シェルも再帰探索し、cd の移動先を追う。
    result = "none"
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        base = tok.rsplit("/", 1)[-1]
        if tok == "cd" and i + 1 < len(tokens) and not is_operator(tokens[i + 1]):
            cwd = os.path.join(cwd, os.path.expanduser(tokens[i + 1]))
            i += 2
            continue
        if tok == "git" or tok.endswith("/git"):
            git_cwd = cwd
            j = i + 1
            while j < len(tokens) and tokens[j].startswith("-"):
                if tokens[j] == "-C" and j + 1 < len(tokens):
                    git_cwd = os.path.join(git_cwd, os.path.expanduser(tokens[j + 1]))
                j += 2 if tokens[j] in VALUE_FLAGS else 1
            if j < len(tokens) and tokens[j] == "commit":
                result = worst(result, "commit")
            elif j < len(tokens) and tokens[j] == "push":
                result = worst(result, classify_push(tokens[j + 1 :], git_cwd))
        elif base in SHELLS:
            k = i + 1
            while k < len(tokens) and not is_operator(tokens[k]):
                if tokens[k] == "-c" and k + 1 < len(tokens):
                    result = worst(result, scan(split(tokens[k + 1]), cwd))
                    break
                k += 1
        elif tok == "eval":
            rest = []
            for t in tokens[i + 1 :]:
                if is_operator(t):
                    break
                rest.append(t)
            result = worst(result, scan(split(" ".join(rest)), cwd))
        i += 1
    return result


try:
    print(scan(split(cmd), start_cwd))
except Unparsable:
    print("push-unknown")
' 2>/dev/null) || kind="none"

case "$kind" in
  push-main)
    echo "[commit-guard] main への push は禁止です。main へは PR を作り gh pr merge でマージしてください。" >&2
    exit 2
    ;;
  push-unknown)
    echo "[commit-guard] push の送り先を判定できないため止めました（main への push を防ぐため）。コマンドを単純な形にしてください。" >&2
    exit 2
    ;;
  commit) ;;
  *) exit 0 ;;
esac

# (1) main 保護（fail fast）
if [ "$branch" = "main" ]; then
  echo "[commit-guard] main への直接コミットは禁止です。feat/*, fix/*, chore/* ブランチで作業してください。" >&2
  exit 2
fi

# (2) データ/大容量ファイルの混入チェック（fail fast）。
#     中間生成物・実行結果・埋め込みなどを誤って git に入れると履歴から消すのが高コストなため、
#     コミット前に機械的に弾く。オントロジー（ontology/*.ttl 等）は成果物なので対象外。
if [ "${COMMIT_GUARD_ALLOW_LARGE:-0}" != "1" ]; then
  # 閾値はハードコードせず環境変数で上書き可能にする。数値以外が来たら既定値へ戻す（入力検証）。
  max_mb="${COMMIT_GUARD_MAX_FILE_MB:-5}"
  case "$max_mb" in
    ''|*[!0-9]*) max_mb=5 ;;
  esac
  max_bytes=$((max_mb * 1024 * 1024))

  # `git commit -a` は未追跡ファイルを取り込まないため、事故の主経路である
  # 「git add した新規データファイル」はステージ済み一覧(--cached)で捕捉できる。
  violations=""
  while IFS= read -r -d '' path; do
    reason=""
    case "$path" in
      # データ・実行結果の置き場は中身に関わらず git 管理外（AGENTS.md「リポジトリの置き場所」参照）。
      data/*|output/*)
        reason="データ/実行結果ディレクトリ配下" ;;
      # 配列データ・埋め込み・DB・ベクトルインデックスの拡張子。1件が小さくても大量混入するため拡張子で弾く。
      *.npy|*.npz|*.parquet|*.feather|*.pkl|*.sqlite|*.sqlite3|*.db|*.faiss|*.index)
        reason="データ/インデックスの拡張子" ;;
    esac
    if [ -z "$reason" ]; then
      # ステージ済み blob の実サイズで判定し、作業ツリー側の状態に依存させない。
      size=$(git cat-file -s ":$path" 2>/dev/null || echo 0)
      case "$size" in
        ''|*[!0-9]*) size=0 ;;
      esac
      if [ "$size" -gt "$max_bytes" ]; then
        reason="${max_mb}MB 超 (${size} bytes)"
      fi
    fi
    if [ -n "$reason" ]; then
      violations="${violations}  - ${path} … ${reason}"$'\n'
    fi
  done < <(git diff --cached --name-only --diff-filter=ACM -z)

  if [ -n "$violations" ]; then
    echo "[commit-guard] データ/大容量ファイルはコミットできません:" >&2
    printf '%s' "$violations" >&2
    echo "[commit-guard] .gitignore に追加するか、意図的なコミットであれば COMMIT_GUARD_ALLOW_LARGE=1 を設定してください。" >&2
    exit 2
  fi
fi

# (3) 品質チェック。プロジェクト設定が無ければチェック不能としてスキップ（Fail safe）。
[ -f "$repo_root/pyproject.toml" ] || exit 0
if ! uv run --no-sync ruff --version >/dev/null 2>&1; then
  echo "[commit-guard] ruff 未検出のため品質チェックをスキップ（Fail safe）" >&2
  exit 0
fi

if ! uv run --no-sync ruff check . ; then
  echo "[commit-guard] ruff check 失敗のため commit をブロックします。" >&2
  exit 2
fi
if ! uv run --no-sync ruff format --check . ; then
  echo "[commit-guard] 未整形ファイルがあります（ruff format）。commit をブロックします。" >&2
  exit 2
fi

# (4) pytest。tests/ を、重いテスト(slow) と Claude を実際に呼ぶテスト(llm) を除いて流す。
#     llm は Claude Pro の利用枠を消費するので、コミットのたびには流さない（AGENTS.md「テスト」参照）。
if [ -d "$repo_root/tests" ]; then
  markers="${COMMIT_GUARD_PYTEST_MARKERS:-not slow and not llm}"
  set +e
  uv run --no-sync pytest -q -m "$markers" tests
  rc=$?
  set -e
  # exit 5 = テストが1件も収集されなかった。失敗扱いにしない。
  if [ "$rc" -ne 0 ] && [ "$rc" -ne 5 ]; then
    echo "[commit-guard] pytest 失敗のため commit をブロックします。" >&2
    exit 2
  fi
fi
exit 0
