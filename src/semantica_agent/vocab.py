"""仕様 §4.2〜§4.4 の名前の表と、slug の対応表。

スキーマ生成ではこの表の名前を必須概念として LLM に渡す。
slug の表に無い名前を LLM が出したら生成を止め、人がここに足す（仕様 §7.1）。
"""

REQUIRED_CLASSES: dict[str, str] = {
    "Business": "業務",
    "ProcedureStep": "工程",
    "StepItem": "手順項目",
    "Task": "作業",
    "ReviewCheck": "審査項目",
    "Condition": "適用条件",
    "DocumentType": "書類の種類",
    "RecordItem": "記載事項",
    "PartyRole": "関係者の種類",
    "Organization": "機関",
    "Law": "法令",
    "LegalProvision": "条文",
    "ProvisionVersion": "条文の版",
    "LegalAmendment": "改正",
    "SourceReference": "出典",
    "JudgmentRule": "判定ルール",
    "DerivedValue": "派生値の定義",
    "Filing": "届出の事案",
    "BirthFiling": "出生届の事案",
}

_BUSINESS_PROPERTIES: dict[str, str] = {
    "hasStep": "工程",
    "stepNumber": "区分の番号",
    "nextStep": "次の工程",
    "hasItem": "項目",
    "hasSubItem": "下位の項目",
    "itemLabel": "手順書上の番号",
    "itemOrder": "出現順",
    "prerequisiteFor": "移行先の工程",
    "appliesWhen": "適用条件",
    "requiresDocument": "必要書類",
    "requiresRecordItem": "確認する記載事項",
    "involvesRole": "関係者",
    "escalatesTo": "照会・通知・送付の先",
    "citesProvision": "根拠条文",
    "partOfLaw": "法令",
    "article": "条",
    "articleBranch": "条の枝番",
    "paragraph": "項",
    "item": "号",
    "hasVersion": "版",
    "validFrom": "施行日",
    "validUntil": "効力を失った日",
    "versionStatus": "版の種類",
    "summary": "内容の要約",
    "amends": "改正する条文",
    "producesVersion": "改正後の版",
    "effectiveDate": "施行日",
    "currentTreatment": "現行法での扱い",
    "currentTreatmentNote": "現行法での扱いの注記",
    "implementsCheck": "判定する審査項目",
    "underVersion": "基づく法の版",
    "shape": "ルールの実体",
    "outcome": "判定の種類",
    "hasSource": "出典",
    "reviewStatus": "レビューの状態",
    "sourceKind": "出典の種類",
}

_CASE_PROPERTIES: dict[str, str] = {
    "filingDate": "届出日",
    "filingMunicipality": "届出を受けた市区町村",
    "childBirthDate": "子の出生日",
    "childBirthTime": "子の出生時刻",
    "birthPlaceMunicipality": "出生地",
    "honsekiMunicipality": "入る戸籍の本籍地",
    "notifierMunicipality": "届出人の所在地",
    "notifierRole": "届出人の資格",
    "attachedDocument": "添付された書類",
    "recordedItem": "記載のある事項",
    "statedRelationship": "届書の続き柄",
    "statedFather": "届書上の父",
    "certBirthDate": "出生証明書の出生日",
    "certBirthTime": "出生証明書の出生時刻",
    "certBirthPlace": "出生証明書の出生地",
    "motherBirthDate": "母の生年月日",
    "parentsMarriageDate": "父母の婚姻日",
    "motherPrevMarriageEndDate": "母の前婚の解消日",
    "motherRemarriedBeforeBirth": "出生までの母の再婚",
    "familyRegisterExists": "入る戸籍の存在",
    "addressExists": "住所の存在",
    # 派生値（コードが計算して足す。仕様 §4.6）
    "daysFromMarriageToBirth": "婚姻から出生までの日数",
    "daysFromPrevMarriageEndToBirth": "前婚の解消から出生までの日数",
    "filingDeadline": "届出期間の末日",
    "daysLate": "届出期間を過ぎた日数",
    "motherAgeAtBirth": "出生時の母の年齢",
    "childAgeAtFiling": "届出時の子の年齢",
}

# 仕様の表には無いが、§4.6・§6.3・§7.1 が持つと書いている値（台帳の Pre-flight の Ruling）。
AUX_PROPERTIES: dict[str, str] = {
    "partOf": "上位の条文",
    "pdfPage": "PDF の頁",
    "printedPage": "印刷頁",
    "rowId": "行の ID",
    "quote": "原文の引用",
    "businessName": "業務名",
    "division": "区分",
    "url": "URL",
    "fetchedDate": "取得日",
    "reviewer": "確認者",
    "reviewedDate": "確認日",
    "model": "モデル",
    "promptSha256": "プロンプトのハッシュ",
    "sha256": "ファイルのハッシュ",
    "periodDays": "期間の日数",
    "countFirstDay": "初日を算入する",
    "extendOnHoliday": "末日が休日なら延ばす",
    "derivedFromProperty": "計算に使う事案のプロパティ",
    "normalizationNote": "正規化の注記",
    "alignment": "対応の確かさ",
    "revisionId": "e-Gov の版の ID",
    "lawNumber": "法律番号",
}

REQUIRED_PROPERTIES: dict[str, str] = {
    **_BUSINESS_PROPERTIES,
    **_CASE_PROPERTIES,
    **AUX_PROPERTIES,
}

ENUM_INDIVIDUALS: dict[str, tuple[str, ...]] = {
    "versionStatus": ("Manual", "Current", "Repealed"),
    "currentTreatment": ("Valid", "Changed", "Obsolete"),
    "outcome": ("Reject", "NeedsCorrection", "NeedsInquiry", "AdditionalProcedure", "Info"),
    "reviewStatus": ("LlmDraft", "HumanReviewed", "HumanEdited"),
    "sourceKind": ("ManualSource", "CurrentLawSource", "Speculation"),
}

BUSINESS_SLUGS: dict[str, str] = {
    "戸籍届出（出生）": "birth",
    "戸籍届出（婚姻）": "marriage",
    "戸籍届出（離婚）": "divorce",
    "戸籍届出（死亡）": "death",
    "戸籍謄本等の交付": "certificate",
}

LAW_SLUGS: dict[str, str] = {
    "戸籍法": "koseki-ho",
    "戸籍法施行規則": "koseki-ho-kisoku",
    "民法": "minpo",
    "住民基本台帳法": "juki-ho",
    "人口動態調査令": "jinko-dotai-rei",
    "母子保健法施行規則": "boshi-hoken-kisoku",
    "法の適用に関する通則法": "tsusoku-ho",
    "墓地、埋葬等に関する法律": "bochi-maiso-ho",
    "地方公共団体の手数料の標準に関する政令": "tesuryo-seirei",
    "学校教育法": "gakko-kyoiku-ho",
}

LAW_ALIASES: dict[str, str] = {"住基法": "住民基本台帳法"}

DOCUMENT_SLUGS: dict[str, str] = {
    "出生届": "birth-notification",
    "婚姻届": "marriage-notification",
    "離婚届": "divorce-notification",
    "死亡届": "death-notification",
    "交付請求書": "certificate-request",
    "出生証明書": "birth-certificate",
    "死亡診断書": "death-certificate",
    "本人確認書類": "identity-document",
    "委任状": "power-of-attorney",
    "遅延理由書": "delay-reason",
    "父母の同意書": "parental-consent",
    "要件具備証明書": "capacity-certificate",
    "母子健康手帳": "maternal-handbook",
    "戸籍謄本等": "family-register-copy",
    "受理証明書": "acceptance-certificate",
    "後見登記等の登記事項証明書": "guardianship-registration-certificate",
    "裁判所の謄本": "court-copy",
    "統一請求書": "unified-request-form",
    "代理権確認書類": "authority-confirmation-document",
}

CONDITION_SLUGS: dict[str, str] = {
    "非本籍地に届出された場合": "non-honseki-filing",
    "代理人による請求の場合": "by-agent",
    "協議離婚の場合": "divorce-by-agreement",
    "裁判離婚の場合": "judicial-divorce",
    "未成年者の場合": "minor",
    "出生証明書が添付されていない場合": "no-birth-certificate",
    "届出期間経過後に届出があった場合": "late-filing",
    "学齢に達した子の出生届の場合": "school-age-child-filing",
    "出生時に母が50歳以上の場合": "mother-aged-50-or-over-at-birth",
    "届出人から請求があった場合": "requested-by-notifier",
    "当事者が外国人の場合": "foreign-party",
    "届出人本人の来庁が確認できなかった場合": "notifier-not-present",
    "死亡診断書が添付されていない場合": "death-certificate-not-attached",
    "有配偶者が死亡した場合": "deceased-had-spouse",
    "出生後30日以内の死亡": "death-within-30-days-of-birth",
    "公的機関からの請求の場合": "public-agency-request",
    "第三者からの請求の場合": "third-party-request",
    "特定事務受任者からの請求の場合": "designated-agent-request",
}

ROLE_SLUGS: dict[str, str] = {
    "届出人": "notifier",
    "届出義務者": "obligated-notifier",
    "届出事件本人": "principal",
    "来庁者": "visitor",
    "使者": "messenger",
    "代理人": "agent",
    "法定代理人": "legal-representative",
    "証人": "witness",
    "第三者": "third-party",
    "公的機関": "public-body",
    "特定事務受任者": "certified-professional",
    "父": "father",
    "母": "mother",
    "同居者": "cohabitant",
    "医師": "physician",
    "助産師": "midwife",
    "請求者": "requester",
}

ORGANIZATION_SLUGS: dict[str, str] = {
    "法務局": "legal-affairs-bureau",
    "管轄簡易裁判所": "summary-court",
    "本籍地市区町村": "honseki-municipality",
    "妻の従前本籍地市区町村": "wife-former-honseki-municipality",
}

RECORD_ITEM_SLUGS: dict[str, str] = {
    "生まれたとき": "birth-datetime",
    "生まれたところ": "birth-place",
    "出生時刻": "birth-time",
    "生存配偶者の年齢": "surviving-spouse-age",
    "配偶者の有無": "spouse-status",
    "母の生年月日": "mother-birth-date",
}

# 項目の JSON のフィールド → (語彙の種類, 日本語名 → slug の表, クラス, プロパティ)
ITEM_VOCAB_FIELDS: dict[str, tuple[str, dict[str, str], str, str]] = {
    "conditions": ("condition", CONDITION_SLUGS, "Condition", "appliesWhen"),
    "documents": ("document", DOCUMENT_SLUGS, "DocumentType", "requiresDocument"),
    "record_items": ("record-item", RECORD_ITEM_SLUGS, "RecordItem", "requiresRecordItem"),
    "roles": ("role", ROLE_SLUGS, "PartyRole", "involvesRole"),
    "escalates_to": ("organization", ORGANIZATION_SLUGS, "Organization", "escalatesTo"),
}
