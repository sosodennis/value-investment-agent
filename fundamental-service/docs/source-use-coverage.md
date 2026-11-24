# 公開來源、用途與固定 coverage

這份 reference 說明 #493 的來源基礎。完整逐列資料、原始 URL、profile、更新成本、
時間範圍、六種用途及條款引用在
[`issue493-matrix.json`](../tests/fixtures/source-coverage/issue493-matrix.json)。
它是研究資料，不會被服務載入，也不能安裝或擴張權限。
操作方式見[重跑來源核對](reproduce-source-coverage.md)。

## 讀取結果

必須分開回答四個問題：原文是否取得、parser 是否讀出事實、語義是否可比、
用途是否成立。取得成功不表示後三者成功。完整三表、mapping、financial policy、
trusted release 及計算資格仍由各正式 owner 決定。

矩陣分開記錄 `acquisition`、`storage`、`analysis`、`derived_display`、
`raw_display`、`redistribution`。`evidence_supported` 表示在列出的範圍內有證據；
`refused` 表示被記載的來源限制或現行系統政策拒絕；`unconfirmed` 表示證據不足。
每格的理由會指出是哪個邊界，不能把系統拒絕解讀為法律禁止，或把研究判斷寫成供應商授權。

Runtime 的 `SourceUsePolicyV1` 只有 `valuation_preparation`、
`derived_valuation_display`、`raw_data_redistribution` 三種用途。
重跑工具直接從現行 policy 投影 provider、metric、profile、用途與 terms pins，
另核對矩陣中的 registrations 及保留證據。投影不取代正式 admission。
部署仍須成對提供 policy file 與 digest；request 和矩陣都不能安裝 policy。

## 來源範圍與下游影響

以下列 ID 對應機器矩陣。查閱資料定義及用途時，應一併讀取該列理由與原文引用。
核對日期為 2026-11-24，沒有實測的 workbook、vintage 或 quote 不宣稱可用。

| 列 ID | 資料與正式路徑 | 本票能支持的判斷 |
| --- | --- | --- |
| `sec-statements` | SEC 原始年度／季度三表；SEC capture → retained originals → ingestion/parser | 固定三案的原文及解析結果可查。#494 仍需完整會計 mapping；本票未驗季度三表。 |
| `sec-history` | 原版／修訂與可得日；SEC catalog/discovery | 不以最新 CompanyFacts 補歷史。Apple 非十二月及 52/53 週保留各自期間；不自動年化。 |
| `sec-shares` | DEI 股數、基本／稀釋加權平均股數及股別 context | 股數口徑與時點各自保留，不等於完整歷史 security identity。 |
| `sec-sbc` | SBC 原始 facts 與附註 | 支持定位，未核准 expense、cash-flow addback 或 dilution 間的換算。 |
| `sec-claims` | 債務、租賃與其他資本 claims 披露 | Fact 存在不證明 #499 inventory 完整；缺項不能補零。 |
| `sec-segments-kpi` | 分部與原始自訂概念 | Custom QName 與 dimensions 可查，仍須 #502 的逐公司／期間語義核對。 |
| `treasury-10y` | Treasury 年度 XML；public acquisition → macro provider → admission | 本票的真實成功路徑。10 年 par yield 不是 SOFR 或 issuer borrowing cost；capture 不證明歷史 vintage。 |
| `bea-current` | BEA 當前 NIPA GDP workbook；public acquisition → macro admission | 本次只核對條款；未實測數值。現行整頁 raw hash 與 article scope digest 分開保留。 |
| `bea-vintage` | BEA 歷史 workbook 與 release publication 配對 | 未驗任意歷史 vintage；不能以目前可下載回推舊估值日可得。 |
| `sofr` | New York Fed API；macro admission | 新抓 terms 整頁 digest 不符 pin，保留未確認及正式拒絕，見 [#506](https://github.com/sosodennis/value-investment-agent/issues/506)。 |
| `alfred-vintage` | ALFRED CSV reproducer | Parser 存在但預設無 grant；DGS10 與 par yield 口徑亦不同。未取得本次資料或條款。 |
| `industry-capital-proxy` | Damodaran industry beta、debt cost 及 weights；reference admission | Terms digest 符合，未驗本次 workbook。Industry aggregate 不是 issuer 估計。 |
| `industry-unlevered-proxy` | Damodaran unlevered beta；reference admission | 不可直接作 equity beta，仍保留金融口徑拒絕。 |
| `country-erp-proxy` | Damodaran country ERP／tax；reference admission | 須保留 jurisdiction、crosswalk 及 tax year；不是 CDS spread 或 issuer 全部地理風險。 |
| `company-ir-kpi` | 逐公司 IR 候選；未建立通用 capture/admission | 免費可見不等於准許留存及展示。條件未成立時，只限制依賴該 KPI 的輸出。 |
| `yahoo-daily-price` | 既有最新完整日線 provider 與 quote admission | 本票未取新 quote。個人非商業本機設定不是供應商自動擷取授權，也不能升格第三方或商業用途。 |
| `nasdaq-historical-candidate` | 既有歷史 quote format reproducer | 既有研究未建立 production capture／permission，不能供 #503 接入。 |

#494 年度三表與 #496 財務指標可先使用已有 SEC 原文及 coverage 證據，
逐案補齊 mapping、完整性與正式 ingestion。它們不必等待所有市場資料研究完成。
#503 須先解決適用報價權利；#504 市場倍數、#505 反向 DCF 等依賴 quote 的輸出
不能因本矩陣存在而宣稱完成。Twelve Data 排除本票啟用範圍，既有 adapter、測試與歷史證據保留。

## 條款與引用邊界

矩陣的 `evidence` 保存 URL、核對日期、原文引句、穩定內容邊界、SHA-256 及
artifact reference。Public acquisition 原文與 SEC 官網研究頁放在可攜證據包，
不依賴作者的工作樹或暫存目錄。證據包位置與 hash 見重跑文件。

- SEC 明示任何人可免費 access/download，並要求可識別 User-Agent 及節流。
  本票限公開事實性觀察及自身計算，附公司、accession、期間與來源。
  Issuer filings 不是 §105 政府作品；原文展示與再分發未成立。
- Treasury 與 BEA 的範圍限各機關自行產生的 aggregate，不擴張到第三方著作。
  引用機關、表名／期間及 release，標示自行計算並避免暗示機關背書。
  現行 runtime 仍拒絕 raw-data redistribution。
- Damodaran 的依據是 publisher 分享 processed aggregates 的文字，
  不涵蓋底層商業 company dataset；引用 Aswath Damodaran、NYU Stern 及版本。
- BEA 核對 `article[about="/help/guidelines-for-citing-bea"]` 的正式
  `HtmlTermsScopeV1` digest。其他列仍採既有 whole-document pin，不能自行刪除頁面區塊。
- New York Fed 的新舊整頁 hash 不同不等於已證明條文變更；必須由 owning policy
  重新核對後版本化，不能在 runner 自動更新 pin。
- Yahoo 的限制見[個人本機政策證據](../../docs/acceptance/issue-361-personal-local-source-policy.md)。
  本票未建立外部自動擷取授權，不把 operator decision 寫成 Yahoo 授權。

這是可核對的工程與來源研究，不是法律認證或投資績效證明。

## 固定樣本與拒絕

[`issue493-cohort.json`](../tests/fixtures/source-coverage/issue493-cohort.json)
在任何本票 coverage 驗收前提交於
[`a6220db0`](https://github.com/sosodennis/value-investment-agent/commit/a6220db071df8fc39e70bbbee8cc70f2da8b6533)。
選樣與預期保持不變，`actual_coverage=unknown`、`supported_history_threshold=null`。
實際結果另存，不回填預期。

三案是 Apple FY2024 10-K、Tesla FY2023 10-K、Tesla FY2024 10-K/A。
修訂版 EXPLANATORY NOTE 只補 Part III 等項目，不代表完整三表重述；原 capture
`amendment_scope=unknown` 不改。缺少 fact 的結果必須分辨原文缺失與 parser 未讀出，
不得挪用另一年度、補零或推論 issuer 從未披露。

初跑的 Tesla 兩案使用 2023 DTS，而固定 cache 缺少對應依賴；
原文有標準 QName，parser 卻只讀出 extension facts 或沒有 facts。
因此保留 partial／unsupported，不能以空 diagnostics 當成功。
資源與解析責任的後續工作見 [#507](https://github.com/sosodennis/value-investment-agent/issues/507)。

SEC runner 使用正式 `parse_filing_offline`，保留 full report、原文 hash、contexts、
units、dimensions、原始 QName 及 parser/runtime/taxonomy identity。
這是 `parse-only`。它會實際呼叫 `require_sec_validation_evidence`，保留
`SEC_VALIDATION_REQUIRED`，不發布 snapshot、mapping、release 或 valuation。
單獨 HTML 與 ZIP 內 HTML 各自依既有 manifest 驗 hash，不宣稱 archive integrity admission。

正式 production 路徑仍是 accession-bound SEC capture／retention → 嚴格 EFM/DQC
ingestion → identity／mapping／financial policy → trusted release → calculation。
SEC 不套用 macro/reference admission。Public 路徑則由
`PublicSourceAcquisition` 與 `PublicSourceAdmission` 擁有取得、留存與用途判斷；
quote 使用其專屬 provider 及 `admit_quote_source`。

## 缺口與維護

所有逐來源失敗只限制依賴它的輸出。原文有值而 parser 漏讀，屬內部解析缺陷；
用途未確認、暫時擷取失敗及口徑不可比分別保留，不合併成「沒有資料」。
可行動根因連到 GitHub issue，不以本文件另建 missing-data 任務系統。
新增或變更來源仍依[既有 owner 擴充流程](market-input-providers.md#extend-a-source)，
版本化 registration、policy、retained terms 與對應測試。

#376 fixed-100、#350 全 Agent/provider 部署與 #339 readiness/interrupt 維持 deferred。
本票不設定五年度／八季度充分性門檻，也不實作完整三表、季度／TTM、新指標、
claims inventory、報價接入或估值公式。
