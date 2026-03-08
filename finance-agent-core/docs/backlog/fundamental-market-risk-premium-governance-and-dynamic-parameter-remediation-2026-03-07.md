# Fundamental MRP Governance and Dynamic Parameter Remediation (2026-03-07)

## Architecture Standard Enforcer Pre-Check

### Findings

1. `P1` `market_risk_premium` 目前可由 `market_snapshot` 直接覆蓋，存在被當作單票調價旋鈕的風險（違反市場級參數治理目標）。
- Evidence:
  - `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/shared/capm_market_defaults_service.py:38`
  - `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/shared/capm_market_defaults_service.py:46`
- Rule mapping:
  - Layer rule `2.domain`: deterministic policy應可審計且不混入臨時調價。
  - Logging/state rule `8`: 參數來源需機器可讀與可追溯。

2. `P2` 現有 backtest 的 consensus gap 覆蓋不足，難以作為動態參數調整的 release gate。
- Evidence:
  - 最新 backtest summary `consensus_gap_distribution.available_count=0`
  - `finance-agent-core/tests/fixtures/fundamental_backtest_cases.json` 尚未覆蓋 DCF cohort（AAPL/NVDA 等）。
- Rule mapping:
  - Runtime/type rule `5`: 變更需有可驗證邊界；目前校準驗證資料不足。

3. `P2` `long_run_growth_anchor` 的 stale 規則受 cadence guardrail 放寬，實際閾值可能高於預設，容易造成認知偏差。
- Evidence:
  - `finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py:30`
  - `finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py:497`
- Rule mapping:
  - Logging quality `8`: 需要更明確、可讀的政策來源與生效閾值揭露。

### Assumptions/Open Questions

1. 本輪優先修復 `MRP 市場級治理 + DCF 動態參數對稱性`，不改 DCF graph 公式。
2. 直接上線、無 feature flag（已確認）。

### Applied Changes

1. 無（此段為 pre-check）。

### Validation

1. 已完成 log replay 驗證（NVDA/AAPL）均 `intrinsic_delta=0.0`，問題屬參數策略而非 replay drift。

## Requirement Breakdown

1. 目標
- 確立 `market_risk_premium` 僅作「市場級輸入」，禁止單一 ticker 透過 snapshot 覆蓋。
- 將估值偏差修復重心放到動態參數（growth/margin/base guardrail/consensus decay），不是調 CAPM 市場參數。

2. 成功標準
- 可追溯輸出 `MRP source + policy decision`（含 ignored override 記錄）。
- AAPL/NVDA replay 中能清楚區分：`base_raw -> base_guarded -> forward_adjusted` 對估值的影響。
- backtest 可量化監控 `consensus_gap_distribution`（不再是 0 coverage）。

3. 已確認約束
- 不走 feature flag，直接上線。
- 保留既有 logging/assumption/snapshot traceability。
- 不改 DCF 計算圖核心公式。

4. Out of Scope（本輪不做）
- 不引入付費外部估值供應商。
- 不做前端互動改版（僅欄位擴充）。
- 不做在線自動再訓練。

## Technical Objectives and Strategy

1. `Market Input Governance`
- 在 CAPM defaults 層落實「market-level MRP only」政策。
- 若 snapshot 帶有 `market_risk_premium`，記錄 `ignored_by_policy`，不進入估值計算。

2. `Dynamic Parameter Remediation`
- 將 `dcf_growth` 與 `dcf_standard` 的 base guardrail 以 profile 方式對稱治理，避免一熱一冷。
- `forward_signal_calibration` 保留為二階調整，不承擔基底糾偏。

3. `Validation System`
- 用 replay + DCF cohort backtest 驗證調整前後差異。
- 建立 `consensus_gap_distribution` 最小樣本門檻，未達標不得作校準結論。

## Involved Files

1. MRP policy path
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/shared/capm_market_defaults_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/saas/saas.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/bank/bank.py`

2. DCF dynamic guardrail path
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/dcf/dcf_variant_payload_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/base_assumption_guardrail_policy.py`

3. Validation
- `finance-agent-core/scripts/replay_fundamental_valuation.py`
- `finance-agent-core/scripts/run_fundamental_backtest.py`
- `finance-agent-core/tests/test_param_builder_canonical_reports.py`

## Detailed Per-File Plan

1. `capm_market_defaults_service.py`
- 新增 `allow_market_snapshot_mrp` 控制（預設關閉）。
- 關閉時即使 snapshot 提供 MRP 也不採用，並寫入 assumptions：`ignored by policy`。

2. `saas.py` / `bank.py`
- 呼叫 CAPM defaults 時顯式傳入 `allow_market_snapshot_mrp=False`，避免隱式行為漂移。

3. `test_param_builder_canonical_reports.py`
- 更新既有「snapshot MRP 可覆蓋」測試，改為驗證「被忽略且保留審計訊息」。

4. 下一階段（本文件記錄，不在本 slice）
- 擴充 DCF cohort backtest dataset，啟用 consensus gap coverage gate。
- 收斂 `dcf_growth`/`dcf_standard` guardrail profile 的對稱性調參。

## Risk/Dependency Assessment

1. 功能風險
- 禁用 snapshot MRP 後，個別案例可能短期偏離既有輸出（屬預期行為變更）。

2. 數據風險
- 若 DCF cohort 仍不足，動態參數調整可能過擬合。

3. 依賴
- replay snapshot artifact 可用。
- backtest dataset 持續補齊 DCF 票池。

4. 回退策略
- 單點回退：還原 `allow_market_snapshot_mrp` policy 開關。
- 發布回退：回退至上一版 artifact + policy 組合。

## Validation and Rollout Gates

1. Gate 1（Unit）
- CAPM default 路徑測試：snapshot MRP ignore/accept 分支可測。

2. Gate 2（Integration）
- AAPL/NVDA replay 成功且無 drift。

3. Gate 3（Regression）
- 受影響參數建構測試與 orchestrator logging 測試綠燈。

4. Gate 4（Offline Monitoring）
- `consensus_gap_distribution.available_count` 達最小門檻後才接受調參結論。

## Execution Slices (agent-refactor-executor)

1. `S1` (`medium`): MRP 市場級治理落地
- Objective: 禁止 snapshot 覆蓋 MRP，補審計訊息。
- Files: CAPM defaults + saas/bank builders + param builder tests。
- Validation: targeted pytest + replay smoke。

2. `S2` (`medium`): DCF cohort backtest coverage 補齊
- Objective: 讓 consensus gap 指標可用。
- Files: backtest fixtures/report gates。

3. `S3` (`medium`): dcf_standard / dcf_growth guardrail 對稱化
- Objective: 降低 AAPL/NVDA 一冷一熱偏差。

4. `S4` (`small`): observability 補強
- Objective: 前後端 diagnostics 欄位完整對齊（不改交互）。
