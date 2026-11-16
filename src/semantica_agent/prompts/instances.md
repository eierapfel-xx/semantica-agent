# 役割

あなたは、戸籍の窓口業務の手順書から、オントロジーのインスタンス（工程・手順項目・審査項目・書類・条文）を起こす。業務は「$business」。

# 入力

## 手順書の行（`row_id | 業務 | 区分 | 業務手順 | 備考`）

PDF の 1 行が 1 行になっている。1 つの項目が複数行に折り返していることがある。備考の条文も行をまたいで折り返す。

$rows

## スキーマ（固定済み。これ以外のクラス・プロパティは使わない）

$schema

## 既にある法令

$laws

## 使える語彙（日本語名。これ以外の名前は使わず、要るときは new_vocab で提案する）

$vocab

# 指示

1. 区分（「1.受付」など）ごとに工程を 1 つ作る。`number` は区分の番号、`label` は番号を除いた名前。
2. 業務手順の (1)・①・○・〇・★・※ ごとに項目を 1 つ作る。「（〜場合には…する。）」のような括弧書きも独立した項目にする。複数行にまたがる項目は 1 つにまとめる。入れ子（(1) の下の ① など）は `children` に入れる。括弧書きや ※ の親は、PDF 上の位置ではなく意味で決める（例：「学齢に達した子の出生届については照会する」は、直前の「生まれたとき」の項目ではなく、工程の直下に置く）。
3. `kind` は、確認・審査（「〜か」「〜を確認する」）なら `check`、それ以外の作業なら `task`、説明や補足なら `note`。
4. 項目ごとに、適用条件（conditions）、必要書類（documents）、記載事項（record_items）、関係者（roles）、照会・通知・送付の先（escalates_to）を、上の語彙の日本語名で埋める。当てはまらなければ空の配列。
5. `★`（「〜が満たされたら次の工程に移行する」）の項目は、移行先の工程の番号を `prerequisite_for` に書く。
6. 備考の条文は、条文ごとに `{"law", "article", "branch", "paragraph", "item", "normalization_note"}` に分ける。`law` は正式名（「住基法」は「住民基本台帳法」）。「第27条の2」は article=27, branch=2。法令名が省略された条文（「第53条、第53条の2」）は直前の法令名を引き継ぐ。明らかな誤記（「第27条2」→ 第27条の2）を直したら `normalization_note` に書く。条文でない備考（「記入例を用意する」など）は `notes` に書く。
7. 各項目に、使った行の `row_ids`、備考を読んだ行の `remark_row_ids`（備考が折り返していれば全部の行）、原文の引用 `quote`（業務手順の文字列の一部をそのまま。改行をまたいでよい）を付ける。
8. 備考の条文がどの項目に対応するかは、行の並びで判断する。自信が無ければ `"alignment": "uncertain"` にする。
9. 業務の表のすべての行を、どれかの項目（row_ids か remark_row_ids）か `notes` に使う。脚注は `notes` に入れてよい。
10. 手順書に無いことは書かない。書く必要があれば `"speculative": true` と `reason` を付ける。

# 出力

JSON だけを出力する。IRI は書かない。

```json
{"business": "$business",
 "steps": [{"number": 2, "label": "審査", "row_ids": ["p2-r20"], "cites": [],
   "items": [{"label": "○", "kind": "check", "text": "届出期間内の届出か。",
     "quote": "届出期間内の届出か", "row_ids": ["p3-r9"], "remark_row_ids": ["p3-r9"],
     "conditions": [], "documents": [], "record_items": [], "roles": [], "escalates_to": [],
     "cites": [{"law": "戸籍法", "article": 49, "branch": null, "paragraph": null, "item": null,
                "normalization_note": null}],
     "notes": [], "alignment": "ok", "speculative": false, "reason": null,
     "prerequisite_for": null, "children": []}]}],
 "notes": [{"text": "来庁者：現に届出の任に当たっている者", "row_ids": ["p2-r40"]}],
 "new_vocab": [{"kind": "document", "name_ja": "…", "slug": "english-slug"}]}
```
