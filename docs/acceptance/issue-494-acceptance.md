# #494 年度三表驗收

正式服務、authenticated API 與 workspace 已通過四案、每案五年度與25個主要行項的驗收。這些主要行項不是完整財報附註，也不是任意企業的通用覆蓋宣告。五年是 coverage target，`supported_history_threshold=null`，`valuation_eligibility=not_evaluated`。

資料 materialization／release commit 為 `31b2483d064e5aee8b3ea6bc79e391eeec6ae7a5`。最終 serving／頁面實作 commit 為 `9b36d41af28241dabe374cb61efa5251d276291b`。後者共用單次原件證明及調整 proxy，沒有更改 mapping v45、statement profile、財務公式或原始輸出。兩個 commit、原 source revision 與各自的 hashes 分別保存。

## 四案結果

| 案例 | Cutoff；年度 | 有值／缺失 | 勾稽 | 正式 API／頁面 |
| --- | --- | --- | --- | --- |
| Apple historical | 2024-11-02；FY2020至FY2024 | 120／5 FX missing | 15 passed；5 full-FX unresolved | PASS |
| Apple current | 2026-11-24；FY2022至FY2026 | 120／5 FX missing | 15 passed；5 full-FX unresolved | PASS |
| Microsoft historical | 2024-11-02；FY2020至FY2024 | 125／0 | 20 passed | PASS |
| Microsoft current | 2026-11-24；FY2022至FY2026 | 125／0 | 20 passed | PASS |

獨立會計 reviewer 直接核對490個原值、十個明確FX缺失、80組勾稽，以及60個額外Decimal residual。Apple實際364／371天期間保留，不自動年化。每個Apple案例選96個later comparative／24個original，Microsoft各100／25；14份原始submission發表時間另獨立核對。較晚比較數不提前出現在歷史cutoff。

Apple未單列的FX沒有補零，quality保留provisional；Microsoft20組勾稽全部通過。FY2020／2021的FX保留舊原始tag，僅在已核准的來源／concept／locator下歸屬同表cash balance定義。真正不同口徑仍拒絕，沒有balancing plug。

## A01至A12

| Gate | 結果與證據 |
| --- | --- |
| A01 | 四案正式operator、strict validation、mapping、signed release、API與頁面通過。各五年、25行逐格列明coverage。 |
| A02 | Apple非十二月年結與52／53週實際期間、limited comparability保留，未年化。 |
| A03 | Duration／instant及issuer、unit、currency、consolidation、dimensions、security scope依versioned契約解析；scope與跨period拒絕由owner tests涵蓋。 |
| A04 | 原版、later comparative、cutoff與候選選樣由原件獨立核對；Part III-only／unknown amendment邊界由固定負向與selector tests涵蓋。 |
| A05 | Standard／custom concept、同精度衝突、缺mapping與observation scope依版本化policy核對，沒有label猜測。 |
| A06 | Decimal、sign／scale、cash definition、FX與reported-decimals tolerance逐案獨立重算。 |
| A07 | 未披露、source／parser failure、用途、不可比、not applicable、零與負數分開。Apple missing不冒稱解析失敗，failed originals不冒稱未披露。 |
| A08 | Profile／hash／validation／DTS／corruption與cross-scope負向通過owning boundary；正式HTTP錯cutoff回422，未知manifest回404。 |
| A09 | 四案共500格實際開啟inspector，核對490個原值與10個缺失；statement／cell／period／version、context、accession、source hash及mapping一致。 |
| A10 | 固定materialization image的四案官方重播逐byte一致；新serving完整重驗同retained release。移除diagnostics、重啟服務後兩個current案保留相同statement／artifact／reference，歷史saved URLs不取代成最新資料。 |
| A11 | 每案light／dark各320／390／768／1440px、窄pane、keyboard與真touch通過；真正browser zoom1→2→1、DPR1→2且CSSzoom1，三表查證與focus return通過。 |
| A12 | 全服務、前端、契約、架構、權限及CI通過，獨立工程、會計與正式UI審閱通過。main實際交付另在PR與issue記錄，不由本文件預告。 |

## 正式 validation 與拒絕

四案各五份original均執行`sec-efm-dqc`，validation engines為`sec-efm`與`dqc-us`，offline且network attempt為0。FY2020至FY2022採已配置的V18，其餘採V31.0.3。14份不同原件的warnings、finding codes、profile/cache與source hashes均保留，沒有把空diagnostics或parse-only升格。每案八個release gates、簽章及mapping approvals均核對通過。

真實public API負向包含未登入401、CSRF403、錯thread404、錯organization403，以及無效intent422。兩個並行strict reads在單worker下，一個成功，另一個在caller期限回`408 application/json`及`DEADLINE_EXCEEDED`。這是具名拒絕證據，不是並行吞吐或效能保證。

## Runtime 與期限

完整tuple見[issue-494-runtime.json](issue-494-runtime.json)，包含ordered Compose files、env路徑與SHA-256、project、ports、URLs、source equality、resources及browser identity。環境檔內容、cookies與private keys不公開。正式preflight設`REQUIRE_SEC_IDENTITY_RESOLUTION=1`。16個其他issue容器的ID、image與start time未變。

本票backend明確設定`FUNDAMENTAL_SERVICE_TIMEOUT_SECONDS=30`，年度route建立一次30秒absolute deadline，各hop及retry使用相同剩餘期限。原generic預設是每次10秒、最多兩次，不能誤稱每次20秒。正式完整五原件重驗約10至25秒，採完整caller預算避免過早重試。Next的`experimental.proxyTimeout=60_000`保留具名backend拒絕的回應空間。它不延長caller deadline，也不保證同步worker在30秒硬終止。診斷override已移除，最後重啟使用標準image command。

保留的31b release使用原verification authority及suite；最終reader沒有簽新candidate。四案實際parser action為v1，原delivery revision及完整closure仍重驗。V2／V3仍要求其current-build gate，沒有降低版本或略過檢查。新capture、profile或mapping形成新輸入；新candidate必須使用當前image的pins及正式operator authority。

## Checks與獨立審閱

- 最終完整Fundamental suite，`uv run --frozen --extra dev --project fundamental-service pytest fundamental-service/tests -ra`，5695 passed、14 skipped、exit0。Skips為既有資源／平台條件，不替代本票20份正式validation證據。
- Ruff0.14.10、74個changed Python檔format、46個source／script檔mypy1.19.1、service與core architecture guards、contract codegen均exit0。
- 前端lint、typecheck與完整suite546 passed；四案真實Playwright逐格matrix均exit0，mock-free且沒有啟動Agent。
- [實作CI run](https://github.com/sosodennis/value-investment-agent/actions/runs/45389478762)通過。後續驗收文件commit僅改本票acceptance metadata，必要head checks仍由PR檢查。
- 未撰寫相應diff者分別審閱SEC表示完整性、DQC資源、原件取得、service／mapping／cash basis、core／UI、兩輪讀取修正及最後真實頁面。最終UI verifier另在獨立checkout核對base、head與stable patch identity；沒有以作者自查代替。

## 可分享證據與重現

[版本化驗收release](https://github.com/sosodennis/value-investment-agent/releases/tag/issue-494-annual-statements-v1)提供ZIP、外層SHA-256及內部allowlist verifier。ZIP SHA-256為`abde2d1af3b06bd70ee78b6865661d7fa49a7e86ff53da12ca869c231add36c9`。包內包含validation／coverage／API／UI摘要、46張正向圖與獨立review，不含SEC原始文件或完整artifact bodies，不擴大raw document再分發用途。

下載到新目錄，先核外層SHA-256，解壓後執行`python3 tools/verify_bundle.py .`。重取來源依[來源fixture說明](../../fundamental-service/tests/fixtures/annual-statements/README.md)與[operations runbook](../../fundamental-service/docs/operations-runbook.md)，使用自己的正式資源、operator keys及reader account，不依賴作者電腦。新capture metadata不同時如實記為新input。

從`frontend/`以`ANNUAL_STATEMENTS_LIVE=1`、`FUNDAMENTAL_LIVE_BASE_URL`、`FUNDAMENTAL_LIVE_LOGIN_FILE`、`ANNUAL_STATEMENTS_LIVE_ISSUER_ID`與`FUNDAMENTAL_LIVE_OUTPUT_DIR`執行`npx playwright test --config e2e/fundamental-report-live.config.ts annual-statements.live.spec.ts`。分別配置歷史與目前reader binding。Saved URL使用`statement_thread`與`statement_artifact`；不使用workflow run補造報表。

真正200%工具與環境參數指令在證據包`tools/zoom/README.md`。每次使用獨立profile，最後還原zoom並關閉。主線merge、issue closure與僅本票資源的清理紀錄在[#494](https://github.com/sosodennis/value-investment-agent/issues/494)及[PR #510](https://github.com/sosodennis/value-investment-agent/pull/510)。
