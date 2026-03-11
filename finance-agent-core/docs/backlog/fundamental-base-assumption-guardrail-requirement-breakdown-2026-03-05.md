# Fundamental Base Assumption Guardrail Requirement Breakdown (2026-03-05)

## Requirement Breakdown

1. 目標
- 在不改動既有 DCF 計算圖公式前提下，修正「基底假設過熱」造成的系統性高估。
- 將 `forward_signal_calibration` 明確定位為二階微調層；基底假設校準由新 guardrail 層負責。

2. 成功標準
- 同一組輸入下可追溯 `base_raw -> base_guarded -> forward_adjusted`。
- 估值輸出中 `growth_year1`、`margin_path` 可解釋且可控，避免極端高估常態化。
- 離線回放中估值誤差改善或不劣化，且 `extreme_upside_rate`（例如 `upside > +80%`）下降。
- 上線後可監控 guardrail 命中率、估值漂移與回退。

3. 已確認約束（Confirmed）
- 直接上線，無 feature flag。
- 沿用現有 logging / assumption breakdown / metadata / snapshot traceability。
- 不改 DCF graph 核心數學公式。
- 前端僅新增欄位顯示 `raw/guarded/calibrated`，不改版面交互。

4. 已確認關鍵決策（本輪定案）
- 本輪優先套用 `dcf_growth`；`dcf_standard` 下一輪接入。
- `margin` 長期收斂目標先用內部統計區間（非外部供應商）。
- guardrail 參數更新節奏先採雙週更。
- `forward_signal_calibration` 保留，作為基底 guardrail 之後的幅度微調。

5. Out of Scope（本輪不做）
- 不改 `forward_signal` 的 `up/down` 方向判定邏輯。
- 不引入第二層外部長期增長 provider（LSEG/FactSet/Bloomberg）。
- 不重構 SEC text / XBRL signal 抽取管線。
- 不做前端整體 UI 重設計或互動改版。
- 不做即時線上自動再訓練（僅離線更新版本與發布）。

## Technical Objectives and Strategy

1. Domain 目標：新增 Base Assumption Guardrail 能力層
- 輸入：歷史增長觀測、當前 margin、模型上下文、預測年限。
- 輸出：`guarded_growth_series`、`guarded_margin_series`、`guardrail_hit`、`guardrail_reason`、`guardrail_version`。
- 性質：單調、有界、可回溯、可回退。

2. Policy 目標：先 guardrail 再 forward signal
- 流程順序固定為 `base_raw -> base_guarded -> forward_adjusted`。
- `forward_signal_calibration` 不再承擔修正基底過熱責任，只處理 bp 級方向幅度微調。

3. Growth 策略目標
- 以 robust anchor（winsorized/trimmed/median）取代易受極端值影響的 base anchor。
- 設定最小樣本門檻，樣本不足時走 deterministic fallback。
- 引入可持續增長上限（sustainable cap）避免 year1 growth 過熱。

4. Margin 策略目標
- 以內部統計區間作為長期收斂目標。
- 採兩段式收斂：前段允許貼近現況，後段強制向 normalized margin 收斂。
- 防止 10 年預測期出現近似常數高 margin 的路徑。

5. Application / Interface 目標
- metadata / snapshot / assumption breakdown 全鏈路輸出 `raw/guarded/calibrated`。
- 前端 parser 與展示欄位同步擴充，維持 backward compatibility。

6. Governance 目標
- guardrail 配置版本化與可回退。
- 雙週 cadence 離線檢核指標，達標才發新參數版本。

## Involved Files

1. Domain / Policy / Parameterization
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/growth_assumption_policy.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/growth_blend_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/core_ops_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/engine/graphs/dcf_growth.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/forward_signal_adjustment_service.py`

2. Application / Observability
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_flow.py`
- `finance-agent-core/src/agents/fundamental/application/services/valuation_assumption_breakdown_service.py`
- `finance-agent-core/src/agents/fundamental/application/services/valuation_update_service.py`

3. Backtest / Validation
- `finance-agent-core/src/agents/fundamental/domain/valuation/backtest/runtime_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/backtest/io_service.py`
- `finance-agent-core/scripts/run_fundamental_backtest.py`

4. Frontend（欄位擴充，不改互動）
- `frontend/src/types/agents/fundamental-preview-parser.ts`
- `frontend/src/components/agent-outputs/FundamentalAnalysisOutput.tsx`

5. Proposed New Files
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/base_assumption_guardrail_policy.py`
- `finance-agent-core/src/agents/fundamental/tests/test_base_assumption_guardrail_policy.py`
- `finance-agent-core/tests/test_growth_blend_service.py`
- `finance-agent-core/tests/test_dcf_growth_convergence_policy.py`

## Detailed Per-File Plan

1. `base_assumption_guardrail_policy.py`（new）
- 定義 `GuardrailInput/GuardrailResult` 契約與 guardrail version。
- 實作 growth/margin guardrail（有界、可解釋、具 fallback）。

2. `growth_assumption_policy.py`
- 新增 growth cap 與收斂節奏參數入口。
- 保留既有 profile 機制，改為可配置的權重與上限。

3. `growth_blend_service.py`
- 將 historical anchor 計算改為 robust 聚合策略。
- 加入樣本數門檻與 fallback 記錄（寫入 assumptions）。

4. `core_ops_service.py`
- 在 growth/margin series 形成前加 guardrail hook。
- 保障輸出仍符合既有下游型別與數值範圍。

5. `dcf_growth.py`
- 調整高 margin regime 收斂 target 與起始點，使 year8-10 明確回落。
- 保留計算圖結構不變（只調 convergence policy）。

6. `forward_signal_adjustment_service.py`
- 固化順序 `guardrail -> forward_signal_calibration`。
- 新增 assumptions 文案：`raw -> guarded -> calibrated`。

7. `run_valuation_flow.py`
- snapshot 補欄位：`base_growth_raw/guarded`、`base_margin_raw/guarded`、`guardrail_hit`、`guardrail_version`。
- completion log 補監控欄位與降級訊號。

8. `valuation_assumption_breakdown_service.py`
- 對外暴露 guardrail 摘要，避免僅有最終結果缺乏中間過程。

9. `valuation_update_service.py`
- `valuation_diagnostics` 增加 `raw/guarded/calibrated` 摘要結構，供前端直接讀取。

10. `runtime_service.py` + `io_service.py` + `run_fundamental_backtest.py`
- 回放報告新增：`extreme_upside_rate`、`guardrail_hit_rate`、`consensus_gap_distribution`。
- 建立雙週更新的固定評估報表輸出格式。

11. Frontend parser / component
- parser 擴充 guardrail 與三段式欄位（optional）。
- UI 只新增可讀欄位，不更動現有操作流程。

12. 測試
- 單元測試：邊界、單調、fallback、樣本不足、版本回退。
- 回歸測試：forward signal policy、orchestrator logging、artifact contract。

## Risk/Dependency Assessment

1. 功能風險
- guardrail 太強會壓制真高增長公司，需透過回放調參避免過度保守。

2. 數據風險
- 樣本不足時 robust 聚合不穩，需最小樣本門檻與 deterministic fallback。

3. 治理風險
- 模型僅先覆蓋 `dcf_growth`，其他模型暫未一致；需在文件與輸出中明確標註 scope。

4. 上線風險（無 feature flag）
- 必須依賴 pre-ship gate 與快速回退策略降低風險。

5. 依賴
- 穩定可重現的回放資料集。
- 一致的 artifact/snapshot 契約。
- 既有前端 parser 向後相容能力。

6. 回退策略
- 參數版本回退（guardrail 配置回上一版）。
- policy 回退至 legacy path（guardrail disable）。
- 必要時整體部署回退。

## Validation and Rollout Gates

1. Gate 1（Unit / Contract）
- guardrail 契約、單調性、有界、fallback、版本欄位測試全綠。

2. Gate 2（Integration）
- `dcf_growth` 端到端可輸出 `raw/guarded/calibrated`，不破壞既有輸出契約。

3. Gate 3（Regression）
- fundamental valuation / orchestrator / artifact / parser 回歸全綠。

4. Gate 4（Offline Backtest）
- 估值誤差不劣化，且 `extreme_upside_rate` 下降達標才可發布新版本。

5. Gate 5（Post-Deploy 24h）
- 監控 `guardrail_hit_rate`、`extreme_upside_rate`、`valuation_drift`、`fallback_rate`。
- 任一超閾值即回退 guardrail 版本。

## Assumptions/Open Questions

1. 已確認：本輪僅覆蓋 `dcf_growth`；`dcf_standard` 下一輪接入。
2. 已確認：margin 長期收斂目標先採內部統計區間，不接外部 provider。
3. 已確認：guardrail 參數更新節奏採雙週更。
4. 已確認：前端僅加欄位顯示 `raw/guarded/calibrated`，不改交互。
5. 待定操作性問題：雙週更新由人工觸發（runbook）還是 CI 定時任務執行；本輪先按 runbook 手動流程落地。
