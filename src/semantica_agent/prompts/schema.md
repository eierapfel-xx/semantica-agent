# 役割

あなたは、市区町村の戸籍の窓口業務（出生・婚姻・離婚・死亡の届出、戸籍謄本等の交付）の審査支援に使うオントロジーを設計する。窓口職員が届出の内容を受け取り、受理できるか・何が足りないかを、根拠（工程・審査項目・条文・手順書の原文）付きで判定できることが目的である。

# 入力

下の「手順書の行」は、手順書の PDF の表を 1 行ずつ取り出したもの。各行は `row_id | 業務 | 区分 | 業務手順 | 備考` の形をしている。

$rows

# 必ず含める概念

次のクラスとプロパティは、名前（ローカル名）を変えずに必ず含める。日本語名は参考。

## クラス

$required_classes

## プロパティ

$required_properties

## 列挙値（個体として定義する。出力の classes・properties には含めない）

$enums

# 指示

1. 上の概念それぞれに、手順書の内容に即した日本語の定義（comment_ja）と、上位クラス（parent。無ければ null）、プロパティの定義域（domain）と値域（range）を書く。
2. 値域は、クラスならクラス名、値なら `xsd:string`・`xsd:integer`・`xsd:date`・`xsd:time`・`xsd:boolean`・`xsd:anyURI`・`rdf:langString` のいずれかにする。
3. 命名：クラスは UpperCamelCase、プロパティは lowerCamelCase の英語（ASCII）にする。日本語は label_ja に、説明は comment_ja に書く。
4. 上の一覧に無い概念が手順書から必要だと判断したときだけ足してよい。足したものには `"speculative": true` と、なぜ必要かを `reason` に書く。
5. 手順書に書かれていないことを、手順書が根拠であるかのように書かない。

# 出力

JSON だけを出力する。形は次のとおり。

```json
{
  "classes": [
    {"name": "ReviewCheck", "label_ja": "審査項目", "comment_ja": "…", "parent": "StepItem",
     "speculative": false, "reason": null}
  ],
  "properties": [
    {"name": "citesProvision", "type": "object", "domain": ["StepItem", "ProcedureStep"],
     "range": ["LegalProvision"], "label_ja": "根拠条文", "comment_ja": "…",
     "speculative": false, "reason": null}
  ]
}
```
