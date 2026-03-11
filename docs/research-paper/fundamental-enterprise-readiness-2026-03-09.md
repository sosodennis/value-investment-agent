# Fundamental 分析流程企業級成熟度驗證報告（2026-03-09）

## 1. 目的與範圍
本報告依據專案內部實作摘要（`fundamental-impl.md`）與公開可驗證來源（成熟開源專案、教學/研究資料、官方規範），評估目前 fundamental 分析從資料採集到估值分析的流程與實作是否達到企業級或朝企業級方向演進，並指出風險與調整建議。

## 2. 企業級基準（公開來源驗證）

### 2.1 資料採集合規與穩定性
- SEC EDGAR 公開資料存取有明確公平存取規則：包含請求速率上限、避免過度抓取、以及要求宣告 User-Agent。這些要求通常被視為企業級資料採集的最低合規門檻之一。citeturn7view0

### 2.2 XBRL 財報品質驗證
- XBRL US Data Quality Committee（DQC）維護並發布一套經審核的 XBRL 驗證規則，並被多家服務提供者實作，代表這是業界可採用的標準化品質檢查來源。citeturn14view1
- XBRL US 官方也明確指出可使用開源 Arelle + DQC Rules Validator 來檢查 XBRL 報表品質，顯示這是成熟開源驗證路徑。citeturn16view0

### 2.3 血緣/可追溯性（Lineage）
- OpenLineage 提供一套開放標準，用於蒐集作業執行期間的血緣中繼資料，核心模型包含 dataset、job、run 等實體與可擴展的 facets。對於企業級審計與追溯，這類標準化 lineage 設計是重要參考。citeturn12view0

### 2.4 資料品質測試與結構驗證
- Great Expectations 提供以「Expectation」為核心的資料品質驗證機制，並強調結構化 schema 驗證能避免上游變更導致下游錯誤，這是企業級資料管線常見的防護思路。citeturn13view0

### 2.5 多來源資料治理與可插拔架構
- OpenBB ODP 強調可整合專有/授權/公共資料來源並以「connect once, consume everywhere」方式提供多界面使用，顯示成熟開源平台採用「多來源、統一介面」的資料治理方向。citeturn19view1
- ODP 的 CLI 文件也展示了「同一指令可切換多個 provider」與「預設 provider/優先順序清單」的治理方式，這反映了企業級常見的 provider 控制與可替換策略。citeturn19view2

### 2.6 市場資料的 corporate actions / normalization
- QuantConnect 明確說明 data normalization 會將拆股、配息等 corporate actions 調整進歷史價格，使價格曲線一致；這是市場資料品質處理的成熟做法。citeturn18view1
- QuantConnect 亦提供 corporate actions 的長期追蹤資料集（拆股、配息、下市、改名等），顯示企業級市場資料處理需要完整 corporate actions 證據鏈。citeturn18view2

### 2.7 估值分析方法論（特別關於估值）
- DCF 估值的核心是「資產價值＝未來現金流的現值」，並區分 equity valuation 與 firm valuation。citeturn10view0
- DCF 估值必須「現金流與折現率一致」，否則會造成系統性高估或低估。citeturn10view0
- 終值的穩定成長率（stable growth rate）必須低於整體經濟成長率，且不能高於折現率，否則估值邏輯不成立。citeturn11view0

## 3. 本專案現況（依 `fundamental-impl.md`）

### 3.1 已具備的企業級趨勢
- 清晰分層：`application/domain/infrastructure/interface` 分層，並以 ports 注入依賴。
- 財報與參數皆採 `TraceableField` 與 provenance；計算引擎使用 deterministic DAG，具可追溯性。
- XBRL 擷取具 rate limiter + retry/backoff；市場資料具 multi-provider + fallback；估值有 time-alignment guard。
- 計算結果以 artifact 形式保存，支援 replay 與審計。

以上特徵顯示系統已朝「可追溯、可審計、可擴展」方向演進，與企業級系統核心特性一致（此為內部觀察）。

### 3.2 主要風險與缺口（對照外部基準）

**P0（高）**
1. **XBRL 財報未納入 DQC/標準驗證流程**
   - 企業級流程通常需要明確的 XBRL 資料品質驗證（DQC 規則或 Arelle 驗證）。目前流程缺少此環節，可能導致錯誤財報數據進入估值。citeturn14view1turn16view0

2. **估值審計缺少「成長率上限」與「現金流/折現率一致性」硬性約束**
   - DCF 的 stable growth rate 需低於經濟成長且不可高於折現率，且折現率必須匹配現金流類型。若缺少此類約束，估值結果易出現結構性偏差。citeturn10view0turn11view0

**P1（中）**
3. **血緣/作業級 lineage 尚未標準化**
   - 目前已有欄位級 provenance，但缺少 dataset/job/run 層級的 lineage 事件；若需達到企業級審計與變更影響分析，建議採用 OpenLineage 標準或同級做法。citeturn12view0

4. **市場資料 corporate actions / normalization 明確性不足**
   - 成熟平台會把拆股、配息等 corporate actions 系統性整合入價格資料，並提供調整模式。若缺少此處理，估值輸入（如 beta、歷史波動）可能失真。citeturn18view1turn18view2

5. **資料品質測試缺少可持續機制**
   - 企業級管線常利用資料品質框架持續做 schema/欄位驗證並輸出可視化報告，避免上游變更破壞下游模型。citeturn13view0

**P2（中/低）**
6. **Provider 治理與可插拔規範不足**
   - 成熟開源平台對 provider 選擇、優先順序與配置有明確機制，能避免單一資料源失效。建議借鑑類似「多 provider 可切換 + 預設優先級」治理方式。citeturn19view2

7. **資料採集合規記錄與 User-Agent 管控未明確化**
   - SEC EDGAR 對 request rate 和 User-Agent 有要求，企業級系統通常需保留合規證據與監控。citeturn7view0

### 3.3 專案內部結構性風險（非外部基準）
- `subgraph.py` 反向依賴 workflow nodes，導致跨層耦合，增加維護與演進成本。
- `run_model_selection_use_case` 可能回傳 `goto="clarifying"`，但 subgraph builder 未宣告該節點，存在路由斷裂風險。
- Human-in-the-loop approval gate 在 spec 中存在，但未在流程實作中落地，可能與合規與模型風控要求不一致。

## 4. 企業級成熟度評估（基於以上基準的推論）

- **資料採集層**：中上（具 retry/rate-limit；但需補合規證據與 User-Agent 管控）。citeturn7view0
- **財報品質層**：中等（未整合 DQC/Arelle 驗證）。citeturn14view1turn16view0
- **市場資料治理**：中等（多 provider 已有，但 corporate actions/normalization 規範不明）。citeturn18view1turn18view2turn19view2
- **估值方法論**：中上（架構合理，但需補穩定成長與一致性硬性約束）。citeturn10view0turn11view0
- **血緣/審計**：中等（欄位 provenance 已有，但欠作業級 lineage 標準）。citeturn12view0
- **資料品質監控**：中等（缺少持續驗證與文件化機制）。citeturn13view0

**結論（推論）**：目前系統已朝企業級方向演進，但仍屬「企業級前期/準企業級」狀態；若補齊 DQC 驗證、lineage 標準化、corporate actions 正規化與估值 guardrails，將可接近企業級成熟度。citeturn10view0turn11view0turn12view0turn13view0turn14view1turn16view0turn18view1turn18view2

## 5. 調整方向與建議（優先級）

**P0（立即）**
1. 在財報 ingest 後加入 DQC/Arelle 驗證步驟，並把驗證結果納入 artifact（含 rule id、錯誤訊息）。citeturn14view1turn16view0
2. 在 audit policy 中加入：stable growth rate 上限、折現率與現金流一致性檢查，並強制 fail-fast。citeturn10view0turn11view0

**P1（短期）**
3. 加入 OpenLineage 事件輸出（job/run/dataset），將 ingestion → transformation → valuation 串成 lineage。citeturn12view0
4. 導入資料品質測試框架（例如 GX），對 market data、forward signals、估值參數做 schema/範圍驗證與可視化報告。citeturn13view0
5. 明確定義 corporate actions 與 normalization 處理規範（拆股、配息、退市），並在 market data service 中固化行為。citeturn18view1turn18view2

**P2（中期）**
6. 建立 provider 治理層：定義「預設 provider/優先順序」與「來源切換策略」的配置規範，降低單一供應商風險。citeturn19view2
7. 強化合規與監控：對 EDGAR 抓取建立 User-Agent 宣告、速率與失敗記錄的可審計 log。citeturn7view0

## 6. 建議的落地路線（90 天示意）
1. **第 0-30 天**：接入 DQC/Arelle 驗證；新增估值 audit guardrails；修正 workflow 路由斷裂。
2. **第 31-60 天**：導入 OpenLineage 事件；建立 market data schema 驗證（GX）；補 corporate actions/normalization 規範。
3. **第 61-90 天**：provider 治理層與配置化策略；補齊合規監控與報表輸出。

---

### 附註
- 外部基準僅用於「是否朝企業級方向」的驗證與對照，未代表唯一標準；評估結論屬推論。
