# Fundamental UI 後續實作交接

本文件供設計師及工程師建立後續 issue，不代表已批准擴大產品能力。推薦布局及證據在 [研究報告](README.md)，格式規格在 [number-format.md](number-format.md)。資料基準為 `cf091fb3b3518ef20c616947ce390bf069bfe031`，開始實作時再核對 main、契約與 installed Next.js docs。

## 元件責任與資料映射

| owning module | 後續責任 | 資料輸入與邊界 |
| --- | --- | --- |
| `fundamental-service-facts.ts` | 保留既有 runtime parser 與 source binding 驗證 | Decimal、fact variants、projection_type、base/root/scenario 身分；不因 UI 缺值放寬 parser |
| `fundamental-report-model.ts` | 加入穩定語義 key、display metadata、可比較 series 投影 | fact 保留 normalized_field；assumption 保留完整 path；node 保留 node_id/unit。UI 不解析 human label |
| feature-owned formatter | 對 raw 產生 readable display 與完整值操作文案 | money、per-share、ratio、beta、shares、count、year、missing variant。只做表示變換，不計算估值 |
| `report-value.tsx` | 顯示短值、具名 evidence button、完整精度入口 | raw 與 display 並存；值與單位穩定排版；不把 display 回傳作 mutation input |
| `valuation-summary.tsx` | 每股 base 主值、總股權值、日期與品質分層；主要值可查 | perShare/totalEquity 與相應 base node identity；EV 另名。不得把 intrinsic_value 當 EV |
| `valuation-uncertainty.tsx` | P05/P50/P95、base marker、條件與文字替代 | alias 依同 basis/契約去重，保留原 keys；base 不 clamp 到 MC 範圍；空 sensitivity/drivers 不畫 |
| 新 feature-owned forecast composition | 零起點營收/FCFF small multiples 與年度表 | 同一 base 的 revenue_i、fcff_i、discounted_fcff_i；node 不足留 gap；Year i 不擅自命名財年 |
| 歷史 series adapter | 核對可比後才產生趨勢 | normalized_field、issuer、consolidation、unit/currency、duration/instant、dimensions、覆蓋、filing version；不能只按 fiscal_year 排列接線 |
| `valuation-assumptions-section.tsx` | 摘要關鍵值，完整假設按需展開，方法與品質分開 | 原始、applied manual、unconfirmed 各用 source binding 判斷；不能靠 display 相等判已套用 |
| `financial-facts-table.tsx` | 精選摘要與完整 evidence table | 完整 84 rows 仍可取得。推薦科目/期間/顯示值/品質為主欄，unit/dimensions/source 在選中 detail；篩選與排序保持原 identity |
| `fundamental-report-sources.tsx` | 完整 nodes、公式、inputs、版本與 hashes | 避免再把完整 Decimal 複製到主閱讀層；保留所有查證路徑 |
| `workspace-evidence-inspector.tsx` | 選中內容優先，inventory 是可回去的瀏覽模式 | sourceKey/thread/run/artifact/preparation/result scope 全保留。Fact quality 與 assumption method 各有標籤，移除含糊 Confidence |
| `valuation-revision*.ts*` | 沿用 availability、explicit submit、operation tokens 與新 run | 唯一 editable terminal_growth、prepared、current、未 revision、完整 source identity；不加 WACC、margin 或任意情境編輯 |
| workspace shell | 沿用 desktop inspector 與窄屏 Sheet/focus return | 本 issue 不重做全站 shell 或歷史導覽。1440px 不等於 report 可用寬度，採 container queries |

新 composition 使用既有 Button、Field、Input、Textarea、Table、Tabs、Sheet、Dialog、Tooltip、Badge、Alert、Skeleton 與 Lucide。現行 Recharts lockfile 為 2.15.4，Lightweight Charts 5.1.0。Fundamental 一般圖沿用前者能力，沒有升級或新增 UI kit 前提。若需要新增 primitive，先核對現有 source-owned 版本與依賴。

## 顯示狀態與操作狀態

Calculation lifecycle、data quality、assumption method 是不同維度。`completed + provisional + conditional` 可同時成立，不能收斂成綠色 Verified。連線狀態也不能取代 artifact status。

| 狀態 | 顯示內容 | 允許操作與驗收重點 |
| --- | --- | --- |
| initial loading | 同布局 skeleton、具名載入訊息 | 不顯示靜態估值或空資料結論 |
| valuation completed | 該 artifact 的結果、品質、條件、日期 | availability 成立時才允許 terminal growth 修改 |
| facts-only | facts 與為何無估值 | 無每股值/區間；不把 null 補 0 |
| partial/degraded | 保留仍有效 section，逐項列缺失與原因 | 受影響 chart gap 或 unavailable；不要全頁蓋成成功或錯誤 |
| requires input | owning parsed outcome 與實際需要的輸入 | 沒有 typed interaction 時不能猜一份表單；警告留到 backend 確認 |
| unsupported | 模型/公司不支援的服務原因 | 不偽造替代估值；可查已有 facts |
| abstained | 服務不提供結論的原因與現有證據 | 不以 empty/error 改寫語義 |
| service/parser error | 對應 section 或 request 錯誤；可用舊結果仍保留 | 有安全語義才提供 retry；parser drift 不能被 empty 掩蓋 |
| stale | 明示資料日期、過時原因與前一結果 | 不自行刷新改 timestamp；更新是否可重試由 owning hook 決定 |
| reconnecting | 連線恢復提示，保留來源與結果 | snapshot/event identity 核對完才改 completed；禁止重複 mutation |
| history | 原 artifact 日期、假設與唯讀說明 | 來源可查；沒有 textbox/Recalculate，也不能以 history 身分觸發 mutation |

推薦原型只模擬這些狀態的主要顯示差異，沒有完整 skeleton、retry、解析錯誤或實際 SSE。產品必須按 typed model 實作，不能複製原型的 selector 為服務邏輯。

### Terminal growth 的完整流程

1. 顯示目前原始或已套用值、方法與服務允許的操作。歷史、已修改與 availability 不成立者呈現唯讀原因。
2. 修改百分比與原因只形成 draft，明示「尚未套用」。沿用 exact decimal shift，`2.5`% 對應 raw `0.025`；不得用浮點 round-trip。
3. 按 Recalculate 才提交。保留 previous artifact 與時間，禁重複提交；不要即時改動估值或百分位。
4. Submitted 仍非結果完成。新 run/artifact 讀取及 source identity 確認後，才顯示新結果、已套用 manual 值、理由與比較。
5. 新結果與上一份各有 artifact/run/preparation 身分。MC P50 與 deterministic base 的新舊比較仍分開，不混用 hashes。
6. Owning service 拒絕時顯示 code 與原因，沒有新估值值。5% retained 案例是 `MANUAL_OVERRIDE_INVALID`，manual 上限 0.04；此限制不能反過來否定原 automatic 4.92%。
7. 失敗或逾時保留可用舊結果與 draft，依現有 operation tokens 拒絕遲到或跨 source 回應。已建立 run 是否可再試，按現有 owning state 決定，不自動重送造成兩次修改。

Research 是 opt-in。pending/error/unavailable/no acceptable claim 必須可結束而不出現 Apply。只有經現有服務及授權綁定接受的 claim 才可 Apply 成為 draft；Apply 不是 Recalculate。#462 沒有 live licensed success 證據，後續不能把靜態 ready 示意當成 provider 已部署。

## 後續 issue 的驗收案例

下表是工程驗收要求，並非本研究全部已實作。重用真實 artifact，合成資料僅作 formatter 或缺失邊界，必須標明身分。

| 編號 | 輸入/動作 | 應觀察結果 |
| --- | --- | --- |
| F01 | 真實 MSFT base/quantiles | base USD 229.88、P50 USD 173.10、P05 144.67、P95 198.00；base marker 可在 P95 外 |
| F02 | 原始0.0492、WACC、Beta、reinvestment | 4.92%、10.28%、1.28、40.00%，Beta 無 %；所有 raw 不變 |
| F03 | revenue331839000000/scale6 | USD331.84B；inspector 仍 raw331839000000 與 source scale6，不重乘 |
| F04 | number-format 全部邊界表 | rounding、負數、極小非零、極大值、零、missing/not-applicable 各符合明確規則 |
| F05 | 相同數字但不同 quantile 語義 | 只去契約 alias，不刪除合法相同分位值；缺一分位不補 |
| F06 | 五年 nodes 完整與缺項 | 圖/表直接使用服務值；缺項留 gap；Year 1 不推算公曆年份 |
| F07 | 不同 period/unit/dimension/history coverage | 不連成趨勢，說明不可比條件，保留 facts 來源 |
| F08 | 三組 scenario、空 sensitivity/drivers | 真實順序與 identity；無概率/排序命名；無 histogram/heatmap/tornado |
| F09 | capital claims 完整性為 false | 條件假設與未知資料持續可見；不以假設圖偽裝觀測完整橋接 |
| F10 | 點主值、fact、manual、node、quantile、scenario | 選中 detail 先顯；raw、來源、unit、period、formula與適用 identity scope 正確；不混 base/root/scenario |
| F11 | 原值複製、顯示值複製、剪貼簿拒絕 | 原始貼上逐字等於 raw，顯示值帶預期格式；拒絕時可選原文且回饋正確 |
| F12 | draft terminal growth2.5%與原因 | 未按 Recalculate 前結果不變；submit raw0.025；pending標 previous 並禁重複 |
| F13 | retained revision success | 新 base168.92，原始4.92%與applied2.50%可分別查證，新的日期/identity/品質全部取新artifact；已修改唯讀 |
| F14 | retained5% refusal | MANUAL_OVERRIDE_INVALID及服務原因；無成功估值0、execution或hashes；舊結果可查 |
| F15 | 失敗、切source、遲到回應、重連 | 不採用跨run/preparation或失效operation的結果；保留真實狀態 |
| F16 | Research opt-in unavailable/error/no claim | 不改draft、不出現可Apply保證；成功受授權/引用/綁定驗證；Apply仍需明確重算 |
| F17 | 歷史讀回 | 原artifact與原假設，來源可查，無編輯控件或mutation |
| F18 | 320/390/768/1440及獨立窄report pane | 依container reflow，短值不拆字，長文字/hash/URL不撐破；2D table可局部滾動並有提示 |
| F19 | light/dark、200% browser zoom、reduced motion | WCAG對比與focus可見、內容不遮蔽、頁面reflow、圖表可用表格讀取，不用純色辨識 |
| F20 | 鍵盤/觸控/螢幕閱讀器 | 具名數值入口、labels、Tab順序、Sheet focus containment/Escape/return、動態status可讀；不用hover作唯一入口 |

正式 UI issue 仍須適用 tests、lint、typecheck、Docker 與端到端驗收。此純研究的原型檢查不能把後續 engineering gate 標成 VERIFIED。

## 建議交付切分與依賴

| 後續範圍 | 既有資料可支持的改進 | 另需資料/決策 |
| --- | --- | --- |
| 格式與閱讀層 | typed semantic key、formatter、summary/alias/假設/facts disclosure、selected detail 優先 | 先採納 number-format 規則；不改 financial policy |
| 預測與歷史 | 服務 nodes 投影、年度表、單位與可比歷史 gate | 每模型 nodes 覆蓋核對；無資料就 unavailable |
| 重算與來源體驗 | 既有 terminal growth flow、previous/new/refusal、read-only、copy/source連結 | 真實 API/browser/evidence scope 驗收；Research success另有provider依賴 |
| 未來圖表或報價 | 本研究只列資料需求 | MC draws、sensitivity coordinates、完整capital claims、正式quote contract、peer/statement coverage，另行立案 |

原型為可丟棄研究工具。移入正式產品前重新以 owning modules 實作，保留現行 contract→parser→model→UI 邊界。沒有 topology 或 runtime ownership 的已實作改變，因此本研究不觸發 architecture-skill-maintainer。
