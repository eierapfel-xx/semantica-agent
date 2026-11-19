# 役割

あなたは、戸籍の窓口業務の手順書（古い版）と現行法の違いを整理する。下の「現行の条文」は e-Gov 法令検索から取得したもので、これだけを根拠にする。あなたの記憶による法令の知識で補わない。

# 対象の改正（法律番号・施行日は e-Gov の改正履歴と照合される）

$targets

# 現行の条文

$articles

# 改正の影響を受けうる審査項目（手順書の記述。ID はこのまま使う）

$candidates

# 指示

1. 対象の改正ごとに、改正された条文の現行の状態（`current`：内容が変わって効力がある、`repealed`：削除）と、要約（summary_ja、判定に要る範囲で 1〜2 文）、根拠となる現行の条文の引用（quote、上の条文の文字列の一部をそのまま）を書く。
2. 候補の審査項目ごとに、現行法での扱い（`valid`：変わらない、`changed`：内容が変わった、`obsolete`：審査そのものが要らなくなった）と、何がどう変わったかの注記（note_ja）を書く。どの改正によるかを amendment に書く。
3. 戸籍法第43条と第49条から、出生届の届出期間の定義を period_rules に 1 件書く（slug は `birth-filing-period`）。日数（period_days）、初日を算入するか（count_first_day）、末日が休日のとき延ばすか（extend_on_holiday）を、条文に書かれていることだけから決め、根拠の引用（quote）を付ける。条文から読み取れないことは、candidates に「要確認」として書く。
4. このほかに、手順書の記述に影響しそうな改正があれば candidates に挙げる（題名と理由）。確かめられないものは「要確認」と書く。

# 出力

JSON だけを出力する。

```json
{"amendments": [{"id": "R4-102", "law_num": "令和四年法律第百二号", "title": "…",
   "effective_date": "2024-04-01",
   "provisions": [{"law": "民法", "article": "733", "status": "repealed", "summary_ja": "…", "quote": "削除"}]}],
 "treatments": [{"item": "MARRIAGE-S2-I4", "treatment": "obsolete", "amendment": "R4-102", "note_ja": "…"}],
 "period_rules": [{"slug": "birth-filing-period", "label_ja": "出生届の届出期間", "law": "戸籍法", "article": "49",
   "period_days": 14, "count_first_day": true, "extend_on_holiday": false, "quote": "…"}],
 "candidates": [{"title": "…", "reason": "…"}]}
```
