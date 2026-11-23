# #477 獨立實質審閱：PASS＋NOTES

交付候選 SHA：`849df68e7f03da8489ae285dafe0cdcf39cdfa74`。最新產品 SHA：`75c75c29745a6f802eb2000ac31bb0a52931107e`；75c75c29→849df68e 僅驗收文件與四張圖，frontend tree 相同。審閱基準：`04fb2e0922c10bde806bdafcb2c71c5872e1e64d`。本 reviewer 未撰寫產品、測試或服務變更，也未 push、開 PR 或 merge。獨立 checkout `/Users/denniswong/.codex/worktrees/issue-477-independent-review/value-investment-agent` 保持乾淨 detached HEAD；所有重現程式、logs 與本報告均在 repo 外。

程式與獨立資料／history 審閱完成；已接受的 parser、unit、revision operation 與 Header findings 均修復並重驗，沒有新的未解產品 finding。候選849df68e完整六案real-service已全數通過，獨立審閱結論為PASS＋NOTES；沒有未解的本次產品阻擋finding。實際 screen-reader 朗讀未驗證，依使用者最新優先序保留為限制，不作合併門檻，也不宣稱通過。

## 使用者最新範圍與驗證決定

- #480 原為 scope 外全站 Header overflow。使用者明確授權「可以，你認為有需要就全站fix」，75c75c29 於 owning app-shell 作最小 flex/shrink 修正。
- 使用者對 actual screen-reader 驗證表示「Ok，a11y不是我們的重心」。本報告保留實際 VoiceOver 朗讀／字幕無法觀測的限制；process 啟動或 DOM labels 不當成 actual-SR pass。這項限制不再阻擋交付。

## 查核範圍與修正結果

| 發現 | 修正與獨立重驗 |
| --- | --- |
| #478：NaN／Infinity／空字串／not-a-number 的 numeric fact 通過 parser，formatter 在 VM render 拋錯 | owning parser 驗證 Decimal grammar，合法質性文字 typed text 保留。初始 probe 在 bcbce5dc 與 1a4de58d 重跑，四例均 parsed=false。 |
| #478：不存在曆日通過 regex，Date.parse=NaN 讓 history 錯判 comparable | UTC calendar roundtrip parser；原 2025-99-99 probe 在 parser 拒絕。 |
| #478：field 名稱＋currency 直接推斷金額／股數，未證明實際 unit | 1a4de58d 核對 fact.unit、context.unit_qname、measure 及幣別。相同 shares／ratio／unknown unit probe 現保留 raw＋實際 unit，history=unavailable 並有原因。完整 retained 財務數字保持正確。 |
| refusal harness 預設沒有 Fundamental artifact | bcbce5dc 改讀 exact degraded refusal artifact，核對 MANUAL_OVERRIDE_INVALID 及不存在成功估值。Retained probe 與真實服務 refusal 證據通過。 |
| 歷史 metrics 長 Decimal／wire unit、count 未分組、quantile caption 位置、Sheet title／close label／focus 收尾 | b63d4207 與 Slice 4 已修；讀碼、相關測試及獨立實頁驗 Sheet labels、Tab 循環、Escape、原 trigger focus return。 |
| #479：合法同 run ticker-selection resume 中止原 sendMessage operation，使其回 superseded，workspace 不採納後續合法結果 | 正式 useAgent＋abort-aware SSE probe 先重現，再於 c46d9fba 重驗為 started；validated snapshot 後立即回傳 run identity，背景 stream 仍受 current/abort guard，recovery failure 為 closed/error。主線真實 success／refusal flows 已交叉核對。 |
| #480：320px global Header 造成 document scrollWidth327 | 75c75c29 左區 flex-1/min-w-0、org Combo 可縮，nav/brand/account 保留操作尺寸。窄屏 brand 以 sr-only 保留 FinanceAI Lab accessible name。獨立 runtime light/dark×320/390/768/1440 全部 scrollWidth=clientWidth；nav/org keyboard 與 focus return 通過。 |

詳細發現與原始重現保留於 `initial-review.md`、`unit-finding.md`、`resume-finding.md`；原始失敗證據不當成修正後結果。

## 實質程式與金融語義審閱

- Decimal formatter 使用 canonical raw；HALF_UP、極小非零、量級晉級與 scientific fallback 分離顯示和原值。Source scale 只作 metadata，不重乘；顯示值不作 mutation input。
- Deterministic base、MC quantile 與 service scenario 各自保留 input/result binding。P50 與 base 分別呈現；alias 依契約標記，不按顯示值相等刪除。
- Forecast 僅投影 base 服務 nodes，缺項留 gap，不補金融公式。History 核對 issuer/security/consolidation、currency/unit/concept/dimensions、period/coverage/filing lineage；修正後不支援 unit 不連線。
- Main value、fact、node、assumption、quantile、scenario、historical metric 保留 raw/display、來源與 run/artifact/preparation/result scope。Comparison 的 previous evidence 使用舊身分。
- Revision 只開現有 terminal-growth，exact decimal shift 提交。Retained attempt 保留舊 output/panel/draft；採納須核對新 thread/run/artifact、issuer/share/currency/snapshot、原 preparation 及 exact manual raw。來源切換與遲到操作不採納。
- Activity 入口只連既有 typed workflow interaction；沒有替 untyped requires-input 猜表單。Research 維持 opt-in，沒有接受的 claim 不提供 Apply。
- 沿用 semantic tokens、既有 report ownership、source-owned primitives；沒有新增估值公式、政策、授權或套件版本。
- Header delta 只改可用寬度分配與窄屏可見文字，沒有改 interaction/focus ownership。Auth routes 保留品牌文字，md 回復可見品牌名稱。

## 獨立執行檢查

| SHA | 檢查 | 結果／證據 |
| --- | --- | --- |
| 0152304c | npm ci；typecheck；lint；report/inspector tests | exit0；8 檔137 tests。initial-*.log |
| bcbce5dc | typecheck、lint；report/inspector/workspace/boundary tests | exit0；11 檔218 tests。final-typecheck.log、final-lint.log、final-tests.log |
| bcbce5dc | 原非法數字／日期 probe；完整 retained parser→VM→series | exit0，非法值在 parser 拒絕，retained assertions 全過。final-probe.json、retained-probe-final.json |
| 1a4de58d | report/boundary tests、typecheck；unit/retained/原始 boundary probes | exit0；9 檔208 tests。unitfix-*.log、unit-probe-unitfix.json、retained-probe-unitfix.json、initial-probe-unitfix.json |
| 7ceb6b00 | workspace tests、typecheck；正式 hook resume probe | tests exit0，1 檔38 tests；probe 重現 superseded（缺陷證據）。activity-entry-*.log、hook-resume-probe.log |
| c46d9fba | 同一 abort-aware hook probe 修正後期望；hook/identity/workspace tests；typecheck、lint | exit0；3 檔68 tests；resume 前已 started，合法同 run resume 後維持身分。hook-resume-fixed-probe.log、hookfix-*.log |
| 75c75c29 | shell/navigation/workspace tests；typecheck | exit0；3 檔43 tests。headerfix-tests.log、headerfix-typecheck.log |
| c46d9fba、75c75c29 | exact tuple 的 app/fundamental compose config --quiet、acceptance_preflight（REQUIRE_SEC_IDENTITY_RESOLUTION=1）、frontend actual port | exit0；port 127.0.0.1:22681。preflight-c46d9fba.log、preflight-75c75c29.log |

Retained probe 使用 #462 完整 wire envelopes，不以 sample.json 冒充完整 artifact；reference=null 的純投影回歸不假造 live identity。Base USD229.88/share、P05 USD144.67、P50 USD173.10、P95 USD198.00；revenue raw331839000000→USD331.84B、scale6未重乘；revision USD168.92/share、manual0.025→2.50%、automatic0.0492→4.92%與原 preparation digest 保留；refusal 為 MANUAL_OVERRIDE_INVALID，沒有成功估值。

Retained 三檔 SHA-256：base `192c54598fc4cd88fc79c8dfc3a6ac8870aa9ccdd28eb35793a7ada26798549c`；revision `09c39098a5a673a81a73eff756688a40a1ab931345dd41a84659e574494ea2e1`；refusal `8933403ec7631ebca2b6833fca13b6244e37699f514a09403c10cc37bb665449`。

## 獨立真實頁面

正式 URL `http://127.0.0.1:22681`。最新 frontend image `sha256:43077280f5381252d85131bc6761cfd42a56d7289baa7b13ffbc3fb94caec08c`，build commit75c75c29；已重讀 canonical tuple，exact preflight/source equality 通過。

使用既有 history `thread_7a3a4b05-00cb-4d0c-9525-4124a2f46a79`／`cb0bd42e-4580-4671-8513-d7cdfa4c2aaf`，artifact `bb6147b4-341c-4cae-a904-c69b18b5207f`，只讀不建立 run/resume。所有獨立 contexts 已關閉，沒有操作 native Chrome/CUA。

- c46d9fba session `independent-review-d1975fef-8900-49e3-8774-af685cf1e7df`，headless Chromium156.0.8078.4。頁面公司、股份、USD、日期、base USD229.88、MC P50 USD175.50、P05 USD144.47/P95 USD200.59、4.92% terminal/10.28%WACC/Beta1.28/40.00% reinvestment 及限制可讀。新 live MC 數字依實際 artifact，未硬套舊 retained quantiles。
- Selected detail 逐字核對：base 的 raw/base input/result hashes；P50 的 raw/MC root hash；revenue 的 raw331839000000、fact id/content hash/scale6；scenario1 的 raw/自己 result/input hashes。四種均有正確 thread/run/artifact。沒有 terminal-growth 編輯或 Recalculate，mutation=0，pageerror=0。證據 history-scope.json/.log。
- 390px Evidence Sheet title「Evidence details」、close label 正確；raw textarea 完整保留。Tab 走過 copy original/display、Technical identity、Open artifact、Browse evidence、close並循環；Escape 返回原 Inspect trigger。證據 history-keyboard.json/.log。
- c46d9fba 獨立 light/dark×四寬度的唯一失敗為320 document327；保留 history-theme.json 作修正前證據。
- 75c75c29 session `independent-header-review-87c4ff9c-8ee2-4cd1-8f73-b7dd368570e3`：light/dark×320/390/768/1440，document scroll=client；brand、org、theme、account boxes 均在頁內，brand accessible name FinanceAI Lab。320 nav Enter 開啟、dialog containment、Escape return、org Combo 開關與 focus return皆過；mutation=0、pageerror=0。證據 header-runtime.json/.log、header-light-320.png、header-dark-320.png。第一版外部 probe 在動畫後同步讀 focus 太早，改為等待 toBeFocused 後同一路徑通過，未作產品修改。

## 主線真實服務證據交叉核對

以下 mutation/touch/native 操作由主線執行，本 reviewer 閱讀正式 log/JSON，沒有冒充親自執行。

- c46d9fba 完整6案為5pass/1layout fail，唯一為320px Header overflow；expect.soft 延續相同門檻，沒有把失敗改 pass。
- Success：new run `65ef26b7-6866-4ca1-9df4-52c79b53848f`、artifact `3c3c97d3-db83-489c-9735-13369da467ff`；submitted/applied raw0.025；new base168.92316962973986376214271505310878928165576150584；一次 run start。Typed Activity resume 後採納新結果。
- Refusal：run `5279813a-c01e-47e7-a92e-675b182f1555`、artifact `654d699f-323f-4483-8a63-9d5587aeecfb`；MANUAL_OVERRIDE_INVALID、5% draft及USD229.88 previous保留；run completed、無成功估值。
- Research unavailable/SEARCH_PROVIDER_FAILURE、acceptedClaimCount0、draft2.5保持；history mutations0；touch390px通過；正反向 focus/Escape/return通過；獨立窄report pane width645.67→358.64。
- 主線另回報 native Chrome 真200% browser zoom/reflow 截圖、Copy original→TextEdit逐字 raw貼回並 undo scratch；本 reviewer 未操作 native Chrome，僅記主線手動證據。

後續含圖候選849df68e已重新build並完整六案通過，詳見下段；實際screen-reader未驗證只保留限制，不標pass。

## 候選內容與 patch identity

獨立 checkout 已切至乾淨 `849df68e7f03da8489ae285dafe0cdcf39cdfa74`。75c75c29→候選僅修改四份驗收 Markdown/JSON 並新增四張WebP；沒有產品或測試變更，frontend tree 均為 `d94bad25652d1e6f2d1b06e37fe33f2dba78d26d`。四張圖已目視檢查，SHA-256 與 evidence 表格一致；320px light/dark 為修正後畫面，200%兩圖保留原生Chrome與可讀公司／估值數字。

base `04fb2e0922c10bde806bdafcb2c71c5872e1e64d` → candidate `849df68e7f03da8489ae285dafe0cdcf39cdfa74`：

- `git diff <base> <candidate> | git patch-id --stable`：`9da628efc141440468d5c901fbba6e4f75ae4a1b`。
- `git diff --binary <base> <candidate> | git patch-id --stable`：`398fb9e9794cd8abebd99baa3701a112760a20c4`（包含可重建的 binary patches）。
- `git diff <base> <candidate> -- frontend | git patch-id --stable`：`f772ca0aba7f3001c5d19c5f3e951f61420aea93`。

額外組織設定頁內容 grid/member table overflow 另列 #482；該頁 Header 控制項幾何通過不等於整頁 document 通過。本次 Fundamental assertions 沒有因此放寬，#482 不冒充已解。

## 最終候選驗證與結論

PASS＋NOTES，適用base `04fb2e0922c10bde806bdafcb2c71c5872e1e64d` → candidate `849df68e7f03da8489ae285dafe0cdcf39cdfa74`。本reviewer沒有修改產品，也沒有主工作樹寫入任務／ownership；主工作樹只讀，checkout／npm checks在獨立worktree，報告與probes只寫repo外。

已交叉讀取 `runtime/live-849df68e.log`（6 passed，4.8m）、`live-849df68e/.last-run.json`（status passed、failedTests=[]）、各正式JSON及 `checks-849df68e/verification.json`（lint/typecheck/vitest/contrast/retained全exit0）。所有本輪JSON的implementationCommit皆為849df68e；完整run/artifact provenance依實際值記錄。

- Success：run `da7d3ffe-cf99-4637-9cd9-0a1f123da58f`、artifact `a2fb591d-65be-4e56-bf33-ffb5ee267bd1`；submitted/applied raw0.025，new base168.92316962973986376214271505310878928165576150584，runStarts1；與原run/artifact不同。
- Refusal：run `838e04ca-27a7-4d70-bbbb-6d888252c2dd`、artifact `36b386ee-2b9d-420f-9762-f2a2577c0b09`；MANUAL_OVERRIDE_INVALID、retainedDraft5、previousDisplay USD229.88/share、run completed。
- Research：unavailable/SEARCH_PROVIDER_FAILURE、acceptedClaimCount0、draft2.5；沒有許諾可Apply。
- History：exact原artifact、mutations0、raw/sourceScale/node/scenario scope皆有記錄。
- Layout：light/dark×320/390/768/1440、reduced motion、獨立窄pane通過；完整正反向Sheet focus/Escape/return為true。Touch390通過。

已接受的#478／#479／#480均在owning layer修正，程式與受影響checks、獨立probes／實頁及正式服務驗收相符；無需新的產品修正。可依專案CI與merge流程繼續交付。

NOTES：actual screen-reader spoken output未驗證，依使用者最新優先序不是本次merge gate且不標pass；組織設定頁內容grid/member table overflow另列#482，沒有將該頁document稱為pass。主線只允許後續驗收Markdown/JSON metadata；若frontend、圖片、測試或服務再改動，此結論需重新核對delta。
