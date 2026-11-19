# 役割

あなたは、出生届の審査の判定ルールを、SHACL シェイプとして下書きする。窓口職員が受け取った出生届の内容（事案データ）にシェイプを当て、受理できるか・何が足りないかを、根拠のルール・審査項目・条文の版まで辿れる形で返すのが目的である。

# スキーマ（事案側のプロパティを含む）

$schema

# 出生届の手順項目（ID・種類・内容・根拠条文）

$checks

# 条文の版

$versions

# 作るルール

各行が 1 つの `kos:JudgmentRule`。IRI は表のとおりにする。

$rules

# 判定の種類と severity（必ずこの対応にする）

- `kos:Reject` → `sh:Violation`（受理できない）
- `kos:NeedsCorrection` → `sh:Violation`（補正・追完が要る）
- `kos:NeedsInquiry` → `sh:Warning`（法務局への受理照会が要る）
- `kos:AdditionalProcedure` → `sh:Warning`（受理できるが追加の手続が要る）
- `kos:Info` → `sh:Info`（参考）

# 書き方

1. 各ルールのノードに、`a kos:JudgmentRule`、`dcterms:identifier`（表の ID の形 `RULE-BIRTH-<SLUG を大文字>`）、`rdfs:label`（日本語）、`kos:implementsCheck`（上の手順項目の IRI）、`kos:outcome`、`kos:shape`（シェイプの IRI）、`kos:reviewStatus kos:LlmDraft`、版が決まっているルールには `kos:underVersion`（上の条文の版の IRI）を付ける。
2. シェイプは `<https://semantica-agent.example/koseki/id/shape/birth/slug>` に置き（`kd:` の下で `/` を含む IRI は、Turtle では必ず `<…>` の完全な形で書く）、`sh:targetClass kos:BirthFiling`、`sh:severity`、日本語の `sh:message` を付ける。1 つのシェイプは 1 つのルールにだけ対応させる。
3. 日付の計算はしない。事案には次の派生値が整数・日付で入っている：`kos:daysFromMarriageToBirth`、`kos:daysFromPrevMarriageEndToBirth`、`kos:filingDeadline`、`kos:daysLate`、`kos:motherAgeAtBirth`、`kos:childAgeAtFiling`。
4. 単純な欠落や値の比較は SHACL Core（`sh:property`、`sh:minCount`、`sh:hasValue`、`sh:in` など）で書く。条件の組み合わせが要るものは SPARQL 制約（`sh:sparql`、`$$this` が事案）で書き、`sh:prefixes kd:prefixes` を参照する。接頭辞の宣言ノード `kd:prefixes` を次のとおり含める。

```turtle
kd:prefixes a owl:Ontology ;
  sh:declare [ sh:prefix "kos" ; sh:namespace "https://semantica-agent.example/koseki/schema#"^^xsd:anyURI ] ,
             [ sh:prefix "kd" ; sh:namespace "https://semantica-agent.example/koseki/id/"^^xsd:anyURI ] ,
             [ sh:prefix "xsd" ; sh:namespace "http://www.w3.org/2001/XMLSchema#"^^xsd:anyURI ] .
```

5. 法の版の選び方：版が決まっているルールは、事案の出生日（`kos:childBirthDate`）が、`kos:underVersion` の版の `kos:validFrom` 以上かつ `kos:validUntil` 未満（無ければ制限なし）のときだけ違反を出す。この条件は SPARQL 制約の WHERE で、オントロジーの版のノードを引いて書く（判定時はオントロジーも同じデータグラフに入っている）。手順書時点の版で `kos:validUntil` が無いものは、常に適用される。
6. 嫡出の判定：B4a は手順書時点の版（`kos:validUntil` が 2024-04-01）に基づくので、5 の条件により 2024-03-31 以前に生まれた子にだけ適用される。B4b は現行の版に基づき 2024-04-01 以後に生まれた子に適用される。B4c は 2024-04-01 以後に生まれた子について、手順書の基準（婚姻後 200 日以上・前婚解消後 300 日以内）による結論と現行の基準による結論が違うときに `kos:Info` を出す。
7. 当てはまらない事案（必要な値が無い等）では違反を出さない。値の欠落そのものを見るのは B11 だけにする。

# 出力

Turtle だけを ```turtle のコードブロックで出力する。接頭辞は kos・kd・sh・rdf・rdfs・owl・xsd・dcterms を宣言する。
