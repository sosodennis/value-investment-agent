# #477 獨立實質審閱（c46d9fba，未授予整體通過）

審閱者未撰寫本次產品、測試或服務變更。使用獨立乾淨 checkout：`/Users/denniswong/.codex/worktrees/issue-477-independent-review/value-investment-agent`。所有重現程式、檢查 logs 與本報告均在 repo 外的 diagnostics/review 目錄。未 push、開 PR、merge、啟動或變更共用 runtime。使用獨立 Playwright contexts 完成唯讀 history 查核；均已關閉。沒有操作原生 Chrome 或 CUA。

基準：`04fb2e0922c10bde806bdafcb2c71c5872e1e64d`。目前獨立 checkout：`c46d9fba191c3b793749198ca444b5ef96f3396d`

正式 runtime：frontend c46d9fba，`http://127.0.0.1:22681`，image `sha256:1fa6bc639843b11fd1176c3bf9bc5d141a93304ec129739f52a095f0d99aa7ec`; exact preflight/source equality pass。獨立唯讀 browser session：`independent-review-d1975fef-8900-49e3-8774-af685cf1e7df`，headless Playwright Chromium 156.0.8078.4。

## 目前結論與未完成項目

本次獨立實質審閱已完成，沒有新增未解的產品程式 finding；#480 範圍與 F20 screen-reader 驗證仍阻擋整體完成，因此不授予 merge／closure 通過。已完成金融語義、來源身分、formatter、parser、series、revision reducer／workspace operation、evidence inspector、reading hierarchy 的程式與資料實質審閱。以下項目明確待處理：

- **#479 已修復並有真實服務證據**：合法同 run ticker-selection resume 原本使 sendMessage 回 superseded，已於 c46d9fba owning hook 修正並以相同 abort-aware probe 重驗為 started。另已交叉核對 root 的 live-c46d9fba log／JSON：2.5% success 新 run/artifact/base 與 5% refusal/previous/draft 均通過；這兩個 mutation 流程由 root 執行，本 reviewer 沒有重複 mutation。
- **#480 scope 未解**：root 在 320px 正式頁面觀察 globalHeader 造成 327px document 寬，目標原排除 shell，正等待 scope 決定。本 reviewer 已於 light/dark 320px 獨立重現同一 7px document overflow；article 本身在 320px 內，但 F18 不可通過。
- **F20 screen reader 未驗證**：root 已啟動 VoiceOver process，但目前 CUA 沒有可觀測朗讀／字幕／last phrase。啟動 process 不等於朗讀驗收。本 reviewer 沒有 screen reader 成功觀察。
- **真實 history 已查核；整體實頁仍未全通過**：獨立唯讀 browser 已查核 history 內容、evidence、Sheet keyboard/focus 與 mutation guard；已交叉核對 root 完整 6 案的結果：5 pass，唯一 layout case 因 320px overflow fail；touch 與完整正反向 focus cycle 已通過。原生 200% zoom／系統 clipboard 由 root 操作並報告，screen-reader 子項仍未驗。

## 已確認並修正的審閱發現

| 發現 | 影響 | 修正與獨立重驗 |
| --- | --- | --- |
| 非法數字 fact 穿過 parser，formatter 在 render 的 VM 投影拋錯 | NaN、Infinity、空字串、not-a-number 導致 report crash，沒有走 artifact parser error | #478，整合 b63d4207；在 bcbce5dc 與 1a4de58d 重跑初始 probe，四例均 parsed=false，錯誤在 owning parser。合法質性文字用 typed text 保留。 |
| 不存在曆日被 history 判成 comparable | 2025-99-99 經 Date.parse 為 NaN，期間比較失效並接線 | #478，UTC roundtrip parser；相同 probe 在 parser 拒絕。 |
| 金額／股數語義僅按 field 推斷，未驗證 source unit | revenue 的全部 units 即使為 shares、ratio、unknown，仍顯示 USD 並建立 comparable history | #478，1a4de58d；同一 unit probe 現保留 raw+實際 unit，history=unavailable 並有原因。Money/share semantics 核對 fact unit、unit_qname、measure；history 額外核對 report currency。 |
| Live refusal harness 預設沒有 Fundamental artifact | 正確 degraded refusal artifact 被誤判，且未查 code／沒有成功估值 | bcbce5dc 改讀 exact refusal artifact。完整 retained refusal parser→VM 為 service-error／MANUAL_OVERRIDE_INVALID。Live 観察仍由 root 執行。 |
| 歷史 metrics 未格式化、count 未分組、圖表 caption 位置與 Sheet label／focus 收尾 | 長 Decimal／wire unit 影響閱讀；Sheet 沒有明確 title 與 close label | de5c6429/b63d4207 與 Slice 4 已修。已讀碼及相關測試，獨立實頁已驗 Sheet label、Tab 循環、Escape 與原 trigger focus return。 |

詳細重現：`initial-review.md`、`initial-probe.ts/.json`、`unit-finding.md`、`unit-probe.ts/.json`、`resume-finding.md`、`hook-resume-probe.test.tsx/.log`。

## 已查核的實作行為

- Decimal formatter 使用 canonical raw，HALF_UP rounding、極小非零、量級晉級與 scientific fallback 分離於原始數字；source scale 只保留 metadata，不重乘。
- Base、Monte Carlo quantile、service scenario 各自保留對應 input/result binding；P50 與 deterministic base 分別呈現。Alias 依契約標記，不按顯示數字相等刪除。
- Forecast 只投影 base 的服務 nodes，缺項保留 gaps；沒有在前端補金融公式。History 核對 issuer、security、consolidation、currency、unit、concept、dimensions、period、filing version 與覆蓋；已修正日期與 unsupported units 缺口。
- 主值、fact、node、assumption、quantile、scenario、historical metric 的 evidence 保留 raw、display、來源與正確 run/artifact/preparation/result scope。Comparison 的 previous evidence 不套用 current identity。
- Revision 只開放既有 terminal-growth 契約，百分比用 exact decimal shift，draft 不即時 mutation。Retained attempt 在 pending／failure 保持舊 output 與 panel mount；新結果採納核對新 thread/run/artifact、issuer/share/currency/snapshot、original preparation 及 exact manual raw。
- 切換 thread 與 invalid operation 有拒絕／clear 路徑；合法 resume 的 superseded 缺口已在 owning hook 修正；validated snapshot 後立即回傳 started，背景 stream errors 受 current/abort guard 約束，recovery failure 會 closed/error。
- 新的 Activity 入口只連到現有 typed workflow interactions；沒有為 untyped requires-input 猜表單。新增入口與保留 panel 的程式 delta 已審；正式 useAgent 的 abort-aware lifecycle probe 及受影響 tests 已通過；真實服務互動成功／拒絕證據已交叉核對。
- UI 沿用 semantic tokens、既有 report ownership 與 evidence primitives；未新增金融服務能力、估值公式或套件版本。

## 執行檢查與證據

| SHA | 命令／probe | 結果 | 證據 |
| --- | --- | --- | --- |
| 0152304c | npm ci | exit 0 | initial checks |
| 0152304c | typecheck、lint；report／inspector tests | exit 0；8 檔 137 tests | initial-typecheck.log、initial-lint.log、initial-tests.log |
| bcbce5dc | npm run typecheck | exit 0 | final-typecheck.log |
| bcbce5dc | npm run lint | exit 0 | final-lint.log |
| bcbce5dc | report、inspector、workspace-page、boundary tests | exit 0；11 檔 218 tests | final-tests.log |
| bcbce5dc | 初始非法數字／日期 probe | exit 0；所有非法值在 parser 被拒絕 | final-probe.json |
| bcbce5dc | 完整 retained parser→VM→series probe | exit 0 | retained-probe-final.json |
| 1a4de58d | report／boundary tests | exit 0；9 檔 208 tests | unitfix-tests.log |
| 1a4de58d | npm run typecheck | exit 0 | unitfix-typecheck.log |
| 1a4de58d | 同一 unsupported unit probe | exit 0；三例 history unavailable，raw／true unit 保留 | unit-probe-unitfix.json |
| 1a4de58d | 完整 retained probe；原始非法邊界 probe | exit 0 | retained-probe-unitfix.json、initial-probe-unitfix.json |
| 7ceb6b00 | workspace-page tests | exit 0；1 檔 38 tests | activity-entry-tests.log |
| 7ceb6b00 | npm run typecheck | exit 0 | activity-entry-typecheck.log |
| 7ceb6b00 | 正式 useAgent + abort-aware SSE 的合法同 run resume probe | exit 0；重現 superseded 缺口，並非通過產品驗收 | hook-resume-probe.log |
| c46d9fba | 相同 abort-aware probe 的修正後期望 | exit 0；resume 前已回 started，合法同 run resume 後維持 accepted identity | hook-resume-fixed-probe.log |
| c46d9fba | hook／identity／workspace tests | exit 0；3 檔 68 tests | hookfix-tests.log |
| c46d9fba | typecheck、lint | exit 0 | hookfix-typecheck.log、hookfix-lint.log |

Retained probe 使用 #462 三份完整 wire envelopes；不以 sample.json 冒充完整 artifact，reference=null 的純投影回歸沒有假造 live identity。

- Base：USD 229.88/share；P05 USD 144.67/share；P50 USD 173.10/share；P95 USD 198.00/share。
- Revenue raw 331839000000 → USD 331.84B，source scale=6 未重乘。
- Revision：USD 168.92/share；manual 0.025 → 2.50%；原 automatic 0.0492 → 4.92%，original preparation digest 保留。
- Refusal：service-error，MANUAL_OVERRIDE_INVALID；沒有成功估值。
- Base、revision、refusal 檔案 SHA-256 分別為 192c54598fc4cd88fc79c8dfc3a6ac8870aa9ccdd28eb35793a7ada26798549c、09c39098a5a673a81a73eff756688a40a1ab931345dd41a84659e574494ea2e1、8933403ec7631ebca2b6833fca13b6244e37699f514a09403c10cc37bb665449。

最終產品查核 SHA 為 c46d9fba191c3b793749198ca444b5ef96f3396d。仍待 #480 scope 決定與 F20 screen-reader 可觀測證據；若產品再改動，應審閱 delta 並重跑受影響驗收。沒有依本報告授予 merge／closure 通過。

## 獨立唯讀 history 實頁觀察

使用 retained base history `thread_7a3a4b05-00cb-4d0c-9525-4124a2f46a79` / `cb0bd42e-4580-4671-8513-d7cdfa4c2aaf`，只讀 `http://127.0.0.1:22681/workspace?...`，沒有建立 run 或 resume；request mutation count=0。

- 頁面呈現 MSFT、MSFT common stock、USD、valuation date、base USD 229.88/share、P05 USD 144.47/share、P50 USD 175.50/share、P95 USD 200.59/share、4.92% terminal growth、10.28% WACC、Beta 1.28、40.00% reinvestment。Forecast、history、assumptions、facts、sources 均可讀，historical reports 顯示 read-only。
- 在 390px 窄頁開啟 Evidence Sheet，標題 `Evidence details` 與 close label `Close evidence inspector` 可被辨識；原值 textarea 保留 `229.88242539685962775556419207139754074672901162460`。Tab 連續移動通過 copy original、copy display、Technical identity、Open artifact、Browse all evidence、close；Escape 關閉後 focus 回到 `Inspect Deterministic base per share` trigger。
- 390px document clientWidth=scrollWidth=390，report article x=16、width=358。320px 時 article width=288、right=304，但 document scrollWidth=327；這個 7px overflow 來自 global shell，符合 root 目前待定的 #480 scope，故 F18 仍未標通過。
- 獨立 session 沒有可觀測 screen-reader utterance，F20 screen-reader 子項未驗。

證據：`history-inspect.log`、`history-desktop-text.txt`、`history-keyboard.log`、`history-keyboard.json`、`history-session.json`、`history-desktop.png`。

## 最後補查與主線證據交叉核對

- 獨立 `history-scope.cjs` 直接讀 exact real artifact，逐字核對 UI selected raw 與 Technical identity：base 使用 base input/result hashes，P50 使用 MC root hash，revenue fact 保留 fact id/content hash/raw 331839000000/scale 6，scenario 1 使用自己的 result hash。四種選中 detail 均含正確 thread/run/artifact，mutation=0，沒有 terminal-growth 編輯或 Recalculate。證據 `history-scope.json/.log`，exit 0。
- 獨立 light/dark × 320/390/768/1440 viewport probes 保留 reducedMotion=true 與 base 可見；只有 320px 的 document scrollWidth=327，其餘 scrollWidth=clientWidth。證據 `history-theme.json/.log`。
- 已讀主線 `runtime/live-c46d9fba.log`：6 個正式 real-service tests 為 5 passed / 1 failed；唯一 fail 為 light/dark 320px overflow，expect.soft 保留同一失敗門檻，未把失敗改 pass。
- 已讀正式 `revision-completed.json`：新 run 65ef26b7-6866-4ca1-9df4-52c79b53848f、artifact 3c3c97d3-db83-489c-9735-13369da467ff，submitted/applied raw=0.025，新 base=168.92316962973986376214271505310878928165576150584，只有一次 run start。
- 已讀正式 `revision-refused.json`：新 refused run 5279813a-c01e-47e7-a92e-675b182f1555、artifact 654d699f-323f-4483-8a63-9d5587aeecfb，MANUAL_OVERRIDE_INVALID，5% draft 與 USD229.88 previous display 保留，refused run completed；artifact 沒有成功估值。
- 已讀 research-terminated：unavailable/SEARCH_PROVIDER_FAILURE，acceptedClaimCount=0，draft=2.5；history-read-only mutation=0；touch-evidence hasTouch=true/390px；sheet-keyboard-focus-cycle forward/reverse/Escape/focusReturn=true；independent narrow pane report width 645.67→358.64。這些是主線執行證據，未冒充 reviewer 親自 mutation／touch。
- 主線另回報原生 Chrome final c46d9fba 的真正 200% browser zoom／reflow 截圖與 Copy original→TextEdit exact raw 貼回，scratch 已 undo；本 reviewer 沒有操作原生 Chrome，故僅記為主線手動證據，非獨立重驗。

所有獨立 browser contexts 已關閉，repo 乾淨 detached HEAD。審閱結論：已接受的 parser、unit、revision operation findings 均修正並重驗；#480/F18 與 F20 screen-reader 尚未完成，不能整體 merge／結案。
