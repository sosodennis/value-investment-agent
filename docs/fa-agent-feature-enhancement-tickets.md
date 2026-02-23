# FA Agent Feature Enhancement Tickets (Executable Backlog)

日期：2026-02-23
來源：
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/fa-agent-feature-enhancement.md`
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/research-paper/fundamental-enhancement-cross-validation-2026-02-23.md`

估時單位：人日（Ideal Engineering Days）
說明：本清單以「可直接落地」為目標，全部綁定實際 repo 檔案路徑。

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
| FAE-010 | MC batch evaluator 介面（先在 SaaS/Bank 落地） | P1 | 3.0 | FAE-009 |
| FAE-011 | Forward signal contract（MD&A / earnings call）與 assumption 接口 | P1 | 2.5 | FAE-006 |
| FAE-012 | Regression report：JSON -> Markdown + drift gate | P1 | 1.5 | FAE-006 |
| FAE-013 | 測試補齊（unit/integration/regression） | P0 | 3.0 | FAE-001..FAE-012 |
| FAE-014 | 文檔與 runbook 更新 | P1 | 1.0 | FAE-013 |

總估時：`32.0` 人日（不含 TODO enhancement）

---

## 2) 執行順序（Critical Path）

1. FAE-001 -> FAE-002 -> FAE-004
2. FAE-001 -> FAE-003 -> FAE-004
3. FAE-004 -> FAE-005 -> FAE-006 -> FAE-007
4. FAE-006 -> FAE-008
5. FAE-009 -> FAE-010
6. FAE-006 -> FAE-011
7. FAE-006 -> FAE-012
8. 全部完成後執行 FAE-013 -> FAE-014

建議 Sprint 切分：
- Sprint A（第 1-2 週）：FAE-001~FAE-006
- Sprint B（第 3-4 週）：FAE-007~FAE-012
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
**標題**：MC batch evaluator 介面（先在 SaaS/Bank 落地）
**目標**：降低 Python per-iteration call 開銷

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/monte_carlo.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/core.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_saas/tools.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/valuation_bank/tools.py`

**驗收標準**：
1. 新增 batch evaluator 接口，不破壞舊 evaluator。
2. 至少在 SaaS/Bank 模型中可切換 batch 模式。

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

## FAE-012（P1, 1.5d）
**標題**：Regression report：JSON -> Markdown + drift gate
**目標**：建立每次改動可審查的回歸報表

**主要檔案**：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/backtest.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/reports/`（輸出）
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/research-paper/`（報表模板可選）

**驗收標準**：
1. 可輸出 markdown summary + drift table。
2. 有 PASS/FAIL gate 規則（drift/errors/issues）。

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
| FAE-901 | HITL 整合（全部延後） | P1 | 2.0 | 審批流程、人工覆核 UI/狀態機全部放 TODO。 |
| FAE-902 | 行業均值 fallback 強制高風險 + 人工審批 | P1 | 1.5 | 落到行業均值不得默默計算，必須標記 `high_risk_assumption` 並卡人工審批。 |
| FAE-903 | Sobol/Shapley 全域敏感度與交互作用分解 | P2 | 4.0 | 研究型 enhancement，待核心路徑穩定後再上。 |

---

## 5) 交付里程碑（Milestone DoD）

### Milestone M1（完成 FAE-001~006）
1. 模型語義與執行一致。
2. 契約可攜帶資料品質與風險。

### Milestone M2（完成 FAE-007~012）
1. UI 可視化完整。
2. 資料來源治理與 MC 策略升級完成。
3. 回歸報表自動產出。

### Milestone M3（完成 FAE-013~014）
1. 測試與文檔封板，可進入下一輪擴展。
