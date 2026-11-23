# #477 正式 Fundamental 報告驗收

本次 implementation commit 為 `c46d9fba191c3b793749198ca444b5ef96f3396d`。目前保持 BLOCKED，未宣稱 VERIFIED、未合併 main，也未結案 #477。

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
| F16 | 通過 live | Research unavailable/error/no acceptable claim 結束，不改 draft，不顯示 Apply 保證。 |
| F17 | 通過 live | history URL 唯讀、無 mutation；原 artifact、assumptions、raw values 與 inspector 保留。 |
| F18 | 未通過，#480 | 真實 320px 頁面 document scrollWidth `327`（viewport `320`）；原因是全站 Header organization selector。報告表格仍使用局部 scroll。目標原本排除 shell，尚未獲授權修改。 |
| F19 | 部分通過 | light/dark、reduced motion、320/390/768/1440、窄 report pane、contrast、200% native Chrome zoom 與放大後 reflow 已核對；F18 shell overflow 仍使整體項目未通過。 |
| F20 | 未完整驗證 | Playwright／CUA 已核對 labels、Tab、Sheet/Dialog focus cycle、Escape、focus return、touch 與 dynamic status；VoiceOver 朗讀與字幕目前無法由工具觀測，等待使用者提供實際朗讀結果。 |

## Runtime 與命令

Canonical tuple 為 [issue-477-runtime.json](issue-477-runtime.json)。工作樹、branch、Compose ordered files、env-file SHA-256、ports、SEC identity capability、browser identity 與 runtime-only overlays 均記錄於其中；secrets 未寫入。

隔離 projects：`value-investment-agent-denniswong-477-app`（backend `22680`、frontend `22681`、PostgreSQL `22682`、Redis `22683`、provider `22684`、search `22685`）及 `value-investment-agent-denniswong-477-fundamental`（service `22690`、PostgreSQL `22691`）。Frontend image 為 `sha256:1fa6bc639843b11fd1176c3bf9bc5d141a93304ec129739f52a095f0d99aa7ec`，健康且由 c46d9fba 建置；backend／Fundamental source equality 分別為 818／183 files，無 mismatch。

已通過：

- `npm run lint`、`npm run typecheck`、`npm run test -- --run`（59 files、517 tests）、`npm run check:contrast`；
- retained Playwright 5 cases；
- canonical preflight（exit 0，`exact_commit=1`、`sec_identity_required=1`）；
- `verify-runtime-source.py`（exit 0）；
- 獨立 reviewer 的 hook／workspace 3 files、68 tests、lint、typecheck（exit 0；未撰寫產品變更）。

真實 Playwright 使用正常登入與隔離服務，無 mock：

```text
5 passed, 1 failed (3.3m)
passed: 2.5% revision, 5% refusal, Research termination, immutable history, touch evidence
failed: light/dark reflow test at 320px because document scrollWidth=327 (#480)
```

主要 live identities 與 evidence files 保存在 repo 外 diagnostics：
`/Users/denniswong/.codex/diagnostics/issue-477-fundamental-report-ui/live-c46d9fba/`。重算 run 的新 base、拒絕 artifact、history identity、screenshots 與 layout JSON 均由測試明確產生；不把舊 retained 數字套到新 live artifact。

## 獨立審閱與未完成項目

獨立 reviewer 已完成金融語義、來源 identity、formatter、series、revision reducer／workspace operation、evidence inspector、reading hierarchy 及 #479 lifecycle 的實質審閱，並在 c46d9fba 重跑 affected checks。[完整獨立 review](issue-477-progress-review.md) 已包含實頁查核，仍明確保留兩個未完成項：#480 shell scope 與 F20 實際 screen-reader output；no-comments 零 findings 不代替實質審閱。

因此 #480 保持 open，F18 不標通過；F20 在取得實際 VoiceOver 觀察前不標通過。PR 應保持 draft，不能以目前證據 merge 或關閉 #477。

## 正式畫面與來源記錄

[實頁截圖與 artifact identities](issue-477-progress-evidence.md) 保存成功重算、拒絕、history、明暗、窄屏、touch、focus 與 native 200% 的正式畫面。截圖 capture commit 為 c46d9fba，後續交付 metadata 與圖片不改產品 source。

## 保留與清理

未合併前保留 #477 Compose projects、named volumes、diagnostics、SEC assets、keys 與 worktrees。清理只允許在 merge／結案後針對本 issue 的 project、worktree 與 branch，禁止 global prune、刪除 #462 資料或繞過 managed-worktree 保護。
