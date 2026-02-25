# FA Agent Feature Enhancement Tickets (Executable Backlog)

日期：2026-02-23
來源：
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/fa-agent-feature-enhancement.md`
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/research-paper/fundamental-enhancement-cross-validation-2026-02-23.md`

估時單位：人日（Ideal Engineering Days）
說明：本清單以「可直接落地」為目標，全部綁定實際 repo 檔案路徑。

---

## 執行進度（更新於 2026-02-24）

| Ticket | 狀態 | 進度說明 |
|---|---|---|
| FAE-001 | ✅ Completed | 已完成 model selection -> calculator 類型映射修正（`dcf_standard`/`dcf_growth` 不再隱性映射為 `saas`），並補齊對應測試。 |
| FAE-002 | ✅ Completed (v1) | 已新增 `valuation_dcf_standard` 獨立 skill（schema/tool）並接入 registry，auditor 增加 `dcf_standard` 專屬入口（目前公式仍沿用 SaaS FCFF graph，後續在 FAE-004/005 再差異化）。 |
| FAE-003 | ✅ Completed (v1) | 已新增 `valuation_dcf_growth` 獨立 skill（schema/tool）並接入 registry，auditor 增加 `dcf_growth` 專屬入口（目前公式仍沿用 SaaS FCFF graph，後續在 FAE-004/005 再差異化）。 |
| FAE-004 | ✅ Completed (v1) | 已新增 `dcf_standard.py` / `dcf_growth.py` 專屬 param builder，`param_builder` 路由已切換，不再直接綁定 `_build_saas_params`（目前內部計算仍重用 FCFF payload，後續在 FAE-005/後續票再做模型公式差異化）。 |
| FAE-005 | ✅ Completed | `saas/dcf_standard/dcf_growth` 路徑改為 market-aware `wacc`（CAPM）與 `terminal_growth`（consensus-aware）並加 clamp 防護，新增 `risk_free_rate/beta/market_risk_premium` 參數可見性與測試覆蓋。 |
| FAE-006 | ✅ Completed | 已將 `data_quality_flags`、`assumption_risk_level`、`time_alignment_status` 正式納入後端 preview contract（DTO/mappers/view_model/formatter/serializer）與前端 parser，並加入 fallback 解析與測試覆蓋。 |
| FAE-007 | ✅ Completed | 已完成前端固定估值卡片與資料品質可視化；MC 開啟時顯示 `executed_iterations`/`stopped_early`/`effective_window`/`psd_repaired`，並新增元件測試覆蓋。 |
| FAE-008 | ✅ Completed | 已完成 market provider facade（`yfinance` + `FRED macro`），並將 `quality_flags`、`license_note`、逐欄位 `market_datums` metadata 接入 valuation metadata/data freshness，含測試覆蓋。 |
| FAE-009 | ✅ Completed | MC engine 新增 `sampler_type`（`pseudo`/`sobol`/`lhs`）、sampler diagnostics 與 fallback 訊號，並打通 SaaS/Bank/REIT 參數契約與前端 parser 顯示。 |
| FAE-010 | ✅ Completed | MC engine 已切為 batch-only evaluator 路徑（移除 scalar evaluator 與 `FUNDAMENTAL_MONTE_CARLO_BATCH_ENABLED` 切換）；SaaS/Bank/REIT 全部使用批次計算，diagnostics 固定輸出 `batch_evaluator_used=true`。 |
| FAE-011 | ✅ Completed | 已完成 `ForwardSignal` policy 主幹，並改為單一 `financial_reports_artifact_id` 載入 `financial_reports + forward_signals`（無新增 state pointer）；已接入 SEC XBRL trend-based signal producer + SEC text signal producer（10-K/10-Q/8-K，優先 MD&A/Item 區段）於 `financial_health` 寫入同一 artifact，model_selection 透傳 `forward_signals`，valuation 從同一 artifact 讀取套用；新增 FA 完成事件固定 log 欄位：`forward_signals_present/count/source`；前端 parser/UI 已可顯示 `forward_signal_summary/risk/evidence/source_types`；text producer log 已補 focused 診斷（`focused_records_total/fallback_records_total/focused_form_counts/emitted_doc_types`）與 focused signal 診斷（`focused_signals_count/emitted_focused_doc_types`）；本次新增 section 抽取優先走 `edgartools` `obj/get_item_with_part`（10-K Item7、10-Q Part I Item2、8-K Item2.02/7.01）後再 fallback regex，並擴充 lexical 規則（negation 過濾、forward/historical 時態加權、numeric guidance 抽取與 confidence 調整）；移除縮寫欄位，`basis_points` 為唯一單位字段（不保留兼容欄位）；並補上 evidence provenance（`filing_date/accession_number/focus_strategy/rule`）與 stale filing 置信度降權。 |
| FAE-015 | ✅ Completed | 已新增 `DCF_STANDARD` / `DCF_GROWTH` 獨立 calculation graphs（含 growth/margin/reinvestment 收斂節點與 terminal growth hard guard），`valuation_dcf_standard/tools.py` 與 `valuation_dcf_growth/tools.py` 改為直接執行新 graph，不再調用 `calculate_saas_valuation`；兩模型已接入獨立 MC batch evaluator，並補上 `test_dcf_graph_tools.py` 驗證（含「不依賴 SaaS wrapper」測試）。 |
| FAE-016 | ✅ Completed | 已完成 MC batch kernel 第二階段優化：SaaS/Bank/DCF batch evaluator 年度遞推改為 in-place loop + 預配置陣列（移除 `np.concatenate` 造成的額外配置），並新增 profiling 腳本 `/finance-agent-core/scripts/profile_monte_carlo_batch_kernels.py` 產出 1k/10k 基準報表（JSON + Markdown，見 `/finance-agent-core/reports/fundamental_mc_kernel_profile.*`）；結果顯示 speedup 且數值一致性 `max_abs_diff=0`（在配置容差內）。 |
| 其餘 Tickets | ⏳ Pending | 主線剩餘 `FAE-013`、`FAE-014`。`FAE-012` 已移入 TODO enhancement。 |

---

## 1) Ticket 總覽（含優先級、估時、依賴）

| Ticket | 標題 | Priority | 估時 | 依賴 |
|---|---|---:|---:|---|
| FAE-001 | 修正 model-selection 到 calculator 的語義映射 | P0 | 1.5 | - |
| FAE-002 | 建立 `dcf_standard` 獨立 skill（schema/tool/audit） | P0 | 3.0 | FAE-001 |
| FAE-003 | 建立 `dcf_growth` 獨立 skill（schema/tool/audit） | P0 | 2.5 | FAE-001 |
| FAE-004 | Param builder 策略化：新增 `dcf_standard`/`dcf_growth` 路由 | P0 | 2.0 | FAE-002, FAE-003 |
| FAE-005 | SaaS WACC/Terminal Growth 改為 market-aware + clamp | P0 | 1.5 | FAE-004 |
| FAE-006 | 擴充輸出契約：資料品質與假設風險欄位 | P0 | 1.5 | FAE-004 |
| FAE-007 | UI 固定卡片 + MC 診斷與資料品質可視化 | P1 | 2.0 | FAE-006 |
| FAE-008 | Market data provider facade + 第二來源介面（先接 Macro/FRED） | P1 | 3.0 | FAE-006 |
| FAE-009 | MC sampler strategy（Pseudo + QMC/Sobol/LHS） | P1 | 3.5 | - |
| FAE-010 | MC batch-only evaluator（SaaS/Bank/REIT） | P1 | 3.0 | FAE-009 |
| FAE-011 | Forward signal contract（MD&A / earnings call）與 assumption 接口 | P1 | 2.5 | FAE-006 |
| FAE-013 | 測試補齊（unit/integration/regression） | P0 | 3.0 | FAE-001..FAE-011, FAE-015, FAE-016 |
| FAE-014 | 文檔與 runbook 更新 | P1 | 1.0 | FAE-013 |
| FAE-015 | DCF 真實引擎落地（移除 SaaS transitional wrapper） | P0 | 3.5 | FAE-004, FAE-005 |
| FAE-016 | MC batch kernel profiling 與第二階段優化 | P1 | 2.0 | FAE-010 |

總估時：`36.0` 人日（不含 TODO enhancement）

---

## 2) 執行順序（Critical Path）

1. FAE-001 -> FAE-002 -> FAE-004
2. FAE-001 -> FAE-003 -> FAE-004
3. FAE-004 -> FAE-005 -> FAE-006 -> FAE-007
4. FAE-006 -> FAE-008
5. FAE-009 -> FAE-010
6. FAE-006 -> FAE-011
7. FAE-004 -> FAE-015
8. FAE-010 -> FAE-016
9. 全部完成後執行 FAE-013 -> FAE-014

建議 Sprint 切分：
- Sprint A（第 1-2 週）：FAE-001~FAE-006
- Sprint B（第 3-4 週）：FAE-007~FAE-011 + FAE-015~FAE-016
- Sprint C（第 5 週）：FAE-013~FAE-014

---

## 3) Ticket 詳細定義

## FAE-001（P0, 1.5d）
**標題**：修正 model-selection 到 calculator 的語義映射
**目標**：讓 `dcf_standard` / `dcf_growth` 不再路由到 `saas`

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/value_objects.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/services.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/application/orchestrator.py`

**驗收標準**：
1. `selected_model=dcf_standard`、`dcf_growth` 可映射到對應 calculator type。
2. 不存在 fallback 到 `saas` 的隱性路徑（除非明確 policy 指定）。

---

## FAE-002（P0, 3.0d）
**標題**：建立 `dcf_standard` 獨立 skill（schema/tool/audit）
**目標**：建立成熟企業通用 DCF 路徑

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_standard/schemas.py`（新增）
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_standard/tools.py`（新增）
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/registry.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/auditor/rules.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/graphs/`（必要時新增 dcf 圖）

**驗收標準**：
1. DCF standard 有獨立 schema + tool + audit。
2. Terminal growth / discount rate 邊界檢查完備。

---

## FAE-003（P0, 2.5d）
**標題**：建立 `dcf_growth` 獨立 skill（schema/tool/audit）
**目標**：高成長通用 DCF 路徑與 SaaS 特化分離

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_growth/schemas.py`（新增）
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_growth/tools.py`（新增）
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/registry.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/auditor/rules.py`

**驗收標準**：
1. dcf_growth 與 saas 估值路徑分離。
2. growth shock / margin / discount factor 有獨立參數契約。

---

## FAE-004（P0, 2.0d）
**標題**：Param builder 策略化：新增 `dcf_standard`/`dcf_growth` 路由
**目標**：參數建構層與新模型對齊

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/context.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/`（新增 dcf 模組）

**驗收標準**：
1. 新模型 route 的 `params/trace_inputs/assumptions/metadata` 完整。
2. time-alignment guard 和 shares source provenance 在新模型同樣生效。

---

## FAE-005（P0, 1.5d）
**標題**：SaaS WACC/Terminal Growth 改為 market-aware + clamp
**目標**：移除過度依賴 policy default 的問題

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/assumptions.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/auditor/rules.py`

**驗收標準**：
1. WACC 能由 market inputs 驅動，並顯示 clamp 原因。
2. 假設來源在 assumption_breakdown 可見。

---

## FAE-006（P0, 1.5d）
**標題**：擴充輸出契約：資料品質與假設風險欄位
**目標**：讓 API/前端可展示資料治理訊息

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/interface/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/interface/serializers.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/interface/formatters.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/application/view_models.py`

**驗收標準**：
1. 回傳包含 `data_quality_flags`、`assumption_risk_level`、`time_alignment_status`。
2. 舊欄位不破壞現有 parser（協議向前兼容在 dev 內保持）。

---

## FAE-007（P1, 2.0d）
**標題**：UI 固定卡片 + MC 診斷與資料品質可視化
**目標**：前端完整呈現 deterministic + MC + quality

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/components/agent-outputs/FundamentalAnalysisOutput.tsx`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/fundamental.ts`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/fundamental-preview-parser.ts`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/generated/api-contract.ts`（如需）

**驗收標準**：
1. 無論 MC on/off，固定卡片始終顯示。
2. MC 開啟時顯示 diagnostics：`executed_iterations/stopped_early/effective_window/psd_repaired`。

---

## FAE-008（P1, 3.0d）
**標題**：Market data provider facade + 第二來源介面（先接 Macro/FRED）
**目標**：降低單一來源與授權風險

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/data/clients/market_data.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/data/ports.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/data/clients/`（新增 provider modules）

**驗收標準**：
1. Provider 可插拔（Yahoo + Macro source）。
2. 每個 market datum 輸出 `source/as_of/quality_flags/license_note`。

---

## FAE-009（P1, 3.5d）
**標題**：MC sampler strategy（Pseudo + QMC/Sobol/LHS）
**目標**：提升收斂效率與穩定性

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/monte_carlo.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_saas/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_bank/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_reit_ffo/tools.py`

**驗收標準**：
1. 可設定 sampler type（至少 `pseudo`, `sobol`, `lhs`）。
2. diagnostics 輸出 sampler 與收斂指標。

---

## FAE-010（P1, 3.0d）
**標題**：MC batch-only evaluator（SaaS/Bank/REIT）
**目標**：以單一路徑 batch evaluator 降低 Python per-iteration call 開銷與維護成本

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/monte_carlo.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/core.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_saas/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_bank/tools.py`

**驗收標準**：
1. MC engine 僅接受 `batch_evaluator`，不再保留 scalar evaluator。
2. SaaS/Bank/REIT 模型全部走 batch 路徑，無雙路徑切換。

---

## FAE-011（P1, 2.5d）
**標題**：Forward signal contract（MD&A / earnings call）與 assumption 接口
**目標**：把非結構化前瞻訊號先納入 assumptions 層

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/assumptions.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/interface/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/application/orchestrator.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/application/fundamental_service.py`

**驗收標準**：
1. Forward signal 有結構化欄位：`value/confidence/evidence`.
2. 可進 assumptions，不直接覆蓋硬財務欄位。

---

## FAE-015（P0, 3.5d）
**標題**：DCF 真實引擎落地（移除 SaaS transitional wrapper）
**目標**：讓 `dcf_standard` / `dcf_growth` 真正使用獨立 DCF 數學引擎，而非 `calculate_saas_valuation` 包裝

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_standard/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_growth/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/graphs/`（新增 dcf graphs）
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_standard/schemas.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_growth/schemas.py`

**驗收標準**：
1. `dcf_standard` / `dcf_growth` 不再呼叫 `calculate_saas_valuation`。
2. 具備多階段收斂（growth/margin/reinvestment converging）與終值邏輯硬性邊界。
3. 新增對應單元測試與回歸基準案例。

---

## FAE-016（P1, 2.0d）
**標題**：MC batch kernel profiling 與第二階段優化
**目標**：在已完成 batch-only evaluator 前提下，優化年度遞推 hot loop，並提供可量化效能基準

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_saas/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_bank/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_reit_ffo/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_standard/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_dcf_growth/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/monte_carlo.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/scripts/profile_monte_carlo_batch_kernels.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/docs/fundamental_monte_carlo_batch_profiling.md`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_monte_carlo_engine.py`

**驗收標準**：
1. 輸出 profiling 結果（至少含 1k/10k iterations 比較）。
2. 優化後 p50 wall-time 有可驗證下降，且數值結果與舊版一致於容差內。
3. 文件新增性能基準與再現命令。

---

## FAE-013（P0, 3.0d）
**標題**：測試補齊（unit/integration/regression）
**目標**：保證模型、契約、前端解析穩定

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_model_selection_scoring_weights.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_param_builder_canonical_reports.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_monte_carlo_engine.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_saas_monte_carlo_integration.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_output_contract_serializers.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_artifact_api_contract.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/fundamental-preview-parser.test.ts`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/protocol.contract.test.ts`

**驗收標準**：
1. 新模型路由、新契約欄位、MC 新 sampler 均有測試。
2. Regression baseline 可重跑且可比較。

---

## FAE-014（P1, 1.0d）
**標題**：文檔與 runbook 更新
**目標**：確保工程與審計可接手

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/fa-agent-feature-enhancement.md`
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/backend-guideline.md`
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/logging-standardization-spec-2026-02-18.md`
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/research-paper/fundamental-enhancement-cross-validation-2026-02-23.md`

**驗收標準**：
1. 新架構、欄位、診斷、回測命令有完整 runbook。
2. 文件與代碼狀態一致。

---

## 4) TODO Enhancement（延後）

| Ticket | 標題 | Priority | 估時 | 說明 |
|---|---|---:|---:|---|
| FAE-012 | Regression report：JSON -> Markdown + drift gate | P2 | 1.5 | 目前未接 UI，也未被其他 agent 在 runtime 消費；保留為工程治理 enhancement（CI/審查用途）。 |
| FAE-901 | HITL 整合（全部延後） | P1 | 2.0 | 審批流程、人工覆核 UI/狀態機全部放 TODO。 |
| FAE-902 | 行業均值 fallback 強制高風險 + 人工審批 | P1 | 1.5 | 落到行業均值不得默默計算，必須標記 `high_risk_assumption` 並卡人工審批。 |
| FAE-903 | Sobol/Shapley 全域敏感度與交互作用分解 | P2 | 4.0 | 研究型 enhancement，待核心路徑穩定後再上。 |

---

## 5) 交付里程碑（Milestone DoD）

### Milestone M1（完成 FAE-001~006）
1. 模型語義與執行一致。
2. 契約可攜帶資料品質與風險。

### Milestone M2（完成 FAE-007~011、FAE-015~016）
1. UI 可視化完整。
2. 資料來源治理與 MC 策略升級完成。
3. 模型與效能主線重構完成（不含 TODO enhancement）。

### Milestone M3（完成 FAE-013~014）
1. 測試與文檔封板，可進入下一輪擴展。
