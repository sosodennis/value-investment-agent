# Fundamental Valuation Sensitivity Requirement Breakdown (2026-03-05)

## Requirement Breakdown

1. 目標
- 在不更改既有 DCF 計算圖公式前提下，引入可解釋的敏感度分析能力，補足目前僅有 Monte Carlo 分佈（P5/P50/P95）但缺乏 driver attribution 的缺口。
- 保留主估值 deterministic 路徑穩定性，敏感度為「附加診斷層」。

2. 成功標準
- 同一次估值輸出中，能追溯 `base_case -> shocked_case -> delta`。
- 可在 AAPL/NVDA 等案例中清楚回答「哪些參數導致估值差距」。
- 前端能直接顯示 sensitivity summary，不需人工讀 logs。
- sensitivity 計算失敗時不影響主估值結果（可降級）。

3. 已確認約束（Confirmed）
- 直接上線，無 feature flag。
- 沿用現有 logging / assumption breakdown / metadata traceability 體系。
- 不改 DCF graph 公式。
- 前端可做 parser 與必要顯示擴充（不做整體版面重構）。

4. 關鍵決策（本輪定案）
- 先做 DCF 模型（`dcf_standard`, `dcf_growth`）的 sensitivity v1。
- 先做 one-way shocks（單因子敏感度），不在本輪實作 2D heatmap 全格點。
- 明確記錄「不同估值模型敏感度維度不同」，後續分模型擴展而非強行共用 DCF 維度。

5. Out of Scope（本輪不做）
- 不將 sensitivity v1 擴到 `bank/reit/multiples`。
- 不做 2D heatmap 全格點（例如 `wacc x terminal_growth` 全網格）。
- 不做即時線上自動再訓練或新 pipeline 強耦合改造。
- 不引入第二層外部 provider（LSEG/FactSet/Bloomberg）。

## Technical Objectives and Strategy

1. Domain 目標
- 新增 DCF sensitivity 能力層（可重用 service），輸入 base context + shock policy，輸出標準化 sensitivity artifact。

2. Policy 目標
- 以 one-way shocks 為 v1：`wacc`、`terminal_growth`、`growth_level`、`margin_level`。
- 所有 shock 需有邊界與 guard（特別是 `terminal_growth < wacc`）。

3. Application 目標
- 將 sensitivity 寫入：
  - `details`（完整 cases）
  - `valuation_diagnostics`（摘要）
  - `assumption_breakdown`（可解釋欄位）
  - completion snapshot logs（監控欄位）

4. Interface / Frontend 目標
- parser 擴充 sensitivity schema。
- UI 新增 sensitivity 區塊（表格/卡片）展示 top drivers 與 shock 結果。

5. Governance 目標
- sensitivity 失敗採 warning + skip（主估值不 fail）。
- 版本化 shock policy，支持快速回退。

## Involved Files

1. Core Calculation / Diagnostics
- `finance-agent-core/src/agents/fundamental/domain/valuation/calculators/dcf_variant_calculator.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/calculators/dcf_variant_result_service.py`
- `finance-agent-core/src/agents/fundamental/application/services/valuation_update_service.py`
- `finance-agent-core/src/agents/fundamental/application/services/valuation_assumption_breakdown_service.py`
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_flow.py`

2. Frontend Contract / UI
- `frontend/src/types/agents/fundamental-preview-parser.ts`
- `frontend/src/components/agent-outputs/FundamentalAnalysisOutput.tsx`

3. Proposed New Files
- `finance-agent-core/src/agents/fundamental/domain/valuation/calculators/dcf_variant_sensitivity_contracts.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/calculators/dcf_variant_sensitivity_service.py`
- `finance-agent-core/tests/test_dcf_variant_sensitivity_service.py`
- `finance-agent-core/tests/fixtures/dcf_variant_sensitivity_cases.json`

## Detailed Per-File Plan

1. `dcf_variant_sensitivity_contracts.py` (new)
- 定義 sensitivity artifact：
  - `scenario_id`
  - `shock_dimension`
  - `shock_value_bp`
  - `intrinsic_value`
  - `delta_pct_vs_base`
  - `guard_applied`

2. `dcf_variant_sensitivity_service.py` (new)
- 實作 one-way shock runner（v1）：
  - `wacc`: `±50bp`, `±100bp`
  - `terminal_growth`: `±25bp`, `±50bp`
  - `growth_level`: `±100bp`, `±200bp`
  - `margin_level`: `±100bp`, `±200bp`
- 實作 bounds/guard 與 deterministic fallback。

3. `dcf_variant_calculator.py`
- base valuation 後串接 sensitivity service。
- 將輸出寫入 `details["sensitivity_summary"]` 與 `details["sensitivity_cases"]`。
- sensitivity 發生錯誤時：warning + continue。

4. `dcf_variant_result_service.py`
- 增加 helper 封裝 sensitivity 所需 base context，避免重複計算與重複 mapping。

5. `valuation_update_service.py`
- 將 sensitivity 摘要映射至 `preview["valuation_diagnostics"]`。

6. `valuation_assumption_breakdown_service.py`
- 在 assumption breakdown 增加 `sensitivity` 區塊：
  - `enabled`
  - `scenario_count`
  - `top_drivers`

7. `run_valuation_flow.py`
- completion snapshot 補欄位：
  - `sensitivity_enabled`
  - `sensitivity_scenario_count`
  - `sensitivity_max_upside_delta_pct`
  - `sensitivity_max_downside_delta_pct`

8. `fundamental-preview-parser.ts`
- 新增 sensitivity type + parser（欄位 optional，維持 backward compatibility）。

9. `FundamentalAnalysisOutput.tsx`
- 新增 sensitivity 展示模組（v1 表格形式，先重資訊可讀性）。

10. 測試
- 新增 sensitivity 單元測試（邏輯、邊界、guard、fallback）。
- 回歸 application 與 frontend parser/UI 測試。

## Risk/Dependency Assessment

1. 計算成本風險
- shock 場景數增加會拉高延遲。
- 控制：v1 限定 one-way shocks + 固定小場景集。

2. 數值約束風險
- `terminal_growth` 接近或高於 `wacc` 導致不穩定。
- 控制：hard guard + `guard_applied` 記錄。

3. 解釋一致性風險
- 使用者可能把 Monte Carlo distribution 與 sensitivity 混淆。
- 控制：欄位命名與 UI 文案分離（stochastic vs deterministic）。

4. 直接上線風險
- 無 feature flag。
- 控制：pre-ship replay gate + 24h 監控 + 版本回退。

5. 依賴風險
- v1 不依賴新資料 pipeline；但後續治理仍建議納入定期 replay 報表。

## Validation and Rollout Gates

1. Gate 1: Unit/Contract
- sensitivity schema、shock mapping、guard、fallback 測試全綠。

2. Gate 2: Integration
- fundamental valuation pipeline 回歸全綠；主估值結果不受負面影響。

3. Gate 3: Replay Cohort
- AAPL/NVDA/MSFT/GOOGL 可輸出可解釋 sensitivity driver。

4. Gate 4: Performance
- 估值端到端延遲增幅在門檻內（建議 `<20%`）。

5. Gate 5: Post-Deploy 24h
- 監控 `sensitivity_enabled_rate`、`sensitivity_error_rate`、`valuation_drift`。
- 異常即回退 sensitivity policy 版本。

## Assumptions / Open Questions

1. 為什麼 v1 先限 DCF？
- 不是其他模型不適用，而是「敏感度維度不同」：
  - DCF：`wacc/growth/margin/terminal_growth`
  - Multiples：`multiple/comps dispersion`
  - Bank DDM：`cost_of_equity/payout/growth/capital`
  - REIT：`FFO multiple/maintenance capex/leverage`
- 若硬套同一維度，會出現可算但解釋失真。

2. 為什麼 v1 不做 2D heatmap 全格點？
- 不是技術做不到，主要是第一版成本/風險不對稱：
  - 計算量與延遲增加
  - 約束處理（`g < wacc`）更複雜
  - 前端與使用者解讀負擔上升
- v1 先用 one-way shocks 取得高性價比可解釋性。

3. 後續規劃（已登記）
- Phase 2：擴展 model-specific sensitivity（bank/reit/multiples 各自維度）。
- Phase 3：新增 2D heatmap 全格點（優先 `wacc x terminal_growth`）與視覺化。
