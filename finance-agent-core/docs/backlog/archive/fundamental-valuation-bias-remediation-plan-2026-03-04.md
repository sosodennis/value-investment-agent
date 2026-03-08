# Fundamental Valuation Bias Remediation Plan (AAPL/NVDA) - 2026-03-04

## Requirement Breakdown

1. 目標
- 在保留 DCF 計算圖與 `forward_signal direction (up/down)` 前提下，修正 AAPL/NVDA 類案例的系統性低估。
- 主要修正層為「參數化與政策層」，非公式層。

2. 成功標準
- 同一組 input signals 下，可解釋 `raw assumptions -> final params -> intrinsic value`。
- 指定 replay cohort（AAPL/NVDA/MSFT/GOOGL）估值偏差顯著改善。
- 上線後可監控漂移、可快速回退。

3. 已確認約束（User Confirmed）
- 不走 feature flag，直接上線。
- 接受新增最小市場資料欄位；缺失時 deterministic fallback，不中止估值。
- `source_type` 新值命名採用 `xbrl_auto`。

4. Rollout 決策（Planner 決定）
- 採「雙層 gate」：
  - Pre-ship hard gate：指定 mega-cap cohort 必須達標（AAPL/NVDA/MSFT/GOOGL）。
  - Pre-ship broad gate：full-universe backtest 不劣化（至少不退步）。
- 上線後 24h 監控估值漂移與 fallback rate；異常即回退 policy/artifact 版本。

5. Out of Scope
- 不重構整個 SEC text/XBRL signal 抽取管線。
- 不做即時線上自動再訓練。
- 不做前端版面改造（僅必要 parser/顯示兼容修正）。
- 不引入第二層外部 LT growth provider（本輪先不做）。

## Technical Objectives and Strategy

1. Cost of Capital 修正
- 移除「MRP 永遠固定 5%」單一路徑，改為可配置/可追溯 fallback ladder。
- 保持既有 deterministic fallback，並將來源與 fallback 理由寫入 assumptions/metadata。

2. Growth Regime 修正
- 降低 `mature_stable` 對歷史均值的過高權重，增加 market consensus 權重。
- 保留無資料時的歷史/預設 fallback。

3. Forward Signal Source Semantics 修正
- 將 XBRL 自動產生信號 `source_type` 由 `manual` 拆分為 `xbrl_auto`。
- 後端 policy 合約、前端 parser 顯示與測試同步兼容。

4. Observability / Governance
- 擴充 completion/assumption breakdown 的參數來源可見性。
- 保留快速回退點（policy 版本、artifact 版本）。

## Involved Files

1. Policy/Parameterization
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/shared/capm_market_defaults_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/growth_assumption_policy.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/growth_blend_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/forward_signal_contracts.py`

2. Signal Producer
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/forward_signals.py`

3. Application Logging/Assumptions
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_use_case.py`
- `finance-agent-core/src/agents/fundamental/application/services/valuation_assumption_breakdown_service.py`

4. Frontend Compatibility Check
- `frontend/src/types/agents/artifact-parsers.ts`
- `frontend/src/components/agent-outputs/FundamentalAnalysisOutput.tsx`

5. Tests
- `finance-agent-core/tests/test_sec_xbrl_forward_signals.py`
- `finance-agent-core/tests/test_sec_text_forward_signals.py`
- `finance-agent-core/tests/test_forward_signal_policy.py`
- (必要時) frontend parser/output tests

## Execution Slices (Agent Refactor Executor)

1. S0 (small): 文檔落地
- 產出本文件。
- Gate: 文件存在、內容包含 confirmed constraints 與 rollout 決策。

2. S1 (small): `source_type=xbrl_auto` 語義切分
- 修改 XBRL forward signal producer、policy source contract、相關測試。
- 檢查前端 parser/顯示是否需改動；若不需，補充驗證證據。
- Gate: 後端與前端相關測試全綠。

3. S2 (medium): CAPM/WACC fallback ladder
- 調整 MRP 來源策略（非硬編碼單一路徑），保留 deterministic fallback。
- assumptions 中清楚記錄「來源/回退」。
- Gate: 單元測試 + 估值流程回歸測試。

4. S3 (medium): Growth blend reweight
- 調整 mature profile 權重，降低歷史均值對估值的壓制。
- 不變更 DCF graph 公式。
- Gate: 成長序列與估值回歸測試。

5. S4 (small): Replay + Rollout gate
- 先跑指定 cohort，再跑 broad backtest。
- Gate: cohort 改善 + broad 不劣化；不達標不發布。

## Risk/Dependency Assessment

1. 估值過度校正風險
- 調高成長或降低折現率可能導致另一批公司高估。
- 控制：cohort + broad 雙 gate。

2. 資料缺失風險
- 新欄位缺失時可能觸發 fallback。
- 控制：保留 deterministic fallback 並明確記錄。

3. 相容性風險
- `xbrl_auto` 可能影響前端顯示或 parser。
- 控制：前端相依檢查與測試回歸。

4. 直接上線風險
- 無 feature flag。
- 控制：版本化回退 + 24h 漂移監控。

## Validation and Rollout Gates

1. Gate 1: Unit/Contract
- source_type 合約、growth blend、CAPM fallback 測試全綠。

2. Gate 2: Integration
- fundamental valuation pipeline 回歸全綠。

3. Gate 3: Cohort Replay
- AAPL/NVDA/MSFT/GOOGL 指標達標。

4. Gate 4: Broad Backtest
- 全體不劣化（至少 key error metrics 不退步）。

5. Gate 5: Post-Deploy 24h
- 監控 `valuation_drift`, `fallback_rate`, `degrade_reasons`，異常立即回退。

## Assumptions / Open Questions

1. KPI 以「估值偏差改善」為主，方向勝率為次要觀察。
2. Full-universe backtest 的資料集可重現且可在交付窗口內完成。
3. 前端目前對 forward signal `source_type` 不做白名單限制（需實測驗證）。
