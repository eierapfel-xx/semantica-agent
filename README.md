# semantica-agent

市区町村の窓口業務（戸籍届出など）の手順書を題材に、[semantica](https://github.com/semantica-agi/semantica) でオントロジーを作り、そのオントロジーを使うエージェントを Claude Agent SDK で作る。

## セットアップ

```bash
uv sync
uv run python -m semantica_agent.doctor   # 環境の確認
```

エージェントは Claude Code のログイン状態（Claude Pro）で動く。先に `claude` で一度ログインしておく。

開発の決まりは `AGENTS.md`（`CLAUDE.md` はそのシンボリックリンク）。
