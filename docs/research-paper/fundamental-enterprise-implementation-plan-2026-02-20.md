# `finance-agent-core/src/agents/fundamental` Implementation Plan（交叉驗證修訂版）

日期：2026-02-20
目標：將現有 Fundamental Agent 升級為可追溯、可治理、可擴充的企業級動態估值系統（市場資料 + 動態假設 + 相關性蒙地卡羅）。

## 1. 目標與範圍

## In Scope
- 導入 `MarketDataClient`（含單位清洗、重試、快取、來源標記）。
- 參數建構升級（最新股數策略、動態 growth blender、REIT/Bank 可配置假設）。
- 估值圖升級（移除硬編碼，接入動態輸入）。
- 蒙地卡羅引擎升級（相關性矩陣、截斷、可重現、收斂診斷）。
- 與現有 LangGraph 流程整合，輸出 P5/P50/P95。

## Out of Scope（本期不做）
- 全量多資料供應商商業化採購與法務流程。
- 前端完整視覺化重設計（僅提供必要輸出欄位）。

---

## 2. 交付里程碑與時程

## Milestone A（第 1 週）市場資料基礎設施
- 新增 `finance-agent-core/src/agents/fundamental/data/clients/market_data.py`
- 新增對應 `port` 與 mapper
- 完成資料正規化、錯誤分類、快取與觀測性

## Milestone B（第 2 週）參數層與假設層升級
- 升級 `param_builder.py` 與 `assumptions.py`
- 導入動態 growth blender、可配置 `maintenance_capex_ratio`
- 完成 shares outstanding 新策略

## Milestone C（第 3-4 週）模型圖與蒙地卡羅升級
- 升級 `bank_ddm.py`、`reit_ffo.py`、`saas_fcff.py`（必要節點）
- 新增 Monte Carlo runner（相關性 + 截斷 + 診斷）
- 串接 orchestrator 與輸出 contract

## Milestone D（第 5 週）整合、回測、文件化
- 回測與回歸測試
- 文件與 runbook 完成

---

## 3. 詳細工作分解（WBS）

## W1. Market Data Client（穩健接入）
涉及檔案：
- `finance-agent-core/src/agents/fundamental/data/clients/market_data.py`（new）
- `finance-agent-core/src/agents/fundamental/data/ports.py`
- `finance-agent-core/src/agents/fundamental/data/mappers.py`

任務：
1. 定義 `MarketSnapshot` 結構（`current_price`, `shares_outstanding`, `beta`, `risk_free_rate`, `consensus_growth_rate`, `target_mean_price`, `as_of`, `provider`）。
2. 實作單位清洗（例如利率 `4.25 -> 0.0425`）。
3. 實作錯誤分級（429/timeout/schema-missing）與 retry/backoff。
4. 加入快取（短 TTL），避免高頻打 API。
5. 在 provenance 留下 `source/provider/as_of/latency_ms`。

驗收標準：
- 可穩定輸出統一 schema。
- 缺欄位時不崩潰，回傳明確 `missing_fields`。
- 監控指標可見成功率/延遲/錯誤碼分布。

## W2. Param Builder 升級（移除脆弱估算）
涉及檔案：
- `finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py`（必要時）

任務：
1. shares outstanding 優先序：
   - `market_data.shares_outstanding`（首選）
   - `XBRL dei:EntityCommonStockSharesOutstanding`（備用）
2. 明確禁止 `market_cap / current_price` 反推邏輯。
3. 對 shares 來源寫入 provenance（live vs filing）。
4. 若兩來源偏差過大，加入 warning（不直接覆寫/可考慮拋出異常）。

驗收標準：
- 每筆估值都可追溯 shares 來源。
- 無反推股數路徑殘留。

## W3. Assumptions 引擎升級（動態權重）
涉及檔案：
- `finance-agent-core/src/agents/fundamental/domain/valuation/assumptions.py`

任務：
1. 新增 `GrowthBlender`：
   - 輸入：歷史 CAGR、共識 growth、可選新聞微調
   - 輸出：`blended_growth` + 權重明細 + 說明
2. 權重改為 context-aware（依波動、產業、成長階段調整）。
3. 高成長均值回歸改為可配置 guardrail（非硬編碼常數）。
4. 保留 `ManualProvenance` 與審核訊息。

驗收標準：
- 權重、輸入來源、最終值完整可追溯。
- 在不同情境輸入下，權重會產生可解釋變化。

## W4. 行業模型修正（Bank/REIT）
涉及檔案：
- `finance-agent-core/src/agents/fundamental/domain/valuation/engine/graphs/bank_ddm.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/engine/graphs/reit_ffo.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/registry.py`

任務：
1. Bank：移除硬編碼 COE，改為策略化輸入（先支援 CAPM；保留擴充接口）。
2. REIT：從 FFO 延伸至 AFFO 近似，`maintenance_capex_ratio` 設為可配置參數（預設 0.8）。
3. 所有新假設寫入 traceable inputs。

驗收標準：
- `bank_ddm` 不再依賴固定 COE。
- `reit_ffo` 可接受可配置維持性資本支出假設。

## W5. Monte Carlo Enterprise Runner（相關性 + 風控）
涉及檔案：
- `finance-agent-core/src/agents/fundamental/domain/valuation/engine/core.py`（必要擴充）
- `finance-agent-core/src/agents/fundamental/domain/valuation/engine/monte_carlo.py`（new）
- `finance-agent-core/src/agents/fundamental/application/orchestrator.py`

任務：
1. 新增分佈物件（normal/triangular/uniform，含 `min_bound/max_bound`）。
2. 支援相關性矩陣抽樣（MVP 先支援 multivariate normal）。
3. correlation -> covariance 轉換與 PSD 檢查。
4. 加入 seed 管理、收斂診斷（分位數穩定性）、失敗保護。
5. 輸出 `P5/P50/P95`、均值、樣本數、seed、假設版本。

驗收標準：
- 可重現（固定 seed 重跑結果一致）。
- 不產生經濟不合理極值（有截斷）。
- 診斷訊號可判斷是否需增加迭代。

## W6. Contract、API 整合
涉及檔案：
- `finance-agent-core/src/agents/fundamental/interface/contracts.py`
- `finance-agent-core/src/agents/fundamental/interface/mappers.py`
- `finance-agent-core/src/agents/fundamental/application/view_models.py`

任務：
1. 擴充輸出欄位：`distribution_summary`, `assumption_breakdown`, `data_freshness`。

驗收標準：
- 使用者可看見關鍵假設與分佈結果。

---

## 4. 測試策略

## Unit Tests
- `market_data`：單位清洗、空值、防呆、429 retry。
- `GrowthBlender`：情境權重、均值回歸 guardrail。
- `monte_carlo`：相關矩陣合法性、截斷、seed 重現。

## Integration Tests
- 從 `param_builder -> graph -> monte_carlo -> contract` 端到端。
- 針對 `saas`, `bank`, `reit_ffo` 各跑一組 golden cases。

## Regression & Backtest
- 取歷史窗口對比舊版估值偏差與穩定性。
- 記錄新舊模型在 P50 與區間寬度的變化。

---

## 5. Definition of Done（DoD）

1. 無硬編碼 COE 與硬寫 growth 權重。
2. shares outstanding 無 `market_cap/price` 反推路徑。
3. Monte Carlo 支援相關性、截斷、seed 重現、P5/P50/P95。
4. 所有新增假設都有 provenance 與 audit 訊息。
5. 主要模型（SaaS/Bank/REIT）有端到端測試通過。
6. 文件與介面契約更新完成（以前置開發版本為準）。

---

## 6. TODO Enhancement（延後實作）

以下功能依你的要求放到最後，不納入本期主交付：

- `TODO (Enhancement)`：當估值流程 fallback 到「行業均值」時，系統需自動標記為高風險假設，並觸發人工審批（HITL gate）；不得默默進入最終計算。
- `TODO (Enhancement)`：HITL 相關整合（審批頁欄位、審批節點 gating、人工覆核 workflow）延後到 enhancement 階段統一實作。
