# #483 Fundamental 圖表互動與數值排版驗收

實作 commit `7a65585c605d8dd22934e3f5823595dac2d80c27`，分支 `codex/issue-483-report-interaction`。對應 [#483](https://github.com/sosodennis/value-investment-agent/issues/483)，延續 #477／PR #481 的正式報告 UI。

## 修正與重現

正式 workspace 的 facts 表格在 1335px viewport、1021px 表格區域下，Value 欄只有 69.8125px。`USD 155.24B`、`7.43B shares` 按鈕高 60px，日期欄只有 97.828125px。表格 auto layout 加上長 ID，配合數值元件的任意字元換行，將主要資料拆碎。舊 Revenue trend 的圖面沒有 button。

修正後 Value 欄約 172.8px、按鈕高 20px，Period 欄約 241.9px。長 ID 可換行，金額與日期保持完整。具名、可聚焦區域直接承擔橫捲，沒有另一層匿名 scroller。所有 84 筆 retained facts 在 1440／1335／768／390／320px 保持單行數值與日期，320px 的 ArrowRight 可捲動該區域。

Forecast／可比 History 採 Recharts 線圖，加入軸與單位。圖點上的 native button 支援 hover／focus 查值及點擊、Enter、Space、觸控查證。傳回原有 EvidenceSelection，完整 raw 與服務身分不經座標重建。線性圖保留缺失年度缺口。

Monte Carlo 改為共用金額軸的分位區間圖。P05、P50、P95 及獨立 Base 各有操作列，相同值仍可分別查證。只有實際 P05、P95 才畫區間；Base 加入共同座標範圍。這次 history 的 P50 為 USD 175.50、P95 為 USD 200.59、Base 為 USD 229.88／share。這些值屬當次 retained artifact，不替換固定 #462 樣本數字。服務未提供 draws／bins，沒有製造 histogram、density 或未來股價機率。

## 設計與審閱

比較 Recharts 領域元件與 SVG 加 HTML 互動 target 兩案。獨立判讀分別為 8／10、6／10。採 Recharts 趨勢圖，保留 feature ownership；Monte Carlo 使用專用 HTML／CSS 座標列，讓相同分位與 Base 有獨立 target。沒有新增通用 chart model、wire contract 或依賴版本。

獨立完整審閱 `45ae9efd` 為 PASS + NOTES。依建議新增 Base／P95 真實 bounding box 順序及圖內邊界斷言，並檢查缺失年度的 rendered curve 不連線。刻意將 connectNulls 改為 true 的隔離 negative control 產生 `M62,18L222,173.99998589677526`，準確失敗 1／21 項，恢復後 21／21 通過。

最終獨立審閱 `7a65585c` 為 PASS，另獨立執行 44 項相關測試通過。9 個變更檔的註解及 suppressions 均為 0。作者自查與 no-comments 不代替此完整審閱。

## 命令與結果

下列前端命令在 `frontend/` 執行，全部 exit 0。

| 命令 | 結果 |
| --- | --- |
| `npm run lint` | 通過 |
| `npm run typecheck` | 通過 |
| `npm run test -- --run` | 60 files、520 tests 通過 |
| `npm run check:contrast` | Light／dark 既有 tokens 通過 |
| `docker compose … build frontend` | production image 建置通過，revision label 為實作 commit |
| `npx playwright test --config e2e/fundamental-report-live.config.ts --grep 'Fundamental report reading regression|history is immutable|real history reflows'` | 5 passed，11.0s |
| `node <runtime>/visual-production.cjs` | 15 captures，所有圖點在圖內且 document 無橫向溢出 |
| `python3 <runtime>/preflight.py` | 精確 Git、env／overlay digest、Compose、image revision、ports、HTTP、健康狀態通過 |

瀏覽器使用 `FUNDAMENTAL_LIVE=1`、base URL `http://127.0.0.1:22881`，登入檔保留於 runtime 且未提交。選用的 5 案只讀取歷史與查證，不建立 analysis、不送 workflow mutation、不重算。沒有 API 替身。原有重算、Research 與拒絕案例本次未重跑，因其 owning code 沒有變更。

Light／dark 另在 1440／390／320px 擷取 Monte Carlo 與 Forecast 圖，所有 mark bounding boxes 均在 figure 內。透過正式 workspace splitter 鍵盤操作，report 寬度從 645.671875px 縮為 358.640625px；同時核對圖表與 facts 局部橫捲。既有 history reflow 案另涵蓋 768px、reduced motion、Sheet 正反向 focus cycle、Escape 與 focus return。

## Canonical runtime tuple

這是 frontend 唯讀 history 驗收。Fundamental 服務未啟動，沒有 SEC 取數、估值或 revision 請求。既有 `scripts/acceptance_preflight.sh` 僅支援完整雙 stack 或 Fundamental service scope，因此本案沒有宣稱該腳本通過；改由 scope 相符的 preflight 核對實際依賴，沒有借用舊 #477 的 VERIFIED 狀態。

| 欄位 | 值 |
| --- | --- |
| Worktree | `/Users/denniswong/.codex/worktrees/issue-483-report-interaction/value-investment-agent` |
| Branch | `codex/issue-483-report-interaction` |
| Implementation commit | `7a65585c605d8dd22934e3f5823595dac2d80c27` |
| Application project | `value-investment-agent-denniswong-483-app` |
| Compose files，依序 | `docker-compose.yml`、`docker-compose.override.yml`、`compose/verification/docker-compose.issue325-app-fundamental.yml`、`<runtime>/app-overlay.yml` |
| Env-file | `/Users/denniswong/.codex/diagnostics/issue-483-report-interaction/runtime/app.env` |
| Env SHA-256 | `632de53f2903ff3beba34170f272142ea11f08b1b5a028bcedef8c5bdd1e80ed` |
| Overlay SHA-256 | `eeabb5b1253db00042e2233868601e629ed1b553df206a87e87dd62931f4bb20` |
| Backend／frontend published ports | `127.0.0.1:22880`／`127.0.0.1:22881` |
| Frontend image ID | `79f164c966b5b751e21e779da37c9b8c626f006081610f085df6a0e1c840a7fa` |
| Fundamental project | 未啟動，不適用 |
| Browser session | 新建 production Playwright contexts，reading-production／visual-production，均已關閉 |
| Thread | `thread_7a3a4b05-00cb-4d0c-9525-4124a2f46a79` |
| Run | `cb0bd42e-4580-4671-8513-d7cdfa4c2aaf` |
| Artifact | `bb6147b4-341c-4cae-a904-c69b18b5207f` |

路由 `/workspace?thread_id=thread_7a3a4b05-00cb-4d0c-9525-4124a2f46a79&run_id=cb0bd42e-4580-4671-8513-d7cdfa4c2aaf`。Application 使用由已停止的 #477 disposable local PostgreSQL volume 複製的獨立 #483 volume；來源唯讀且保留。Backend／provider 沿用未變更的既有本機 image，前端使用獨立 #483 production image。

本機證據根目錄 `/Users/denniswong/.codex/diagnostics/issue-483-report-interaction/runtime`，包含 runtime-tuple.json、preflight-production.json、checks-7a65585c.json、reading-production.log、visual-production.json、圖表截圖及 negative-control log。未提交 credentials、cookies 或完整登入狀態。

## 限制與清理

實際 screen-reader 朗讀及新的原生 200% zoom 本次未驗證，未標為通過。使用者已降低 screen-reader 驗收優先序；鍵盤、focus、touch 仍完成實測。

合併與資源清理結果於 PR／issue 結案紀錄補上。只處理 #483 project、臨時工作樹及分支，保留資料 volumes 與已受保護的 #477 primary checkout。
