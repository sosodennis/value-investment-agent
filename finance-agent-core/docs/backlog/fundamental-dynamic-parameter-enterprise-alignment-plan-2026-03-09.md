# Fundamental Dynamic-Parameter Enterprise Alignment Plan (2026-03-09)

## Requirement Breakdown

1. Objective
- 調整 fundamental 動態參數治理，讓估值結果更接近企業級方法：
  - 保持模型自主估值（不是直接輸出外部 target price）。
  - 在 AAPL/MSFT/GOOG/NVDA cohort 下，降低結構性偏保守/偏樂觀漂移。

2. Success Criteria
- 第一階段上線門檻：`|consensus_gap_pct|` cohort median 達 `<=10%~15%`。
- 估值輸出需可審計展示：`raw -> guarded -> calibrated`。
- `dcf_growth` / `dcf_standard` 動態參數不再出現結構性不對稱漂移。

3. Constraints
- 直接上線，無 feature flag。
- 不改 DCF 計算圖核心公式（僅參數 policy/governance 層）。
- 先做後端與 metadata/log 欄位擴充，前端交互不改。

4. Out of Scope
- 不引入付費數據供應商（Bloomberg/FactSet/LSEG）。
- 不做即時線上自動再訓練。
- 不重構整個 SEC/XBRL 提取管線。

## Technical Objectives and Strategy

1. Nominal/Real 口徑治理
- 長期增長（terminal/long-run anchor）統一走 nominal 口徑。
- real anchor 僅作輸入來源之一，不可直接覆蓋 nominal DCF 目標。

2. Variant 對齊治理
- 建立 shared base guardrail profile。
- `dcf_growth`/`dcf_standard` 僅保留必要 delta，避免分叉常數長期漂移。

3. Consensus 品質分層
- 單源 consensus 強制降權（不得高 confidence）。
- 補充 `source_count/analyst_count/age_days/quality_bucket` 到 metadata。

4. Replay 驅動調參
- 固定 cohort（AAPL/MSFT/GOOG/NVDA）做 deterministic replay。
- 每次只調一個參數群組（growth 或 margin 或 reinvestment），避免耦合。

5. 可觀測與回退
- 所有動態調整輸出 `policy_profile_version`、`mapping_version`、`fallback_reason`。
- 失敗可回退 profile artifact，不需要回退計算公式。

## Involved Files

1. Parameter policy core
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/dcf/dcf_variant_payload_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/growth_assumption_policy.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/growth_blend_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/registry_service.py`

2. Market consensus & anchor quality
- `finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/market_data/consensus_anchor_aggregator.py`

3. Forward-signal calibration path
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/forward_signal_calibration_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/forward_signal_scoring_service.py`

4. Observability & assumptions
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/forward_signal_adjustment_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/orchestrator.py`
- `finance-agent-core/src/agents/fundamental/application/services/valuation_assumption_breakdown_service.py`
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_flow.py`

5. Replay/Backtest
- `finance-agent-core/scripts/replay_fundamental_valuation.py`
- `finance-agent-core/scripts/run_fundamental_backtest.py`

## Detailed Per-File Plan

1. `dcf_variant_payload_service.py`
- 引入 shared base profile + variant delta 配置化。
- long-run growth 輸入做 nominal bridge/fallback（保留來源 trace）。
- 每次 guardrail 應輸出 `before/after/reason`。

2. `growth_assumption_policy.py` + `growth_blend_service.py`
- short-term consensus 採衰減納入（3 年窗口，可配置）。
- 10Y DCF 收斂節奏改 8-10 年 fade。
- profile-driven blend 權重（mature/high-growth）替代單一固定權重。

3. `market_data_service.py` + `consensus_anchor_aggregator.py`
- 單源 fallback 強制降 confidence。
- stale threshold 收緊並可觀測化。
- 補充 consensus quality bucket 到 completion metadata。

4. `forward_signal_calibration_service.py` + `forward_signal_scoring_service.py`
- 保留 direction 訊號，僅校準幅度。
- 覆蓋率不足時 fallback raw path，並寫入 fallback reason。

5. `forward_signal_adjustment_service.py` + `orchestrator.py` + `run_valuation_flow.py` + `valuation_assumption_breakdown_service.py`
- 對外統一輸出 `raw/guarded/calibrated` 三段值與版本欄位。
- assumptions/log 統一記錄 `policy_profile_version`、`mapping_version`、`data_quality_flags`。

6. `replay_fundamental_valuation.py` + `run_fundamental_backtest.py`
- 新增 cohort mode 固定輸入集合（AAPL/MSFT/GOOG/NVDA）。
- 報告新增 `delta_by_parameter_group`（growth/margin/reinvestment/terminal）。

## Risk/Dependency Assessment

1. Functional risk
- 過度貼近 consensus 可能弱化模型獨立性。
- 緩解：用 bounded calibration，只校準幅度不改方向。

2. Data risk
- 免費來源易 403/覆蓋不足，造成 consensus quality 波動。
- 緩解：品質分層 + 單源降權 + fallback 明確標記。

3. Migration risk
- variant 對齊可能影響已上線 ticker 行為。
- 緩解：分 slice 小步上線 + cohort regression gate。

4. Dependency
- 需要穩定 replay dataset 與可重現 backtest pipeline。
- 需要現有 artifact schema 可承接新增 metadata 欄位。

5. Rollback
- 優先回退 `policy_profile_version` 或 `mapping_version` artifact。
- 保留 observability 欄位，避免失去診斷能力。

## Validation and Rollout Gates

1. Gate 1: Contract/Unit
- 新欄位 schema、guardrail/calibration 單元測試全綠。

2. Gate 2: Deterministic Replay
- 同 artifact replay 漂移可解釋且可重現。

3. Gate 3: Cohort KPI
- AAPL/MSFT/GOOG/NVDA 的 `|consensus_gap_pct|` median 達 `<=10%~15%`。

4. Gate 4: Non-Regression
- 非目標 ticker 抽樣不可明顯劣化。

5. Gate 5: Post-Deploy 24h
- 監控 `fallback_rate`、`consensus_quality_bucket`、`valuation_drift`。
- 超閾值即回退 profile/mapping 版本。

## Assumptions/Open Questions

1. 已確認：第一階段 KPI 改為 `|gap| <=10%~15%`（cohort median）。
2. 已確認：long-run growth 一律 nominal 口徑；real anchor 僅作來源之一。
3. 已確認：單源 consensus 必降權，不可給高 confidence。
4. 已確認：profile 更新節奏採雙週更，且每次必附 replay report。
