# Fundamental NVDA Valuation Remediation Plan (2026-03-04)

## Requirement Breakdown

### Objective
修正 `finance-agent-core/src/agents/fundamental` 在 NVDA 案例中出現的顯著低估，確保估值結果在資料時效、參數語意、追溯性上符合預期。

### Confirmed Decisions
1. 不使用 feature flag，直接上線。
2. `time_alignment_policy` 先採 `warn`。
3. `shares_outstanding` 改為「market stale 時回退 filing-first」。
4. API 回傳需新增 `parameter_source_summary`。
5. 長期成長來源僅採第一層方案，不接第二層 analyst provider。

### Non-goals
1. 不重寫 DCF 核心計算圖公式。
2. 本輪不接入 LSEG/FactSet/Bloomberg 等第二層長期成長來源。
3. 本輪不做前端 UI 改版，只擴充資料欄位。

## Technical Objectives and Strategy

### Objective A: Filing Freshness Fix
把 SEC 報表抓取由「年份推測優先」改為「最新可用 filing 優先」，避免 valuation 落在舊年度資料。

### Objective B: Growth Semantics Split
將短期成長與終值成長解耦：
1. `revenueGrowth/earningsGrowth` 僅用於 projected growth。
2. `terminal_growth` 僅由第一層長期錨點與政策規則推導。

### Objective C: Market Stale Fallback
`shares_outstanding` 來源策略調整：
1. market 不 stale：沿用 market。
2. market stale 或缺失：回退 filing-first。

### Objective D: API Explainability
在 fundamental 估值輸出中提供 `parameter_source_summary`，清楚說明關鍵參數的來源、時間點、品質標記與回退原因。

## Involved Files

### Core Changes
1. `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/financial_payload_service.py`
2. `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/extractor.py`
3. `finance-agent-core/src/agents/fundamental/infrastructure/market_data/provider_contracts.py`
4. `finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py`
5. `finance-agent-core/src/agents/fundamental/infrastructure/market_data/yahoo_finance_provider.py`
6. `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/saas/saas.py`
7. `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/market_controls_service.py`
8. `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/time_alignment_guard_service.py`
9. `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/metadata_service.py`
10. `finance-agent-core/src/agents/fundamental/application/services/valuation_assumption_breakdown_service.py`
11. `finance-agent-core/src/agents/fundamental/application/services/valuation_update_service.py`
12. `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_use_case.py`

### Tests
1. `finance-agent-core/tests/test_param_builder_canonical_reports.py`
2. `finance-agent-core/tests/test_fundamental_market_data_client.py`
3. `finance-agent-core/tests/test_fundamental_growth_blender.py`
4. `finance-agent-core/tests/test_fundamental_orchestrator_logging.py`
5. `finance-agent-core/tests/test_sec_xbrl_live_golden.py`

## Detailed Per-File Plan

### 1) SEC Filing Selection and Freshness
1. `financial_payload_service.py`
   1. 將報表年份迴圈調整為「最新可用 filing 優先」。
   2. 將 filing metadata（form/accession/filing_date/accepted_datetime）納入 payload。
2. `extractor.py`
   1. 擴充 `target_filing` 選擇依據，避免單靠 fiscal year 命中。
   2. 保留並上拋 anchor date 與 filing 對應資訊。

### 2) Growth Source Semantics
1. `yahoo_finance_provider.py`
   1. 將既有短期成長欄位明確標記為短期 horizon。
   2. 不再讓該欄位直接承擔 terminal growth 語意。
2. `saas.py`
   1. `terminal_growth` 改用第一層長期錨點推導。
   2. 短期成長僅進 `growth_rates` blending。
3. 第一層長期成長引入方式
   1. 來源：宏觀 proxy（FRED 系列或既有 macro provider）。
   2. 規則：`terminal_growth = min(policy_cap, long_run_anchor, wacc - buffer)`。
   3. 無資料時回退：既有 policy default + 明確 assumption log。

### 3) Shares Source Policy
1. `market_data_service.py`
   1. 增加 market staleness 判定欄位。
   2. 產出 `shares_outstanding` 的來源決策與回退原因。
2. `market_controls_service.py`
   1. 實作「market stale -> filing-first」。
   2. assumption 增加來源/回退敘述，供審計與 UI 顯示。

### 4) Metadata and API Contract
1. `provider_contracts.py`
   1. 擴充 datum metadata 欄位（horizon/source_detail/staleness/fallback_reason）。
2. `metadata_service.py`
   1. 新增 `parameter_source_summary` 組裝。
3. `valuation_assumption_breakdown_service.py`
   1. 將 `parameter_source_summary` 注入 assumption breakdown。
4. `valuation_update_service.py`
   1. 將 `parameter_source_summary` 寫入 preview/API payload。
5. `run_valuation_use_case.py`
   1. completion log 輸出 `parameter_source_summary`、freshness 與 fallback 狀態。

## Risk/Dependency Assessment

### Functional Risks
1. 最新 filing 選擇器規則錯誤會造成非預期資料切換。
2. growth 語意調整會導致估值分佈出現可觀變動。

### Runtime Risks
1. 外部資料源（Yahoo/FRED）波動導致缺值。
2. 回退邏輯若未打點完整，容易形成靜默降級。

### Dependency Risks
1. API 欄位擴充需維持向後相容，避免破壞既有 consumer。

### Rollback Strategy
不走 feature flag；回滾策略採部署版本回退與 git revert。

## Validation and Rollout Gates

### Gate 1: Unit and Contract
1. market data 與 param builder 測試全綠。
2. `parameter_source_summary` schema 相容驗證通過。

### Gate 2: NVDA Replay
1. 回放 NVDA case，確認首選報表為最新可用 filing。
2. 確認不再出現短期高增長直接灌 terminal 的語意錯位。
3. 確認 `shares_outstanding` 在 stale 情境可回退到 filing-first。

### Gate 3: Cross-Ticker Regression
1. 成長股、成熟股、金融股各至少一檔回放。
2. 檢查估值漂移均可由來源與假設變更解釋。

### Gate 4: Post-Deploy Monitoring
1. 觀察 24 小時 `warn` 量、fallback 觸發率、資料缺失率。
2. 異常即啟動部署版本回退。

## Assumptions/Open Questions
1. `market stale` 閾值建議值：`> 5` 個交易日（待最終固定）。
2. `warn` 模式下是否需要同步產生監控告警（建議需要）。
3. `parameter_source_summary` 是否需在前端固定區塊顯示（建議需要）。
