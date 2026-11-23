# #477 正式 Fundamental 報告驗收

Header修正已整合於`75c75c29745a6f802eb2000ac31bb0a52931107e`，layout與獨立實頁重驗通過。含新截圖的交付候選將再建置並執行整組真實服務驗收；目前保持WIP、PR draft，尚未合併或結案。

## 使用者核准的範圍調整

2026-11-23，使用者明確同意修正全站 Header：「可以，你認為有需要就全站fix」。#480 因而納入本次交付，修正 owning shell 的響應式約束。

對實際 VoiceOver 人工驗收，使用者回覆：「Ok，a11y不是我們的重心。」本次保留 actual screen-reader output 未驗證的限制，依最新優先序不作結案與合併門檻。沒有把未驗證的朗讀標為 pass；既有鍵盤、touch、focus、Escape、labels、200% zoom 與非純色提示仍依正式頁面結果記錄。

## 已交付行為

報告採用連續章節，首屏區分 deterministic base、Monte Carlo quantiles、關鍵假設與資料限制。Forecast、可比 history、facts、assumptions、service scenarios 與 sources 均保留服務來源與查證入口。原值與顯示值分開保存，複製使用 canonical Decimal。重算只允許現行 terminal-growth contract，draft、pending、previous、completed 與拒絕結果分開處理；歷史報告保持唯讀。

`#478` 的 parser／日期／unit semantic 修正已整合：非法 Decimal、無效曆日、shares／ratio／unsupported unit 與 context currency 不一致的 facts 在 owning boundary 被拒絕或保留 raw，不再被前端誤標 USD 或 comparable。`#479` 的 Activity 入口與 run/SSE lifecycle 修正已整合：待輸入會指向既有 typed interaction；validated run snapshot 後立即回傳 started，背景串流恢復錯誤只影響目前 operation。

## F01–F20 結果

| 案例 | 結果 | 證據 |
| --- | --- | --- |
| F01 | 通過 retained | 完整 envelope → parser → VM：base USD 229.88、P05 USD 144.67、P50 USD 173.10、P95 USD 198.00；base 可在 P95 外。 |
| F02–F04 | 通過 | 4.92%、WACC 10.28%、Beta 1.28、reinvestment 40.00%；revenue raw `331839000000` 顯示 USD 331.84B；formatter 邊界與 canonical raw 通過。 |
| F05–F09 | 通過 | alias、缺失 quantile、forecast nodes、history comparability、scenario identity 與 incomplete capital claims 由 retained／unit tests 核對。 |
| F10–F11 | 通過 live／native | 實頁查證主值、fact、assumption、node、quantile、scenario scope；原值經系統剪貼簿貼回原生 TextEdit 逐字相等，UI 提供拒絕時可選原文。 |
| F12–F13 | 通過 live | 2.5% draft 不改舊值，唯一提交 raw `0.025`；Activity 完成 MSFT/NASDAQ 後新報告 base `168.923169629739...`，applied manual 與 original automatic provenance 分開。 |
| F14 | 通過 live | 5% 產生 completed、failure=null 的 degraded artifact，`MANUAL_OVERRIDE_INVALID`；previous result 與 draft 保留，沒有成功估值。 |
| F15 | 通過 unit／hook／live | 同 run typed resume 不再被誤判 superseded；stale operation、source identity、recovery error 有 current/abort guard。 |
| F16 | 通過 live 與元件測試 | Live Research 回傳 unavailable，無 accepted claims、不改 draft；error、無可套用 claim 與 accepted claim Apply 路徑由元件測試核對。 |
| F17 | 通過 live | history URL 唯讀、無 mutation；原 artifact、assumptions、raw values 與 inspector 保留。 |
| F18 | 通過修正後layout | #480 owning shell修正後，light/dark×320/390/768/1440 document不溢出，窄report pane與表格局部scroll可讀；獨立reviewer同樣重驗。 |
| F19 | 通過 | light/dark、reduced motion、四寬、窄pane、contrast與原生Chrome真正200%zoom/reflow均經核對，75c75c29已補拍公司及估值數字。 |
| F20 | 已驗互動；朗讀未驗證 | labels、Tab、Sheet/Dialog正反向focus cycle、Escape、focus return、touch與dynamic status通過。Actual VoiceOver output不可觀測，依使用者最新優先序列限制，不標朗讀pass，且不作本次merge／closure門檻。 |

完整命令、exit code、同 source 證明與最終重跑結果見 [交付檢查](issue-477-progress-checks.md)。

## Runtime 與命令

Canonical tuple 為 [issue-477-runtime.json](issue-477-runtime.json)。工作樹、branch、Compose ordered files、env-file SHA-256、ports、SEC identity capability、browser identity 與 runtime-only overlays 均記錄於其中；secrets 未寫入。

隔離 projects：`value-investment-agent-denniswong-477-app`（backend `22680`、frontend `22681`、PostgreSQL `22682`、Redis `22683`、provider `22684`、search `22685`）及 `value-investment-agent-denniswong-477-fundamental`（service `22690`、PostgreSQL `22691`）。Frontend image 為 `sha256:98de139b6effa715776d6312b3fe153be70a4f839c2ef14881c56cc0ad1e11ea`，健康且由 541c8a9c 建置；backend／Fundamental source equality 分別為 818／183 files，無 mismatch。

已通過：

- `npm run lint`、`npm run typecheck`、`npm run test -- --run`（59 files、517 tests）、`npm run check:contrast`；
- retained Playwright 5 cases；
- canonical preflight（exit 0，`exact_commit=1`、`sec_identity_required=1`）；
- `verify-runtime-source.py`（exit 0）；
- 獨立 reviewer 的 hook／workspace 3 files、68 tests、lint、typecheck（exit 0；未撰寫產品變更）。

真實 Playwright 使用正常登入與隔離服務，無 mock：

```text
5 passed, 1 failed (4.2m)
passed: 2.5% revision, 5% refusal, Research termination, immutable history, touch evidence
failed: light/dark reflow test at 320px because document scrollWidth=327 (#480)
```

主要 live identities 與 evidence files 保存在 repo 外 diagnostics：
`/Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/live-541c8a9c/`。重算 run 的新 base、拒絕 artifact、history identity、screenshots 與 layout JSON 均由測試明確產生；不把舊 retained 數字套到新 live artifact。

## 獨立審閱與限制

[完整獨立review](issue-477-progress-review.md)已核對金融語義、來源、狀態、閱讀層級與Header實頁，接受的#478／#479／#480問題均已有owning-layer修正。Overall verdict等待含圖交付候選的整組6案結果。

實際螢幕閱讀器朗讀未驗證，依上述使用者優先序保留限制。額外發現的組織設定頁內容grid／member table溢出另列[#482](https://github.com/sosodennis/value-investment-agent/issues/482)：Header本身幾何與選單通過，不將settings整頁稱為pass，也不改Fundamental canonical assertions。

## 正式畫面與來源記錄

[實頁截圖與 artifact identities](issue-477-progress-evidence.md) 保存成功重算、拒絕、history、明暗、窄屏、touch、focus 與 native 200% 的正式畫面。截圖 capture commit 為 c46d9fba，後續交付 metadata 與圖片不改產品 source。

## 保留與清理

未合併前保留 #477 Compose projects、named volumes、diagnostics、SEC assets、keys 與 worktrees。清理只允許在 merge／結案後針對本 issue 的 project、worktree 與 branch，禁止 global prune、刪除 #462 資料或繞過 managed-worktree 保護。
