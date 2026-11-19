"""data.json を template.html に埋め込んで flow-replay.html を作る。

使い方（リポジトリの直下で）:
  uv run python .archify/flow-replay-20261119-212500/src/run_once.py
  （↑ エージェントを 1 回実行する。Claude Pro の枠を使う）
  uv run python .archify/flow-replay-20261119-212500/src/extract.py <data.json>
  uv run python .archify/flow-replay-20261119-212500/src/build.py <data.json> <out.html>
"""

import sys
from pathlib import Path

data = Path(sys.argv[1]).read_text("utf-8").replace("</", "<\\/")
tpl = (Path(__file__).parent / "template.html").read_text("utf-8")
Path(sys.argv[2]).write_text(tpl.replace("__DATA__", data), encoding="utf-8")
