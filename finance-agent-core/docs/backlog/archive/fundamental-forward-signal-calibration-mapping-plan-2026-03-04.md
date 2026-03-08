# Fundamental Forward Signal Calibration Mapping Plan (2026-03-04)

## Requirement Breakdown

### Objective
在保留 `forward_signal direction`（`up/down`）前提下，改成「回測校準的幅度映射函數」決定扣分/加分力度，降低 NVDA 這類高增長公司被過度扣分的機率。

### Success Criteria
1. 同一組 signals 下，新 policy 可輸出可解釋的 `raw_bp -> calibrated_bp`。
2. 估值誤差在離線回放可量化改善（或至少不劣化）。
3. 上線後可監控漂移並可快速回退。

### Constraints
1. 不走 feature flag，直接上線。
2. 沿用現有 logging/assumption 可追溯體系。
3. 不改 DCF 計算圖公式。

### Out of Scope
1. 不改 `up/down` 方向判定邏輯（只校準幅度）。
2. 不引入第二層外部長期增長 provider（LSEG/FactSet/Bloomberg）。
3. 不重構整個 SEC text/XBRL signal 抽取管線。
4. 不做前端版面改造，只擴充可讀欄位。
5. 不做即時線上自動再訓練（只做離線產物更新與版本發布）。
6. 不做 feature flag 漸進發布。

## Technical Objectives and Strategy

1. `Domain`：新增「幅度校準能力」層，輸入 raw signal features，輸出 calibrated basis points，並保證單調與有界。
2. `Policy`：在現有 `apply_forward_signal_policy` 內保留 direction，替換幅度計算為 calibration mapping；保留無 mapping 時 deterministic fallback。
3. `Backtest/Calibration`：新增離線校準流程（dataset build -> walk-forward fit -> report -> mapping artifact）。
4. `Application`：把 `mapping_version`、`raw_vs_calibrated`、`calibration_coverage` 寫入 metadata/log/assumption breakdown。
5. `Governance`：建立固定重訓節奏與可回退版本（mapping artifact versioned）。

## Involved Files

### Existing Policy Core
1. `finance-agent-core/src/agents/fundamental/domain/valuation/policies/forward_signal_contracts.py`
2. `finance-agent-core/src/agents/fundamental/domain/valuation/policies/forward_signal_scoring_service.py`
3. `finance-agent-core/src/agents/fundamental/domain/valuation/policies/forward_signal_policy.py`

### Existing Parameterization, Metadata, and Logging
1. `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/forward_signal_adjustment_service.py`
2. `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/orchestrator.py`
3. `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_use_case.py`
4. `finance-agent-core/src/agents/fundamental/application/services/valuation_assumption_breakdown_service.py`

### Existing Signal Producer (Minimal Standardization Only)
1. `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/forward_signals.py`
2. `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/pipeline_runner.py`

### Existing Backtest Capability (Reuse)
1. `finance-agent-core/src/agents/fundamental/domain/valuation/backtest/contracts.py`
2. `finance-agent-core/src/agents/fundamental/domain/valuation/backtest/runtime_service.py`
3. `finance-agent-core/src/agents/fundamental/domain/valuation/backtest/io_service.py`
4. `finance-agent-core/scripts/run_fundamental_backtest.py`

### Proposed New Files
1. `finance-agent-core/src/agents/fundamental/domain/valuation/calibration/contracts.py`
2. `finance-agent-core/src/agents/fundamental/domain/valuation/calibration/mapping_service.py`
3. `finance-agent-core/src/agents/fundamental/domain/valuation/calibration/fitting_service.py`
4. `finance-agent-core/src/agents/fundamental/domain/valuation/calibration/io_service.py`
5. `finance-agent-core/scripts/run_forward_signal_calibration.py`
6. `finance-agent-core/tests/test_forward_signal_calibration_mapping.py`
7. `finance-agent-core/tests/fixtures/forward_signal_calibration_cases.json`
8. `finance-agent-core/docs/fundamental_forward_signal_calibration_runbook.md`

## Detailed Per-File Plan

1. `forward_signal_contracts.py`
   - 擴充 policy result：新增 `raw_basis_points`、`calibrated_basis_points`、`mapping_version`、`calibration_applied`。
2. `domain/valuation/calibration/contracts.py` (new)
   - 定義 mapping artifact schema（per metric/source/regime 的 monotonic bins 或 piecewise params）。
3. `domain/valuation/calibration/io_service.py` (new)
   - 負責 mapping artifact 讀取、版本與完整性校驗。
4. `domain/valuation/calibration/mapping_service.py` (new)
   - 提供 `map_raw_bp_to_calibrated_bp(...)`；保證單調、可選對稱、有界。
5. `domain/valuation/calibration/fitting_service.py` (new)
   - 離線 fit，輸出 mapping artifact 與訓練報告（coverage/segments）。
6. `forward_signal_scoring_service.py`
   - 將 raw heuristic bp 經 mapping 轉為 calibrated bp，再做 confidence 加權聚合。
7. `forward_signal_policy.py`
   - 注入 calibration 依賴與 fallback path。
8. `forward_signal_adjustment_service.py`
   - assumptions 加入 `raw->calibrated` 摘要；保留現有 series apply 邏輯。
9. `parameterization/orchestrator.py`
   - log fields 加入 `mapping_version`、`calibration_applied`、`coverage_bucket`。
10. `run_valuation_use_case.py`
    - completion log 擴充 calibration metadata，支持事後審計。
11. `valuation_assumption_breakdown_service.py`
    - 對外暴露校準摘要，避免只看到最終 bp。
12. `forward_signals.py`
    - 標準化 source 語義（auto-xbrl 與 true-manual 區分）以支撐分來源映射。
13. `pipeline_runner.py`
    - 補最小必要 feature（例如 textual evidence density）供 calibration segmentation。
14. `backtest/runtime_service.py` + `backtest/io_service.py`
    - 擴充離線評估資料抽取欄位，支持 walk-forward 校準。
15. `scripts/run_forward_signal_calibration.py` (new)
    - 一鍵生成 mapping artifact 與報告；與既有 backtest runner 並存。
16. Tests
    - 更新 `tests/test_forward_signal_policy.py`，新增 calibration mapping/monotonic/fallback 測試。
    - 回歸 `tests/test_fundamental_backtest_runner.py` 與 `tests/test_fundamental_orchestrator_logging.py`。

## Risk/Dependency Assessment

1. 功能風險：calibration 過擬合導致特定 market regime 外失效。
2. 資料風險：樣本不足時 mapping 不穩定，需最小樣本門檻與 fallback。
3. 治理風險：source 語義不乾淨會污染分來源 mapping。
4. 上線風險：無 feature flag，需加強 pre-ship gate 與快速回退。
5. 依賴：需要穩定回放資料集與可重現 backtest pipeline。
6. 回退策略：mapping artifact 版本回退；policy 自動退回 raw heuristic path；必要時整體部署回退。

## Validation and Rollout Gates

1. Gate 1 (Unit/Contract)
   - mapping schema、單調性、邊界、fallback 全綠。
2. Gate 2 (Offline Calibration)
   - walk-forward 報告生成成功，無資料洩漏檢查失敗。
3. Gate 3 (Policy Regression)
   - 既有 forward signal 測試全綠；NVDA 重放中 `raw_bp` 與 `calibrated_bp` 可解釋。
4. Gate 4 (Backtest Improvement)
   - 相對現況在既定指標（例如 valuation error）達標或不劣化；未達標則不發布新 mapping。
5. Gate 5 (Post-Deploy 24h)
   - 監控 `calibration_applied_rate`、`fallback_rate`、`mapping_version`、`valuation_drift`；異常即回退 mapping 版本。

## Operational Cadence (Initial Proposal)

1. Data Build Pipeline
   - 每日執行，產出 calibration dataset（不更新 mapping）。
2. Calibration Pipeline
   - 初期雙週執行一次（資料量不足前不建議週更）。
3. Publish Rule
   - 僅在樣本量達門檻且 Gate 4 通過時發布新 mapping。

### Initial Minimum Sample Guardrail
1. `total_labeled_samples >= 400`
2. 每個核心分桶（`metric x direction x source_type`）`>= 40`
3. 未達門檻：沿用上一版 mapping；若無 mapping 則退回 heuristic。

## Assumptions/Open Questions

1. 校準目標先定為「降低估值偏差」，非「提升方向預測勝率」。
2. mapping 更新節奏初期採雙週，達穩定門檻後再評估改為週更。
3. 本輪接受將 XBRL auto signal 的 `source_type` 自 `manual` 拆分為獨立值，以避免校準失真。
