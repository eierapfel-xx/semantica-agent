# 役割

あなたは、戸籍の窓口業務のオントロジー自体の整合性を検査する SHACL シェイプを書く。

# スキーマ

$schema

# 書くシェイプ（仕様 §4.5 の 1）

1. 型（rdf:type）を持つすべてのノード（ただし sh:NodeShape・sh:PropertyShape・prov:Activity・prov:Entity・owl の定義を除く）に、`dcterms:identifier` がちょうど 1 つあり、`kos:reviewStatus` が 1 つある。
2. `kos:Business`・`kos:ProcedureStep`・`kos:StepItem` の下位・`kos:Law`・`kos:LegalProvision`・`kos:LegalAmendment`・`kos:ProvisionVersion`（ただし `kos:versionStatus kos:Manual` で出典を持たないものを除いてよい）・`kos:DerivedValue` は、`kos:hasSource` か `kos:sourceKind` を 1 つ以上持つ。
3. `kos:ReviewCheck` は、ちょうど 1 つの親（`kos:hasItem` か `kos:hasSubItem` の目的語になっている）を持つ。
4. `kos:currentTreatment` が `kos:Changed` か `kos:Obsolete` の審査項目は、`kos:citesProvision` の先の条文（またはその `kos:partOf` の条）に、`kos:versionStatus` が `kos:Current` か `kos:Repealed` の版がある。SPARQL 制約で書く。
5. `kos:sourceKind kos:Speculation` を持つノードは `rdfs:comment` を持つ。
6. `kos:SourceReference` は `kos:sourceKind` をちょうど 1 つ持ち、`kos:ManualSource` なら `kos:pdfPage` と `kos:rowId` を、`kos:CurrentLawSource` なら `kos:url` と `kos:fetchedDate` を持つ。

SPARQL 制約を使うときは、次の接頭辞の宣言ノードをそのまま含め、`sh:prefixes kd:prefixes` で参照する。

```turtle
kd:prefixes a owl:Ontology ;
  sh:declare [ sh:prefix "kos" ; sh:namespace "https://semantica-agent.example/koseki/schema#"^^xsd:anyURI ] ,
             [ sh:prefix "kd" ; sh:namespace "https://semantica-agent.example/koseki/id/"^^xsd:anyURI ] ,
             [ sh:prefix "rdfs" ; sh:namespace "http://www.w3.org/2000/01/rdf-schema#"^^xsd:anyURI ] .
```

シェイプの IRI は `<https://semantica-agent.example/koseki/id/shape/integrity/英語の slug>` にする（Turtle の接頭辞付きの名前には `/` を書けないので、`kd:` の下で `/` を含む IRI は必ず `<…>` の完全な形で書く）。各シェイプに `sh:message` を日本語で付ける。

# 出力

Turtle だけを ```turtle のコードブロックで出力する。接頭辞は kos・kd・sh・rdf・rdfs・owl・xsd・dcterms・prov を宣言する。
