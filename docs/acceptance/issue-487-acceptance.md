# #487 預測年度與日期折現驗收

實作 commit `452b13efb28f202ef14e1ffefa0ba0129d1d3083`，分支 `codex/issue-487-forecast-timeline`。由 [PR #489](https://github.com/sosodennis/value-investment-agent/pull/489) 一起完成 [#487](https://github.com/sosodennis/value-investment-agent/issues/487) 與模型 release 治理 blocker [#488](https://github.com/sosodennis/value-investment-agent/issues/488)。Canonical runtime、映像、來源一致性、命令、證據 SHA-256 與限制在 [issue-487-runtime.json](issue-487-runtime.json)。

## 使用者可以測試的結果

[最終 MSFT 報告](http://127.0.0.1:23081/workspace?thread_id=thread_a7ae7b38-780e-4ca2-9aa9-07710782be7e&run_id=65221f25-554e-4ddf-b825-5a4ba13e437e)，選 Fundamental，再選 Forecast。這是 retained run 的唯讀入口。要測試新分析與重算，從同環境的 `/workspace` 開始。

圖表與年度表顯示 2027E 至 2031E。E 表示估計，年份指期間結束的公曆年，沒有聲稱這是公司官方 FY 名稱。展開 Forecast periods and included coverage，可以讀取完整年度與估值日後納入的期間。

這份報告的估值時點是 `2026-11-23T10:43:47.023306Z`，沿用正式保留資料的歷史 cutoff。首期為 `2026-07-01 → 2027-06-30`，只納入 `2026-11-24 → 2027-06-30` 的 219 天。2028 年期間包含閏日，為 366 天。圖表 hover 或鍵盤 focus 顯示完整期末日期，啟動圖點或數字則查證相同 node。

| 同一報告的第一期 | 顯示值 |
| --- | --- |
| 全年 Revenue | USD 385.37B |
| 全年 FCFF | USD 86.02B |
| Future FCFF included | USD 51.61B |
| Discounted future FCFF | USD 48.67B |
| Deterministic base | USD 235.00 / share |
| Monte Carlo P05 / P50 / P95 | USD 148.60 / 180.92 / 204.05 per share |

各數字的完整 Decimal 原值仍在 artifact。數字隨當次輸入與模型而定，沒有將此表硬編碼為產品結果。

## 模型與資料責任

Fundamental Service 擁有 typed timeline，連結三期連續、consolidated、undimensioned、365 或 366 天的可比收入來源。來源期間、可用時點、估值日、基準收入與 timeline 不符時明確拒絕。52／53 週、不規則或轉換財年、過期或未來基準不由 UI 猜測。

v3 使用明示的 uniform annual accrual 與 period-end settlement。`included_fcff = annual_fcff * included_days / full_period_days`，`PV = included_fcff / (1 + wacc)^(discount_days / 365)`，採 ACT/365F。全年收入與 FCFF 維持全年語義。這是模型假設，沒有宣稱使用觀察到的 YTD 現金流。終值使用最後全年 FCFF 的年度 Gordon 近似，在最後期末形成，再折回估值日。

v3 必須具有有效 timeline。舊 v2 不接受再忽略 timeline，也不升級舊 artifact。保留 v2 artifact `bb6147b4-341c-4cae-a904-c69b18b5207f` 的 canonical envelope SHA-256 為 `4dbe25aab47bf12158d77460f491cbd982ac2497f14c376fb069510cbf323a50`。舊報告仍顯示 Year 1 至 Year 5 及缺少可靠日期的理由。

## 獨立核對與發布邊界

十個真實 SEC 來源工程案例涵蓋兩個模型與九個 SIC groups。核對 67 筆數據、五份原始 10-K 引文、Treasury 2026-11-20 的 10 年期殖利率 4.92%。事先固定的 case plan SHA-256 為 `762938d1ec090b9c15f78c0b9022657f80b692c1c8c5b860270d54a7721209a6`。

獨立 80-digit Decimal 與 float challenger 核對 290 個 nodes。十個案例在獨立、禁止網路的程序精確重播，三十個負例按預期拒絕。這些驗證證明來源期間、條件算術與重播行為，不證明預測準確性、完整 ingestion 認證或資本 claims 完整性。

獨立 financial、source-dimension、release-security 與 UI review 先行檢查相關責任層。UI review 發現終值說明將折現方向寫反，已修正。算術 challenger 曾依 literal fact ID 推斷證據語義，已改為檢查實際內容。最終獨立 executed-release review 綁定 `452b13ef`，SHA-256 為 `184d6bb7e797be6940cf23f46ca971d3d9602eb7cbdbb0fb20d0afe4028e0db9`，批准僅限本地工程 release。

首次未校準 raw release 採明確 engineering gates；需要 calibration OOS 的 promotion 保留原有 gates。唯一 strict loader 驗證受信 verifier、簽章、source revision、suite digest、報告、來源、期限與模型 admission，拒絕 absolute 或逃逸 bundle 的路徑。bundle 內部 symlink 不一概拒絕。

最終 bundle SHA-256 為 `f43aeff34dbfd4acf1373eaf982ce0ccecaf1fafa308ef02b811cc276435b0ca`，suite SHA-256 為 `b01386a6704d18fea9c9b9c0618c41b059c4ecf7808069d7506b86a4c81d634d`，有效至 `2026-11-30T18:52:39.036736Z`。`production_approval=false`，calibration 維持 inactive。

最終 no-comments 獨立審查涵蓋 46 個差異檔案。新增 25 組 doc comments／58 行，既有差異移除 1 組／1 行；reviewer 沒有再刪除或恢復註解，沒有 suppression 變更。公開 factory 契約 docstring 與 generated schema 文件符合保留例外，最終沒有待移除項或 MUST KILL finding。報告 SHA-256 為 `929564385d3d096c82ed8bce2b448085de0d341dbaa72efe72107c2bb6b81cec`。

## 真實服務與瀏覽器驗證

正式 preparation 成功，data release 為 `84b3b2a9e4a2e018f8e6155da0dfc4ecb27455212759556d4c2ff2e4dce08567`，preparation digest 為 `81471fb0c2157c6510b9cfb70ded4ac321e801eefe69319173cad403a7234c72`。原 SEC captures 與 quote metadata 沒有改成新擷取時點。兩份最新 10-K 本身包含所需比較年度。

早期準備依序拒絕未核准的第三份 filing、quote 時點不一致、舊 profile／facts 不符及 mapping namespace 不符，原始嘗試保留在診斷目錄。首次成功 preparation 後，真實 HTTP policy validation 又揭露 overrides 漏掉 timeline，回傳 `400 invalid_request`。正式 overrides 契約已修正，兩模型的 HTTP regression 與 84 項相關測試通過。失敗 run 與 log 保留，不計為成功驗收。

| 檢查 | 實際結果 |
| --- | --- |
| Fundamental 完整 suite | 5,040 passed、163 skipped、4 warnings，exit 0 |
| Frontend lint、typecheck、unit tests、contrast | 60 files、527 tests 與其他檢查通過，exit 0 |
| Contract generation、Core transport、架構與 pre-commit checks | 通過，最終 codegen 沒有額外差異 |
| 十個來源案例、290 nodes、三十個負例、十次獨立程序重播 | 全部通過 |
| Production frontend image 與 runtime Python source equality | 通過，服務 186 個檔案與 Core 818 個檔案無差異 |
| 真實服務 Playwright 六案 | 全部通過，2.1 分鐘，exit 0 |
| Canonical tuple preflight | 兩個隔離 projects、env／Compose、綁定 ports、健康與 SEC identity capability 通過 |

完整服務 suite 執行於 `04b8b187`。最終 `452b13ef` 只增加 workspace 單欄 grid 與 current-report 320px assertion，整棵服務及 Core Git tree 不變。前端各檢查、production build、六案 E2E 與 CUA 都驗證此最後 delta。合併另要求 final PR head 的 CI 通過。

六個真實 E2E 案例包含 draft 不改舊結果、exact `2.5% → 0.025`、新 run／artifact 與唯讀 revision、5% 明確拒絕、Research unavailable 終結、舊 history／raw 身分、light／dark、reduced motion、窄 pane、焦點與觸控。額外讀回 original／revision／final artifact，確認 timeline、base 與所有 service scenarios 完全一致。重算後 base 約 USD 171.62，這是本輪 v3 結果。

CUA 使用 IAB browser 2、tab 11 實際完成新分析與公司確認。最終 thread `thread_a7ae7b38-780e-4ca2-9aa9-07710782be7e`、run `65221f25-554e-4ddf-b825-5a4ba13e437e`、artifact `bf61ebee-dde6-41ce-ae19-7ceb9e176862`。鍵盤 focus 顯示 2029-06-30，首期 included 與 discounted FCFF 分別開到正確公式與原值。

新分析與 history 的 320／390／768／1440px document scrollWidth 均等於 viewport。修正前 current 頁的 auto grid track 受 thread ID 撐至 392px；在擁有該 track 的 main 加單欄約束後，320px 回到 320px。沒有以隱藏 overflow 掩蓋。320px close button 為 x272、y40、32×32，與 header 分離，Escape 返回原數字按鈕。暫時 viewport override 已 reset。

## 限制與保留資源

實際 VoiceOver 朗讀、新的原生 200% browser zoom 與 system clipboard paste 未在本輪驗證。CUA clipboard read 回空字串，不計為成功複製。使用者已降低 screen-reader 優先序，沒有重新開啟原 #477 目標。這些限制不被列為通過。

完整 workflow 的 News／Debate provider 仍可能 unavailable。本輪證據涵蓋 Fundamental 正式服務流程，不是完整 Agent pipeline 認證。資本 claims、歷史覆蓋與 forward reinvestment 的 provisional／條件限制持續顯示。

本機診斷根為 `/Users/denniswong/.codex/diagnostics/issue-487-forecast-timeline`，包含原始來源、case plan、可重跑 challenger／replay／bundle builder、獨立審閱、精確 HTTP artifacts、logs 與截圖。所有引用檔案的 hashes 記於 canonical JSON。未提交 credentials、cookies 或 private signing key。

保留 #487 app／Fundamental stacks 供使用者測試。Compose 與來源資源仍依賴本工作樹、frozen checkout 與診斷路徑，因此延後清理。#483／#485 runtime 未停用或修改。重新綁定 model evidence 時，只在隔離、可重建的 #487 DB 備份後重建兩筆精確 v3 metadata，其他來源與 v2 records 保留。

PR 合併、main commit 與 GitHub issues 自動關閉結果，在 issue／PR 結案記錄補上。
