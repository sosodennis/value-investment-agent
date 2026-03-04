# Fundamental Refactor Execution Tracker

Date: 2026-03-03
Owner: Codex + project maintainers
Scope: `finance-agent-core/src/agents/fundamental/**`
Status: In Progress

## 1. 目的

這份文檔用來追蹤 fundamental 重構的「計畫」與「實際進度」。
後續每一波變更都在此更新，避免討論與實作脫節。

## 2. 參考文檔

1. `finance-agent-core/docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
2. `finance-agent-core/docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
3. `finance-agent-core/docs/standards/refactor_lessons_and_cross_agent_playbook.md`

## 3. 執行策略

1. 先做低風險命名/邊界修正（保留 shim，不破壞行為）。
2. 再做中風險拆分（大檔拆解、契約統一）。
3. 最後收斂 legacy 路徑（移除 shim、清理 import）。
4. 每一批完成後必做 `Lessons Review Gate`：
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 記錄 `updated` 或 `no_update`（必填）及原因

### 3.1 批次記錄模板（強制）

每一批變更除了測試/對齊外，必須新增以下欄位：

1. `Lessons Review: updated | no_update`
2. `Reason: <why>`

說明：

1. `updated`：本批有新問題模式、根因、或 guardrail，已更新 lessons 文檔。
2. `no_update`：本批沒有新增可抽象的經驗，但仍需給出具體判定理由。

## 4. 階段計畫（Plan）

| Phase | Goal | 主要工作 | 驗收標準 | 狀態 |
|---|---|---|---|---|
| P0 | Baseline/追蹤就緒 | 建立藍圖、命名規範、execution tracker | 文檔齊備，可追蹤後續波次 | Done |
| P1 | 命名與邊界修正（低風險） | concrete `*Port` -> `*Repository`（保留相容別名）；application 端引用改名 | 功能不變、既有測試通過 | Done |
| P2 | 契約收斂（中風險） | 統一 market provider contract，移除 duck-typing；統一 canonical financial report 模型邊界 | 型別一致、測試覆蓋關鍵路徑 | In Progress |
| P3 | 大檔拆分（中高風險） | 拆 `sec_xbrl/factory.py`、`forward_signals_text.py`、`param_builder.py` | 檔案內聚提升、單檔規模下降 | Todo |
| P4 | 目錄收斂（中風險） | `data` 漸進遷移到 `infrastructure`，保留短期 shim | application 不直連 legacy 實作 | Todo |
| P5 | 清理收尾（高風險） | 移除 shim、更新 docs/runbook、穩定性驗證 | 無 legacy 路徑依賴 | Todo |
| P6 | Auditor 主流程接入（高價值） | valuation execution 串接 model auditor（hard/soft gate） | 任一模型審核生效，hard-fail 不進 calculator | Planned |
| P7 | Service 顆粒收斂（中風險） | 精簡 parameterization/model builders 薄 service | 內聚提升、跳檔下降、輸出不變 | In Progress |
| P8 | Monte Carlo 性能基線（中風險） | 建立固定 seed/iterations baseline 與回歸閾值 | 性能退化可自動攔截 | Planned |

## 5. 當前進度（Progress）

### 2026-03-03

Completed:

1. Standards 更新（聚焦兩條）：
   - 新增 `Entity/Value Object vs Domain Service` 決策規則。
   - 新增重計算節點 performance gate（async offload + reproducible baseline）。
2. F-P0 實作（auditor 主流程接入）：
   - `parse_valuation_model_runtime` 要求 `auditor` callable。
   - valuation execution 改為 `schema -> auditor -> calculator`。
   - auditor failure 會阻斷 calculator 並回傳明確錯誤。
   - auditor warning/failure 會輸出 structured logs。
   - audit summary 寫入 `build_metadata`，並進入 valuation preview/artifact。
3. T-P0 實作（technical async 阻塞尾巴修復）：
   - `semantic_backtest_context_service` 的 `run_backtest/run_wfa` 改為 `asyncio.to_thread(...)` offload。
   - 新增 bounded concurrency semaphore，避免重計算同時過量。
4. 新增/更新測試：
   - `test_fundamental_interface_parsers.py`（auditor runtime contract）
   - `test_fundamental_orchestrator_logging.py`（audit fail 會提前終止）
   - `test_technical_semantic_backtest_context_service.py`（backtest/wfa offload 路徑）
5. 驗證結果：
   - `ruff check`（所有 touched files）通過
   - `pytest` targeted batch 通過（36 passed）
6. F-P1 第一批大切片（service 顆粒收斂）：
   - 收斂 `eva/reit/residual_income` model builders 內部薄 service owner：
     - policy/output assembly 函式併回各自 builder owner 檔案
   - 移除 6 個碎片檔案：
     - `eva/eva_invested_capital_policy_service.py`
     - `eva/eva_output_assembly_service.py`
     - `reit/reit_fallback_policy_service.py`
     - `reit/reit_ffo_policy_service.py`
     - `reit/reit_output_assembly_service.py`
     - `residual_income/residual_income_output_assembly_service.py`
7. 驗證結果（F-P1 slice-1）：
   - `ruff check`（touched model builders）通過
   - `pytest finance-agent-core/tests/test_fundamental_* -q` 通過（50 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
8. F-P1 第二批大切片（service 顆粒收斂）：
   - 收斂 `bank/saas` model builders 內部薄 service owner：
     - CAPM policy / rates policy / output assembly 函式併回各自 builder owner 檔案
   - 移除 6 個碎片檔案：
     - `bank/bank_capm_policy_service.py`
     - `bank/bank_rorwa_policy_service.py`
     - `bank/bank_output_assembly_service.py`
     - `saas/saas_capm_policy_service.py`
     - `saas/saas_operating_rates_policy_service.py`
     - `saas/saas_output_assembly_service.py`
9. 驗證結果（F-P1 slice-2）：
   - `ruff check`（`bank.py` + `saas.py`）通過
   - `pytest finance-agent-core/tests/test_fundamental_* -q` 通過（50 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
10. P8 第一批（重計算性能基線 gate）：
   - 新增 Fundamental Monte Carlo 固定案例 latency gate：
     - `tests/test_fundamental_monte_carlo_performance_gate.py`
     - warmup + repeated run + `p50` latency threshold
   - 新增 Technical WFA 固定案例 latency gate：
     - `tests/test_technical_wfa_performance_gate.py`
     - warmup + repeated run + `p50` latency threshold
11. P8 第一批驗證結果：
   - `ruff check`（新增兩個 performance gate tests）通過
   - `pytest tests/test_fundamental_monte_carlo_performance_gate.py tests/test_technical_wfa_performance_gate.py -q` 通過（2 passed）
   - 回歸驗證：
     - `pytest finance-agent-core/tests/test_fundamental_* -q` 通過（51 passed）
     - `pytest finance-agent-core/tests/test_technical_* -q` 通過（26 passed）
12. Standards 更新：
   - 在 cross-agent standard 明確新增「LOC is a signal, not a target」：
     - 高 LOC 是 review 觸發條件，不是硬門檻
     - 不可為追行數目標而拆分
     - 拆分以責任邊界與內聚為先
13. P1 第三批大切片（parameterization wiring/factory 收斂）：
   - 將 `model_builder_factory_service.py` + `model_builder_adapter_service.py` 內聯到 `registry_service.py` owner。
   - 將 `wiring_service.py` 的 context wiring（`BuilderContextDeps` + builder context assembly）內聯到 `default_context_service.py` owner。
   - 刪除 3 個中介檔案：
     - `model_builder_factory_service.py`
     - `model_builder_adapter_service.py`
     - `wiring_service.py`
14. P2 收尾（market provider compatibility 去除）：
   - 移除 `YahooFinanceProvider` / `FredMacroProvider` 未使用且非標準契約的 `fetch_datums(...)`。
   - provider 僅保留 `fetch(...) -> ProviderFetch`。
15. 驗證結果（P1 slice-3 + P2 provider 收尾）：
   - `ruff check`（touched parameterization + providers）通過
   - `pytest finance-agent-core/tests/test_fundamental_* -q` 通過（51 passed）
   - `pytest finance-agent-core/tests/test_technical_* -q` 通過（26 passed）
   - `rg` 驗證：已無 `model_builder_factory_service|model_builder_adapter_service|wiring_service|fetch_datums` 引用
16. 全鏈路 review 三點修復（valuation/model_selection/financial_health）：
   - P1 async 阻塞修復：
     - `run_valuation_use_case.py` 將 `execute_valuation_calculation(...)` 改為 `asyncio.to_thread(...)`。
     - 新增 bounded concurrency semaphore，避免 valuation 重計算併發失控。
   - P2 model_selection handoff fail-fast：
     - `run_model_selection_use_case.py` 在 `report_id` 與 `reports_artifact_id` 同時缺失時立即 fail-fast（不再進 calculation）。
     - 補 completion/error logs（固定 `error_code=FUNDAMENTAL_MODEL_SELECTION_REPORT_ID_MISSING`）。
   - P2 financial_health 邊界型別收斂：
     - 新增 `interface/parsers.py::FinancialHealthPayload` + `parse_financial_health_payload(...)`。
     - `run_financial_health_use_case` / `orchestrator` 改為 typed callback，移除 application use-case contract 上的 `object` payload + normalize callback。
17. 測試補強：
   - `test_fundamental_orchestrator_logging.py`：
     - 新增 valuation offload 驗證（確保 `execute_valuation_calculation` 走 `to_thread`）。
     - 新增 model_selection 缺 report id fail-fast 驗證。
     - financial_health 測試切到 typed parser payload。
   - `test_fundamental_interface_parsers.py`：
     - 新增 `parse_financial_health_payload(...)` 正向案例（mapping/list 入口）驗證。
18. 驗證結果（全鏈路三點修復）：
   - `ruff check`（touched files）通過
   - `pytest finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（21 passed）
   - `pytest finance-agent-core/tests/test_fundamental_* -q` 通過（55 passed）
   - `pytest finance-agent-core/tests/test_technical_* -q` 通過（26 passed）

Lessons Review: updated
Reason: 本日已完成標準更新（LOC 作為訊號而非硬目標）；本批三點修復屬既有規約落地（async offload、handoff fail-fast、typed boundary），未新增新的跨 agent 反模式類型。

### 2026-02-27

Completed:

1. 完成 fundamental valuation + data 架構 review（命名、層邊界、內聚問題）。
2. 更新/補齊 clean architecture 藍圖，含 layer/package 職責邊界。
3. 產出跨 agent 命名與責任規範草案。
4. 升級正式規範文檔 `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`，並明確採「文檔強約束」策略（本階段不引入自動命名檢查）。
5. P1 第一批代碼落地：
   - `FundamentalArtifactPort` 正名為 `FundamentalArtifactRepository`
   - 保留 `FundamentalArtifactPort` / `fundamental_artifact_port` 相容 alias
   - `application/orchestrator.py` 與 `application/factory.py` 引用切到新命名
6. 補齊 `fetch_financial_data` 相容入口，並讓 workflow runner 透過該符號 runtime lookup（維持既有 patch 測試可用）。
7. 驗證結果：
   - `ruff check`（3 個 touched files）通過
   - `pytest finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（6 passed）
8. P2 第一批代碼落地（market provider contract 收斂）：
   - `ProviderFetch` 移到 `data/ports.py` 作為正式契約型別
   - `MarketDataProvider` 統一為 `fetch(ticker_symbol) -> ProviderFetch`
   - `MarketDataClient` 移除 `_provider_fetch` duck-typing，改為 strict provider contract
   - `FREDMacroProvider.fetch` 簽名統一為 `fetch(ticker_symbol)`（ticker 參數顯式忽略）
9. 驗證結果（P2 第一批）：
   - `ruff check`（6 個 touched files）通過
   - `pytest finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（6 passed）
10. P2 第二批代碼落地（canonical financial report 邊界收斂第一步）：
   - `sec_xbrl/provider.fetch_financial_payload` 改為在 adapter 邊界輸出 canonical JSON
   - 使用 `parse_financial_reports_model(...)` 統一 `financial_reports` 契約
   - `forward_signals` 也做最小型別正規化（非 list 則設為 `None`）
11. 新增回歸測試：
   - `test_fetch_financial_payload_normalizes_reports_to_canonical_json`
12. 驗證結果（P2 第二批）：
   - `ruff check`（provider + sec text tests）通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（21 passed）
   - `pytest finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（6 passed）
13. 命名一致性補強（infrastructure/data clients）：
   - 聚合器 `MarketDataClient` 正名為 `MarketDataService`
   - 保留 `MarketDataClient` / `market_data_client` 相容 alias
   - 新增 `market_data_service` export
14. 驗證結果（命名一致性補強）：
   - `ruff check`（market_data/provider/tests）通過
   - `pytest finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（27 passed）
15. `sec_xbrl -> canonical` mapping 責任抽離：
   - 新增 `data/clients/sec_xbrl/canonical_mapper.py`
   - `provider.py` 改由 mapper 負責 canonical reports 轉換，provider 專注 adapter 邊界
16. `sec_xbrl/models.py` 加入 internal-only 模組說明，明確非 canonical contract owner。
17. application 依賴收斂（market data）：
   - 新增 `IFundamentalMarketDataService` / `IMarketSnapshot` protocol（`application/ports.py`）
   - `FundamentalWorkflowRunner` 改為依賴 protocol，而非直接綁 concrete 類型
   - factory wiring 改用 `market_data_service`，維持 runtime 行為不變
18. valuation provenance 命名一致化：
   - trace `author=\"MarketDataClient\"` 全面統一為 `author=\"MarketDataService\"`
19. 驗證結果（P2 第三批）：
   - `ruff check`（application ports/factory + valuation param builders）通過
   - `pytest finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（44 passed）
20. `data -> application` mapper 責任收斂：
   - 新增 `application/report_projection_service.py` 作為 canonical owner
   - `application/orchestrator.py`、`application/view_models.py` 改引用 application service
   - `data/mappers.py` 降為 backward-compatible shim（re-export）
21. 驗證結果（mapper 責任收斂）：
   - `ruff check`（projection service + orchestrator/view_models）通過
   - `pytest finance-agent-core/tests/test_fundamental_model_selection_projection.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（51 passed）
22. P3 拆分前置 first-slice（sec_xbrl factory）：
   - 新增 `data/clients/sec_xbrl/field_resolution_utils.py`
   - 將 `factory.py` 內 field resolution utility（dimensional/relaxed configs、search config key、numeric/scale/preview parse）抽離為獨立模組
   - `BaseFinancialModelFactory` 保留薄 wrapper 以降低風險
23. 驗證結果（P3 first-slice）：
   - `ruff check`（factory + field_resolution_utils）通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（45 passed）
24. P3 第二批拆分（derived metrics / debt helpers）：
   - 新增 `data/clients/sec_xbrl/factory_derived_utils.py`
   - 將 `factory.py` 內共用衍生計算與 debt helper 函式抽離：
     - ratio/subtract/invested_capital/nopat
     - relax_statement_filters/rename_field/field_source_label
     - total debt policy resolution helper / real-estate debt combined helper
   - `BaseFinancialModelFactory` 保留對應 wrapper，維持呼叫面不變
25. 驗證結果（P3 第二批）：
   - `ruff check`（factory + factory_derived_utils）通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（45 passed）
26. P3 第三批拆分前置（report factory common utils）：
   - 新增 `data/clients/sec_xbrl/report_factory_common_utils.py`
   - 將 `FinancialReportFactory._resolve_industry_type`、`_sum_fields` 抽離到共用 util
   - `FinancialReportFactory` 保留 wrapper，呼叫面維持不變
27. 驗證結果（P3 第三批前置）：
   - `ruff check`（factory + report_factory_common_utils）通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（24 passed）
28. 去 legacy 化（測試路徑）：
   - `test_error_handling_fundamental.py` patch 目標從 `FundamentalArtifactPort` 切換到 `FundamentalArtifactRepository`
29. 驗證結果（去 legacy 化）：
   - `ruff check finance-agent-core/tests/test_error_handling_fundamental.py` 通過
   - `pytest finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（23 passed）
30. P3 第四批拆分（industry extension builders 開始）：
   - 新增 `data/clients/sec_xbrl/industrial_extension_builder.py`
   - `FinancialReportFactory._create_industrial_extension` 改為 wrapper 呼叫新 builder
   - 保留既有呼叫介面與行為
31. 驗證結果（industrial builder 切片）：
   - `ruff check`（industrial_extension_builder + factory）通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（45 passed）
32. P3 第四批拆分（financial_services builder 外提）：
   - 新增 `data/clients/sec_xbrl/financial_services_extension_builder.py`
   - `FinancialReportFactory._create_financial_services_extension` 改為 wrapper 呼叫新 builder
33. P3 第四批拆分（real_estate builder 外提）：
   - 新增 `data/clients/sec_xbrl/real_estate_extension_builder.py`
   - `FinancialReportFactory._create_real_estate_extension` 改為 wrapper 呼叫新 builder
34. 驗證結果（三個 extension builders 全部外提）：
   - `ruff check`（factory + industrial/financial_services/real_estate builders）通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（45 passed）
35. P3 第五批拆分（`BaseFinancialModelFactory.create` debt 段落外提）：
   - 新增 `data/clients/sec_xbrl/base_model_debt_builder.py`
   - 將 debt configs、REIT debt component 聚合、total debt policy、relaxed fallback、diagnostics 從 `factory.py` 抽離為 `build_total_debt_field(...)`
   - `factory.py` 的 `create(...)` 改為薄 wrapper 呼叫，既有 `BaseFinancialModelFactory` static API 保持不變
36. 驗證結果（P3 第五批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_debt_builder.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（52 passed）
37. P3 第六批拆分（`BaseFinancialModelFactory.create` income/cashflow/derived 段落外提）：
   - 新增 `data/clients/sec_xbrl/base_model_income_cashflow_builder.py`
   - 將 `preferred stock`、`income statement`、`cash flow`、`derived metrics` 從 `factory.py` 抽離為 `build_income_cashflow_and_derived_fields(...)`
   - `factory.py` 保留 `create(...)` 組裝邏輯與既有 static helper 介面，避免外部呼叫面破壞
38. 驗證結果（P3 第六批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_income_cashflow_builder.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（52 passed）
39. P3 第七批拆分（`BaseFinancialModelFactory.create` context/balance + model assembly 外提）：
   - 新增 `data/clients/sec_xbrl/base_model_context_balance_builder.py`
   - 新增 `data/clients/sec_xbrl/base_model_assembler.py`
   - `factory.py::create(...)` 改為三段 orchestration：
     1) `build_context_balance_fields(...)`
     2) `build_total_debt_field(...)`
     3) `build_income_cashflow_and_derived_fields(...)` + `assemble_base_financial_model(...)`
40. 驗證結果（P3 第七批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_context_balance_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_assembler.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_income_cashflow_builder.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（52 passed）
41. P3 第八批拆分（`create` 的 config helper `C/R` 外提）：
   - 新增 `data/clients/sec_xbrl/base_model_extraction_context.py`
   - 將 `C/R` 本地 helper 收斂為 `BaseModelExtractionContext`（`build_config` + `resolve_configs`）
   - `factory.py::create(...)` 改為透過 extraction context 統一注入到各 builder，進一步降低函式內局部責任耦合
42. 驗證結果（P3 第八批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_context_balance_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_assembler.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_income_cashflow_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_extraction_context.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（52 passed）
43. P3 第九批拆分（field extraction owner 收斂）：
   - 新增 `data/clients/sec_xbrl/base_model_field_extraction_service.py`
   - 將 `BaseFinancialModelFactory` 內 `_extract_field` / `_collect_parsed_candidates` / `_build_resolution_stages` 的主要實作遷移至新 service
   - `factory.py` 保留相容 façade wrappers，避免既有 private API 依賴與測試 patch 路徑破壞
44. 驗證結果（P3 第九批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_field_extraction_service.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_context_balance_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_assembler.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_extraction_context.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_income_cashflow_builder.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（58 passed）
45. 計畫對齊檢查（P3 第九批）：
   - 結果：與 refactor plan 一致（`factory` 朝 façade-only 收斂，未偏離 blueprint/P3 目標）
   - 偏離：無
46. P3 第十批拆分（debt policy owner 收斂）：
   - 新增 `data/clients/sec_xbrl/base_model_debt_policy_service.py`
   - 將 `BaseFinancialModelFactory._resolve_total_debt_policy`、`_log_total_debt_diagnostics` 的主要實作遷移到新 service
   - `factory.py` 保留相容 façade wrappers，避免既有測試與 private API 使用破壞
47. 驗證結果（P3 第十批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_field_extraction_service.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_debt_policy_service.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_context_balance_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_assembler.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_extraction_context.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_income_cashflow_builder.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（58 passed）
48. 計畫對齊檢查（P3 第十批）：
   - 結果：與 refactor plan 一致（static utility wrapper owner 持續外提，`factory` 僅保留 façade）
   - 偏離：無
49. P3 第十一批拆分（façade wrapper 去重）：
   - `BaseFinancialModelFactory` 內純 pass-through static wrappers 改為 `staticmethod(alias)`（保留相同方法名與呼叫行為）
   - 覆蓋範圍：field resolution aliases、derived metric aliases、debt helper aliases
   - 目的：降低 wrapper 樣板與維護成本，同時維持 private API 相容
50. 驗證結果（P3 第十一批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（58 passed）
51. 計畫對齊檢查（P3 第十一批）：
   - 結果：與 refactor plan 一致（`factory` 保留 façade，但降低樣板；未改變既有測試可見行為）
   - 偏離：無
52. P3 第十二批拆分（mapping config resolver owner 收斂）：
   - 新增 `data/clients/sec_xbrl/base_model_mapping_resolver_service.py`
   - 將 `BaseFinancialModelFactory._resolve_configs` 主要實作移至新 service，保留 `factory` façade method
   - 保留既有 logging event（`fundamental_xbrl_mapping_missing` / `fundamental_xbrl_mapping_resolved`）與欄位，確保觀測一致
53. 驗證結果（P3 第十二批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_mapping_resolver_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（58 passed）
54. 計畫對齊檢查（P3 第十二批）：
   - 結果：與 refactor plan 一致（`_resolve_configs` owner 外提、`factory` 維持 façade 相容）
   - 偏離：無
55. P3 第十三批拆分（façade 保留清單契約化）：
   - `factory.py` 新增 `BASE_MODEL_FACTORY_COMPAT_WRAPPERS` 常數，明確列出遷移期需保留的 private façade 方法
   - 新增 `test_sec_xbrl_factory_private_wrapper_contract.py`，確保保留清單方法存在且可呼叫
56. 驗證結果（P3 第十三批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_mapping_resolver_service.py finance-agent-core/tests/test_sec_xbrl_factory_private_wrapper_contract.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_factory_private_wrapper_contract.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（59 passed）
57. 計畫對齊檢查（P3 第十三批）：
   - 結果：與 refactor plan 一致（wrapper 保留策略從「口頭約定」升級為可測試契約）
   - 偏離：無
58. P3 第十四批治理收尾（façade owner inventory 文檔化）：
   - 新增 `docs/backlog/sec_xbrl_factory_facade_owner_inventory.md`（後續已併入 tracker，獨立文檔移除）
   - 明確列出每個 `BaseFinancialModelFactory` 相容 façade 方法對應 owner 與保留理由
   - 補充 compatibility contract 與偏離檢查規則，降低後續重構漂移
59. 驗證結果（P3 第十四批）：
   - 文檔治理切片，無 runtime 行為變更；沿用上一批（P3 第十三批）測試基線
60. 計畫對齊檢查（P3 第十四批）：
   - 結果：與 refactor plan 一致（façade 收尾所需治理資訊已補齊）
   - 偏離：無
61. P2 第四批增量（domain report parser 命名收斂）：
   - `domain/valuation/report_contract.py` 新增 module docstring，明確其為 domain projection contract，非 canonical owner
   - 新增 `parse_domain_financial_reports(...)` 作為語義化主入口
   - 保留 `parse_financial_reports(...)` 相容 alias，避免既有 import 路徑中斷
   - `param_builder.py` 呼叫切換到新入口 `parse_domain_financial_reports(...)`
62. 驗證結果（P2 第四批增量）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_factory_private_wrapper_contract.py -q` 通過（31 passed）
63. 計畫對齊檢查（P2 第四批增量）：
   - 結果：與 refactor plan 一致（屬於「FinancialReport 責任邊界收斂」範圍）
   - 偏離：無（此批為 P2 in-progress 的預期工作，非臨時偏航）
64. P5 清理前置（移除已無引用 compatibility alias）：
   - `data/ports.py` 移除 `FundamentalArtifactPort` / `fundamental_artifact_port`
   - `data/clients/market_data.py` 移除 `MarketDataClient` / `market_data_client`
   - `data/clients/__init__.py` 移除上述 legacy exports
   - `domain/valuation/report_contract.py` 移除 `parse_financial_reports(...)` alias，僅保留 `parse_domain_financial_reports(...)`
   - `tests/test_fundamental_market_data_client.py` 改用 `MarketDataService`
65. 驗證結果（P5 清理前置）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/ports.py finance-agent-core/src/agents/fundamental/data/clients/market_data.py finance-agent-core/src/agents/fundamental/data/clients/__init__.py finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/tests/test_fundamental_market_data_client.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_sec_xbrl_factory_private_wrapper_contract.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py -q` 通過（37 passed）
66. 計畫對齊檢查（P5 清理前置）：
   - 結果：與 refactor plan 一致，且符合「最終不保留相容層」新決策
   - 偏離：無
67. 決策更新（2026-02-27）：
   - compatibility 僅可短期過渡；最終狀態目標為 **零相容別名/零 legacy shim**
   - 後續切片優先順序：先改 call sites，再移除 alias（避免長期雙命名）
68. P3 第十五批拆分（builder 對 façade class 依賴解耦）：
   - `base_model_debt_builder.py` 移除 `DebtFactoryProtocol` + `base_factory` 參數，改為 `DebtBuilderOps` 顯式函式注入
   - `base_model_income_cashflow_builder.py` 移除 `IncomeCashflowFactoryProtocol` + `base_factory` 參數，改為 `IncomeCashflowOps` 顯式函式注入
   - `factory.py::BaseFinancialModelFactory.create(...)` 改為先組裝 `debt_ops` / `income_cashflow_ops` 再注入 builder
   - 行為保持不變；目標是降低 builder 對 `BaseFinancialModelFactory` 私有 wrapper 形狀耦合
69. 驗證結果（P3 第十五批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_debt_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_income_cashflow_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_factory_private_wrapper_contract.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（59 passed）
70. 計畫對齊檢查（P3 第十五批）：
   - 結果：與 blueprint/P3 一致（`sec_xbrl` orchestration 持續朝 owner-based service wiring 收斂，`factory` 更接近 assembly role）
   - 偏離：無
71. P3 第十六批拆分（ops 綁定改用 owner utility/service）：
   - `factory.py::BaseFinancialModelFactory.create(...)` 的 `debt_ops` 綁定改為 owner utility/service：
     `resolve_total_debt_policy_util`、`relax_statement_filters_util`、`build_total_debt_with_policy_util`、`build_real_estate_debt_combined_ex_leases_util`、`field_source_label_util`、`log_total_debt_diagnostics_util`
   - `income_cashflow_ops` 的計算 callable 改為 direct utility 綁定：
     `calc_subtract_util`、`calc_ratio_util`、`calc_invested_capital_util`、`calc_nopat_util`
   - 保留 `extract_field_fn` 走 `BaseFinancialModelFactory._extract_field`（目前作為 logger-aware 入口），其餘從 wrapper 脫鉤
72. 驗證結果（P3 第十六批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_debt_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_income_cashflow_builder.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_factory_private_wrapper_contract.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（59 passed）
73. 計畫對齊檢查（P3 第十六批）：
   - 結果：與 blueprint/P3 一致（wiring owner 明確化，符合 infrastructure adapter 解耦方向）
   - 偏離：無
74. P3 第十七批拆分（移除 `factory` compatibility contract）：
   - `factory.py` 移除 `BASE_MODEL_FACTORY_COMPAT_WRAPPERS`
   - 移除已不再有 runtime 依賴的 private compatibility wrappers（field resolution aliases、derived aliases、debt policy aliases）
   - `tests/test_sec_xbrl_total_debt_policy.py` 改為直接驗證 owner utility/service（不再透過 `BaseFinancialModelFactory` private wrappers）
   - 刪除 `tests/test_sec_xbrl_factory_private_wrapper_contract.py`（遷移期契約結束）
   - 更新 `sec_xbrl` owner inventory（後續已併入 tracker，獨立文檔移除）
75. 驗證結果（P3 第十七批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_debt_builder.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/base_model_income_cashflow_builder.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（58 passed）
76. 計畫對齊檢查（P3 第十七批）：
   - 結果：與 blueprint/P3 及「最終零相容層」決策一致（compatibility contract 已移除）
   - 偏離：無
77. P2 第五批增量（FinancialReport canonical owner 收斂）：
   - `application/factory.py::run_valuation` 的 `build_params` 呼叫前，加入 `parse_financial_reports_model(...)` canonicalization（context: `valuation.financial_reports`）
   - `domain/valuation/report_contract.py` 移除 extension type 推斷 fallback（不再從 extension keys 反推 type）
   - `domain/valuation/report_contract.py` 調整為「只接受 canonicalized mapping + domain projection」邊界
   - `domain/valuation/param_builder.py` 輸入型別從 `dict` 收斂為 `Mapping`（對齊 canonical payload contract）
78. 驗證結果（P2 第五批增量）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/application/factory.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py -q` 通過（33 passed）
79. 計畫對齊檢查（P2 第五批增量）：
   - 結果：與 blueprint/P2 一致（`interface/contracts.py::FinancialReportModel` 保持 canonical owner，domain parser 僅做 projection）
   - 偏離：無
80. P3 第十八批拆分（`forward_signals_text.py` postprocess owner 外提）：
   - 新增 `data/clients/sec_xbrl/text_signal_postprocess_service.py`
   - 將下列責任從 `forward_signals_text.py` 外提到新 owner module：
     - signal payload validation/serialization（`build_forward_signal_payload`）
     - FLS fast-skip phrase policy（`should_fast_skip_fls_with_phrases`）
     - retrieval debug sentence preview（`preview_sentence`）
     - FinBERT direction review postprocess（`apply_finbert_direction_reviews`）
   - `forward_signals_text.py` 保留 orchestration 與薄 wrapper（依賴注入 `review_signal_direction_with_finbert`、`_clamp`），維持現有 patch/test 路徑與行為
81. 驗證結果（P3 第十八批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/forward_signals_text.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_postprocess_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py -q` 通過（26 passed）
82. 計畫對齊檢查（P3 第十八批）：
   - 結果：與 blueprint/P3/P4 一致（`forward_signals_text.py` 持續朝 thin orchestrator 收斂）
   - 偏離：無
83. P3 第十九批拆分（`forward_signals_text.py` records loading owner 外提）：
   - 新增 `data/clients/sec_xbrl/text_signal_record_loader_service.py`
   - 將 SEC filing text records 載入與 fallback 邏輯（`fetch_records_fn` / default loader）從 `forward_signals_text.py` 外提
   - `forward_signals_text.py` 改由 `load_sec_text_records(...)` 統一取得 records，減少 loader 細節耦合
   - 保留 `forward_signals_text._normalize_text` 與 focus extractor alias，維持既有測試可見路徑
84. 驗證結果（P3 第十九批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/forward_signals_text.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_postprocess_service.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_record_loader_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py -q` 通過（26 passed）
85. 計畫對齊檢查（P3 第十九批）：
   - 結果：與 blueprint/P3/P4 一致（`forward_signals_text.py` 繼續收斂為 orchestrator，loader/postprocess owner 已外提）
   - 偏離：無
86. P3 第二十批拆分（`forward_signals_text.py` diagnostics/log fields owner 外提）：
   - 新增 `data/clients/sec_xbrl/text_signal_diagnostics_service.py`
   - 將 signals/no-signal logging fields 組裝（doc type emission summary、focus/pipeline/finbert diagnostics merge）外提為 `build_text_signal_log_fields(...)`
   - `forward_signals_text.py` 保留 `log_event(...)` 呼叫本身，僅替換 fields builder，確保既有 `patch("...forward_signals_text.log_event")` 測試路徑不變
87. 驗證結果（P3 第二十批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/forward_signals_text.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_diagnostics_service.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_postprocess_service.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_record_loader_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py -q` 通過（26 passed）
88. 計畫對齊檢查（P3 第二十批）：
   - 結果：與 blueprint/P3/P4 一致（`forward_signals_text.py` 已進一步收斂為 thin orchestrator）
   - 偏離：無
89. P3 第二十一批拆分（`forward_signals_text.py` diagnostics owner 再收斂）：
   - `forward_signals_text.py` signals/no-signal 兩段 log fields 組裝改為 `text_signal_diagnostics_service.build_text_signal_log_fields(...)`
   - 仍由 `forward_signals_text.py` 呼叫 `log_event(...)`，保持測試 patch 路徑穩定
   - `forward_signals_text.py` 行數進一步下降（約 `323 -> 279`）
90. 驗證結果（P3 第二十一批）：
   - `ruff check finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/forward_signals_text.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_diagnostics_service.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_postprocess_service.py finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/text_signal_record_loader_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py -q` 通過（26 passed）
91. 計畫對齊檢查（P3 第二十一批）：
   - 結果：與 blueprint/P3/P4 一致（logging/diagnostics assembly owner 明確化）
   - 偏離：無
92. P4 第一批拆分（`param_builder.py` core series/stat helpers 外提）：
   - 新增 `domain/valuation/param_builder_series_service.py`
   - 將 `computed_field`、growth series 建構、觀察值抽取、stddev、missing 去重等純函式從 `param_builder.py` 外提為 owner module
   - `param_builder.py` 改為 import owner functions（行為不變）
   - 修正 model selection error-handling 測試契約：改 patch `load_financial_reports_payload`（符合目前 orchestrator 讀取路徑）
93. 驗證結果（P4 第一批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_series_service.py finance-agent-core/tests/test_error_handling_fundamental.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
94. 計畫對齊檢查（P4 第一批）：
   - 結果：與 blueprint/P4 一致（`param_builder.py` 開始拆出 reusable owner utilities，主檔朝 orchestration 收斂）
   - 偏離：無
95. P4 第二批拆分（`param_builder.py` market/env/time helpers 外提）：
   - 新增 `domain/valuation/param_builder_snapshot_service.py`
   - 將 market snapshot parsing / env config parsing / ISO datetime parsing / metadata merge helpers 從 `param_builder.py` 外提
   - `param_builder.py` 改為 import owner helpers，主檔保留 valuation flow 與 model route orchestration
96. 驗證結果（P4 第二批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_series_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_snapshot_service.py finance-agent-core/tests/test_error_handling_fundamental.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
97. 計畫對齊檢查（P4 第二批）：
   - 結果：與 blueprint/P4 一致（`param_builder.py` 拆分方向持續正確，owner 邊界更清楚）
   - 偏離：無
98. P4 第三批拆分（`param_builder.py` guard/policy + metadata owner 外提）：
   - 新增 `domain/valuation/param_builder_policy_service.py`
   - 新增 `domain/valuation/param_builder_metadata_service.py`
   - 將 `time-alignment guard` 與 `forward-signal adjustment` 政策邏輯從 `param_builder.py` 外提（`param_builder.py` 僅保留 wrapper + orchestration）
   - 將 valuation result metadata (`data_freshness`) 組裝從 `param_builder.py` 外提為獨立 owner
99. 驗證結果（P4 第三批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_metadata_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
100. 計畫對齊檢查（P4 第三批）：
   - 結果：與 blueprint/P4 一致（`param_builder.py` 進一步收斂為 thin orchestrator，policy/metadata owner 邊界清楚）
   - 偏離：無
101. P4 第四批拆分（`param_builder.py` payload/route wrapper 去重）：
   - 在 `param_builder.py` 新增 `_build_param_result(...)`，統一所有 builder payload -> `ParamBuildResult` 組裝流程
   - 在 `param_builder.py` 新增 `_route_latest_only(...)`，移除重複的 latest-only model route wrappers（`ev_revenue`、`ev_ebitda`、`reit_ffo`、`residual_income`、`eva`）
   - `param_builder.py` 進一步減少重複碼與流程噪音，保留 model routing orchestration 可讀性
102. 驗證結果（P4 第四批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
103. 計畫對齊檢查（P4 第四批）：
   - 結果：與 blueprint/P4 一致（`param_builder.py` 主檔持續朝 orchestration-only 收斂，重複 wrapper 責任已集中）
   - 偏離：無
104. P4 第五批拆分（`param_builder.py` context wiring / model registry owner 外提）：
   - 新增 `domain/valuation/param_builder_wiring_service.py`
   - 將 `_get_model_builder` 的 registry 組裝責任外提到 `build_model_builder_registry(...)`
   - 將 `_builder_context` 的 context 建構責任外提到 `build_builder_context(...)` + `BuilderContextDeps`
   - `param_builder.py` 保留 route 決策入口與 wrapper，wiring 組裝移交 owner module
105. 驗證結果（P4 第五批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_wiring_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
106. 計畫對齊檢查（P4 第五批）：
   - 結果：與 blueprint/P4 一致（wiring owner 邊界清楚化，`param_builder.py` 再次瘦身）
   - 偏離：無
107. P4 第六批拆分（`param_builder.py` Monte Carlo + shares override owner 外提）：
   - 新增 `domain/valuation/param_builder_market_controls_service.py`
   - 將 Monte Carlo controls policy（env + snapshot override + assumptions）從 `param_builder.py` 外提到 `resolve_monte_carlo_controls(...)`
   - 將 shares_outstanding 市場覆寫決策從 `param_builder.py` 外提到 `resolve_shares_outstanding(...)`
   - `param_builder.py` 保留薄 wrapper 與 orchestration，行為維持不變
108. 驗證結果（P4 第六批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_market_controls_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_wiring_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
109. 計畫對齊檢查（P4 第六批）：
   - 結果：與 blueprint/P4 一致（`param_builder.py` 剩餘 helper owner 持續收斂，主檔持續瘦身）
   - 偏離：無
110. P4 第七批拆分（`param_builder.py` saas growth blend helper 外提）：
   - 新增 `domain/valuation/param_builder_growth_blend_service.py`
   - 將 saas growth blend / baseline growth extraction 邏輯從 `param_builder.py` 外提到 `build_saas_growth_rates(...)`
   - `param_builder.py` 的 `_build_saas_growth_rates(...)` 改為 thin wrapper，維持既有依賴注入介面
111. 驗證結果（P4 第七批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_growth_blend_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
112. 計畫對齊檢查（P4 第七批）：
   - 結果：與 blueprint/P4 一致（growth blend owner 邊界明確化，`param_builder.py` 進一步瘦身）
   - 偏離：無
113. P4 第八批拆分（`param_builder.py` core ops/report sorting owner 外提）：
   - 新增 `domain/valuation/param_builder_core_ops_service.py`
   - 將 `report_year` + reports sorting、`missing_field`、`ratio`、`subtract`、`repeat_rate`、`value_or_missing` 從 `param_builder.py` 外提到 owner service
   - `param_builder.py` 改為引用 owner functions，去除重複本地實作
114. 驗證結果（P4 第八批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_core_ops_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
115. 計畫對齊檢查（P4 第八批）：
   - 結果：與 blueprint/P4 一致（core ops owner 化，`param_builder.py` 持續瘦身）
   - 偏離：無
116. P2 第六批收斂（`report_contract.py` coercion 分支結構化）：
   - `report_contract.py` 新增 `_resolve_extension_type(...)`，集中 extension type 解析與錯誤條件（`extension` 存在但缺少 canonical type）
   - 將 `_coerce_traceable_field(...)` 分拆為 `_coerce_traceable_field_from_mapping(...)` / `_coerce_traceable_field_from_scalar(...)`
   - 本批以「分支可讀性與責任界線」為目標，未改變既有 coercion 行為（保留 scalar fallback）
117. 驗證結果（P2 第六批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_core_ops_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py -q` 通過（46 passed）
118. 計畫對齊檢查（P2 第六批）：
   - 結果：與 blueprint/P2 一致（domain parser coercion 分支已收斂，canonical owner 仍維持 `interface/contracts.py`）
   - 偏離：無
119. P2 第七批增量（`report_contract` coercion 回歸測試補強）：
   - 新增 `tests/test_report_contract_coercion.py`
   - 覆蓋 `parse_domain_financial_reports(...)` 的三個關鍵行為：
     - scalar field fallback（當前仍允許）
     - extension 存在但缺 canonical type 時的拒絕行為
     - traceable mapping 中 boolean value 的拒絕行為
120. 驗證結果（P2 第七批）：
   - `ruff check finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_core_ops_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_report_contract_coercion.py -q` 通過（49 passed）
121. 計畫對齊檢查（P2 第七批）：
   - 結果：與 blueprint/P2 一致（先鎖行為再做契約收斂，降低 fallback 移除風險）
   - 偏離：無
122. P2 第八批收斂（`report_contract.py` 移除 scalar coercion fallback）：
   - `report_contract._coerce_traceable_field(...)` 移除 `str|int|float` scalar fallback 分支
   - domain parser 收斂為 canonical traceable-object 輸入（`TraceableField` 或 `{value, provenance?}` mapping）
   - 非 canonical scalar 現在會明確拋出 `TypeError: ... must be a traceable object`
123. 驗證結果（P2 第八批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_core_ops_service.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_report_contract_coercion.py -q` 通過（49 passed）
124. 計畫對齊檢查（P2 第八批）：
   - 結果：與 blueprint/P2 及「canonical owner 強約束」方向一致（domain parser compatibility 分支進一步下降）
   - 偏離：無
125. P5 第一批清理（`param_builder.py` top-level wrapper alias 收斂）：
   - 移除 `param_builder.py` 的 top-level wrappers：
     - `_resolve_monte_carlo_controls(...)`
     - `_resolve_shares_outstanding(...)`
     - `_build_saas_growth_rates(...)`
   - 改為在 `_builder_context()` 內建立 local callable，直接綁定 owner services（避免新增對外相容入口）
   - 目標：在不改行為下，降低 compatibility-style wrapper 暴露面
126. 驗證結果（P5 第一批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_report_contract_coercion.py -q` 通過（49 passed）
127. 計畫對齊檢查（P5 第一批）：
   - 結果：與 blueprint/P5 一致（開始移除 legacy wrapper/shim，向零相容層收斂）
   - 偏離：無
128. P5 第二批清理（application -> infrastructure import 收斂）：
   - 新增 `fundamental/infrastructure/*` adapter modules：
     - `infrastructure/artifacts/fundamental_artifact_repository.py`
     - `infrastructure/market_data/market_data_service.py`
     - `infrastructure/sec_xbrl/financial_payload_provider.py`
   - 新增 `infrastructure/` 與子 package `__init__.py`
   - `application/factory.py` 改為從 `infrastructure/*` 匯入 concrete adapters，不再直接依賴 `data/*`
   - `application/orchestrator.py` 的 repository type import 同步切到 `infrastructure/*`
129. 驗證結果（P5 第二批）：
   - `ruff check finance-agent-core/src/agents/fundamental/application/factory.py finance-agent-core/src/agents/fundamental/application/orchestrator.py finance-agent-core/src/agents/fundamental/infrastructure finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_core_ops_service.py finance-agent-core/tests/test_report_contract_coercion.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py -q` 通過（54 passed）
130. 計畫對齊檢查（P5 第二批）：
   - 結果：與 blueprint/Phase 3+4+P5 方向一致（application 不再直接 import legacy `data/*` concrete）
   - 偏離：無
131. P5 第三批清理（`infrastructure` 真 owner 化：artifact + market_data）：
   - `infrastructure/artifacts/fundamental_artifact_repository.py` 改為實作 owner（不再 re-export `data.ports`）
   - `infrastructure/market_data/` 新增 owner contracts/providers/service：
     - `provider_contracts.py`
     - `providers.py`
     - `market_data_service.py`
   - `tests/test_fundamental_market_data_client.py` 改為驗證 `infrastructure.market_data` owner 路徑
   - `tests/test_error_handling_fundamental.py` repository patch 路徑改為 `infrastructure.artifacts...FundamentalArtifactRepository`
132. 驗證結果（P5 第三批）：
   - `ruff check finance-agent-core/src/agents/fundamental/infrastructure finance-agent-core/src/agents/fundamental/application/factory.py finance-agent-core/src/agents/fundamental/application/orchestrator.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py -q` 通過（57 passed）
133. 計畫對齊檢查（P5 第三批）：
   - 結果：與 blueprint/Phase 3+4+P5 一致（application 與 infrastructure 分層收斂持續正向；infrastructure->data transitional import 只剩 sec_xbrl 一處）
   - 偏離：無
134. P5 第四批清理（移除最後一個 `infrastructure -> fundamental.data` 依賴）：
   - 將 `data/clients/sec_xbrl` owner modules 複製到 `infrastructure/sec_xbrl`（含 `mappings/`、`matchers/`、`rules/` 子模組）
   - `infrastructure/sec_xbrl/financial_payload_provider.py` 改為 `from .provider import fetch_financial_payload`
   - `infrastructure/sec_xbrl` 不再依賴 `src.agents.fundamental.data.clients.sec_xbrl.*`
135. 驗證結果（P5 第四批）：
   - `ruff check finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl finance-agent-core/src/agents/fundamental/infrastructure/market_data finance-agent-core/src/agents/fundamental/infrastructure/artifacts finance-agent-core/src/agents/fundamental/application/factory.py finance-agent-core/src/agents/fundamental/application/orchestrator.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py -q` 通過（57 passed）
136. 計畫對齊檢查（P5 第四批）：
   - 結果：與 blueprint/P5 一致（`application` 與 `infrastructure` 對 legacy `fundamental.data` 的直接依賴已清零）
   - 偏離：無
137. P5 第五批清理（移除 `fundamental/data` 無 runtime 依賴的 market/ports legacy 模組）：
   - 刪除 `data/clients/market_data.py`
   - 刪除 `data/clients/market_providers.py`
   - 刪除 `data/ports.py`
   - `data/clients/__init__.py` 移除 market exports，改為僅保留 package 說明（避免匯入時隱式載入已淘汰 market adapters）
138. 驗證結果（P5 第五批）：
   - `ruff check finance-agent-core/src/agents/fundamental/application finance-agent-core/src/agents/fundamental/data finance-agent-core/src/agents/fundamental/infrastructure finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_report_contract_coercion.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py -q` 通過（57 passed）
139. 計畫對齊檢查（P5 第五批）：
   - 結果：與 blueprint/P5 及「零相容層」決策一致（`fundamental/data` 中 market/ports 重複 owner 已實際移除）
   - 偏離：無
140. P5 第六批清理（`sec_xbrl` 測試與 patch 路徑切換到 infrastructure owner）：
   - 將 tests 中 `src.agents.fundamental.data.clients.sec_xbrl.*` 匯入/patch 路徑，批次切換為 `src.agents.fundamental.infrastructure.sec_xbrl.*`
   - `test_sec_xbrl_provider_import_guard.py` 的 banned import 與 internal path skip 規則，改為 `infrastructure/sec_xbrl` 路徑語義
   - 保留 `test_sec_xbrl_legacy_import_guard.py` 對 legacy prefix 的掃描，用於阻擋新舊路徑回流
141. 驗證結果（P5 第六批）：
   - `ruff check`（所有已修改 tests）通過
   - `pytest finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_sec_text_filing_section_selector.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_model_loader_circuit_breaker.py finance-agent-core/tests/test_sec_text_sentence_pipeline.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_filing_fetcher.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_live_golden.py finance-agent-core/tests/test_sec_xbrl_mapping_fallbacks.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_rules_loader.py finance-agent-core/tests/test_sec_xbrl_signal_pattern_catalog.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py -q` 通過（95 passed, 5 skipped）
142. 計畫對齊檢查（P5 第六批）：
   - 結果：與 blueprint/P5 及 tracker 下一步一致（已完成刪除 `data/clients/sec_xbrl/*` 前的 call sites/test patch targets 切換）
   - 偏離：無
143. P5 第七批清理（移除 `fundamental/data/clients/sec_xbrl/*` legacy owner 重複模組）：
   - 刪除 `data/clients/sec_xbrl/` 全目錄（含 `mappings/`、`matchers/`、`rules/` 與其餘 pipeline/mapper/factory modules）
   - 保留 runtime owner 於 `infrastructure/sec_xbrl/*`
   - 保留 `test_sec_xbrl_legacy_import_guard.py` 作為 legacy import 回流防線
144. 驗證結果（P5 第七批）：
   - `ruff check`（所有已修改 tests）通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_legacy_import_guard.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_sec_text_filing_section_selector.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_model_loader_circuit_breaker.py finance-agent-core/tests/test_sec_text_sentence_pipeline.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_filing_fetcher.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_live_golden.py finance-agent-core/tests/test_sec_xbrl_mapping_fallbacks.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_rules_loader.py finance-agent-core/tests/test_sec_xbrl_signal_pattern_catalog.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py -q` 通過（96 passed, 5 skipped）
145. 計畫對齊檢查（P5 第七批）：
   - 結果：與 blueprint/P5 及「零相容層」決策一致（`data/clients/sec_xbrl` legacy owner 已移除）
   - 偏離：無
146. P5 第八批清理（`fundamental.data` 完整退場）：
   - `scripts/benchmark_sec_forward_signals.py`、`scripts/benchmark_fls_backends.py` 改為匯入 `infrastructure/sec_xbrl/*`
   - `tests/test_fundamental_model_selection_projection.py` 改為匯入 `application/report_projection_service.py`
   - 移除整個 `src/agents/fundamental/data/` package（含 `__init__.py`、`mappers.py`、`clients/*`、`ports.py` legacy 殘留）
147. 驗證結果（P5 第八批）：
   - `ruff check`（已修改 scripts + tests）通過
   - `pytest finance-agent-core/tests/test_fundamental_model_selection_projection.py finance-agent-core/tests/test_sec_xbrl_legacy_import_guard.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_sec_text_filing_section_selector.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_model_loader_circuit_breaker.py finance-agent-core/tests/test_sec_text_sentence_pipeline.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_filing_fetcher.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_live_golden.py finance-agent-core/tests/test_sec_xbrl_mapping_fallbacks.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_sec_xbrl_resolver.py finance-agent-core/tests/test_sec_xbrl_rules_loader.py finance-agent-core/tests/test_sec_xbrl_signal_pattern_catalog.py finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py -q` 通過（98 passed, 5 skipped）
148. 計畫對齊檢查（P5 第八批）：
   - 結果：與 blueprint/P5 完全一致（`fundamental/data` 已不再存在，legacy package 清理完成）
   - 偏離：無
149. P5 第九批收尾（blueprint 文檔與實際架構對齊）：
   - 更新 `fundamental_valuation_clean_architecture_refactor_blueprint.md`：
     - scope 從 `fundamental/data` 轉為 `fundamental/infrastructure`
     - 新增狀態更新（`fundamental/data` legacy package 已移除）
     - 同步修正文檔中的 `data -> infrastructure` 映射描述與 shim 策略（最終不保留 shim）
150. 計畫對齊檢查（P5 第九批）：
   - 結果：與 blueprint/P5 一致（文檔與實際目錄結構已回到同一狀態）
   - 偏離：無
151. P5 第十批收尾（import hygiene guard 命名與語義升級）：
   - 刪除 `tests/test_sec_xbrl_legacy_import_guard.py`
   - 新增 `tests/test_fundamental_import_hygiene_guard.py`
   - 檢查規則從「字串掃描特定 sec_xbrl shim import」升級為「AST 層級掃描，禁止任何 `src.agents.fundamental.data*` import」
152. 驗證結果（P5 第十批）：
   - `ruff check finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py -q` 通過（2 passed）
153. 計畫對齊檢查（P5 第十批）：
   - 結果：與 blueprint/P5 一致（guard 測試由歷史導向名稱改為長期可維護的通用 hygiene 規範）
   - 偏離：無
154. P5 收尾盤點（remaining compatibility/shim 掃描）：
   - 以 `rg` 盤點 `src/agents/fundamental/**` 與 `tests/**` 的 `alias/shim/legacy/compatibility` 關鍵字與舊命名入口
   - 結果：除 hygiene guard 測試中的 banned prefix 常量外，未發現 `src.agents.fundamental.data*` runtime import 或既有 compatibility alias 入口
155. 計畫對齊檢查（P5 收尾盤點）：
   - 結果：與「P5 零相容層」目標一致，可把重心切回 P2/P3 後續收斂
   - 偏離：無
156. P2 第九批收斂（`report_contract.py` canonical-only 邊界再收緊）：
   - `_resolve_extension_type(...)` 移除 `industry_type` fallback，extension 解析僅接受 `extension_type`
   - `_coerce_provenance(...)` 改為 strict shape/type 驗證：
     - 保留 `None -> ManualProvenance` 預設
     - 非 object provenance 明確報錯
     - 支援 `type` 欄位並驗證與 payload shape 一致（`XBRL` / `CALCULATION` / `MANUAL`）
     - 不再對未知 provenance mapping 靜默降級，改為 `TypeError`
157. P3 第十九批收尾（`param_builder.py` orchestration wiring 去重）：
   - `param_builder.py` 新增 `@lru_cache(maxsize=1)`：
     - `_builder_context()` 單例化（避免每次 model builder 呼叫重建 deps closures）
     - `_model_builder_registry()` 單例化（避免每次 lookup 重建 registry）
   - `_get_model_builder(...)` 改為使用 cached registry
158. 測試增補（P2 第九批）：
   - `tests/test_report_contract_coercion.py` 新增：
     - `industry_type` 不再充當 extension_type fallback
     - provenance unknown shape 報錯
     - provenance `type` 與 payload shape 不一致報錯
159. 驗證結果（P2 第九批 + P3 第十九批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/tests/test_report_contract_coercion.py` 通過
   - `pytest finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（31 passed）
160. 計畫對齊檢查（P2 第九批 + P3 第十九批）：
   - 結果：與 blueprint/P2 + P3 一致（domain parser compatibility 分支進一步下降，param_builder orchestration 進一步 thin 化）
   - 偏離：無
161. P2 第十批收斂（domain parser 輸入契約去相容分支）：
   - `parse_domain_financial_reports(...)` 輸入型別收斂為 `list[Mapping[str, object]]`
   - 移除對 `FinancialReport` 物件輸入的相容分支（不再接受 domain object 直入 parser）
   - `build_params(...)` 的 `reports_raw` 型別同步收斂為 canonical mapping list
162. 測試增補（P2 第十批）：
   - `tests/test_report_contract_coercion.py` 新增 `test_parse_domain_financial_reports_rejects_domain_object_input`
163. 驗證結果（P2 第十批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/tests/test_report_contract_coercion.py` 通過
   - `pytest finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（32 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py -q` 通過（62 passed）
164. 計畫對齊檢查（P2 第十批）：
   - 結果：與 blueprint/P2「domain parser canonical-only 邊界」一致（compatibility 輸入分支再下降）
   - 偏離：無
165. P2 第十一批收斂（provenance fallback 責任上移到 interface owner）：
   - `report_contract.py::_coerce_provenance(...)` 移除 `None -> ManualProvenance` fallback，改為 strict required provenance（缺省即報錯）
   - `interface/contracts.py::parse_financial_reports_model(...)` 新增 `inject_default_provenance` 開關：
     - 開啟時，對缺省 provenance 的 traceable fields 注入 manual provenance（canonical owner 責任）
     - 關閉時維持既有輸出形狀（不改既有 API serializer 預期）
   - `application/factory.py::run_valuation` 改為 `parse_financial_reports_model(..., inject_default_provenance=True)`，確保 valuation 路徑在 strict domain parser 下可持續運作
166. 測試增補（P2 第十一批）：
   - `tests/test_report_contract_coercion.py` 新增 `test_parse_domain_financial_reports_requires_provenance`
   - `tests/test_fundamental_interface_parsers.py` 新增 `test_parse_financial_reports_model_can_inject_default_provenance`
167. 驗證結果（P2 第十一批）：
   - `ruff check finance-agent-core/src/agents/fundamental/interface/contracts.py finance-agent-core/src/agents/fundamental/application/factory.py finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_interface_parsers.py` 通過
   - `pytest finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（39 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py -q` 通過（63 passed）
168. 計畫對齊檢查（P2 第十一批）：
   - 結果：與 blueprint/P2 一致（domain parser fallback 持續下降，canonical owner 責任更清晰）
   - 偏離：無
169. P2 第十二批收斂（移除 report_contract 的 domain-object compatibility branches）：
   - `report_contract.py::_coerce_traceable_field(...)` 移除 `TraceableField` instance 直接通過分支
   - `report_contract.py::_coerce_provenance(...)` 移除 provenance model instance 直接通過分支
   - domain parser 進一步限定為 canonical JSON mapping projection，不接受 runtime object 混入
170. 測試增補（P2 第十二批）：
   - `tests/test_report_contract_coercion.py` 新增：
     - `test_parse_domain_financial_reports_rejects_traceable_object_input`
     - `test_parse_domain_financial_reports_rejects_provenance_object_input`
171. 驗證結果（P2 第十二批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/tests/test_report_contract_coercion.py` 通過
   - `pytest finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（41 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py -q` 通過（65 passed）
172. 計畫對齊檢查（P2 第十二批）：
   - 結果：與 blueprint/P2 一致（domain parser 已更接近 pure canonical projection，compatibility 分支持續下降）
   - 偏離：無
173. P2 第十三批收斂（canonical owner scalar fallback 收緊）：
   - `interface/contracts.py::TraceableFieldModel._coerce_scalar` 改為 strict object-only：
     - 不再把 scalar 自動包裝成 `{\"value\": ...}`
     - 僅接受 object（或 `None`）作為 traceable field 輸入
   - `tests/test_output_contract_serializers.py` 將仍使用 scalar traceable payload 的測試資料改為 canonical object 形狀
   - `tests/test_fundamental_interface_parsers.py` 新增 `test_parse_financial_reports_model_rejects_scalar_traceable_field`
174. P5 維持性修正（回歸測試捕獲 legacy import 漏網）：
   - `api/server.py` 的 SEC warmup import 從
     `src.agents.fundamental.data.clients.sec_xbrl.*`
     改為
     `src.agents.fundamental.infrastructure.sec_xbrl.*`
175. 驗證結果（P2 第十三批 + P5 維持性修正）：
   - `ruff check finance-agent-core/src/agents/fundamental/interface/contracts.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/api/server.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（21 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（86 passed）
176. 計畫對齊檢查（P2 第十三批 + P5 維持性修正）：
   - 結果：與 blueprint/P2 一致（canonical owner fallback 持續收斂），且符合 P5 維持性監控目標（及時清除漏網 legacy import）
   - 偏離：無
177. P2 第十四批收斂（`FinancialReportModel` 移除 `industry_type -> extension_type` fallback）：
   - `interface/contracts.py::FinancialReportModel._normalize_report` 不再用 `industry_type` 補 `extension_type`
   - `extension` 存在但缺少 `extension_type` 時，改為 strict 報錯：`financial report.extension requires extension_type in canonical payload`
   - 保留 `industry_type`/`extension_type` 衝突檢查，並維持 `industry_type` 最終落值（`industry_type` -> `extension_type` -> `General`）邏輯
178. P2 配套（SEC XBRL canonical adapter 顯式補齊 canonical type）：
   - `infrastructure/sec_xbrl/canonical_mapper.py` 新增 `_normalize_sec_xbrl_report(...)`
   - 對 `SEC XBRL` 輸入做顯式 canonical 化：若有 `extension` 但無 `extension_type`，以可正規化的 `industry_type` 補齊 `extension_type`
   - 若 `extension` 存在且 `industry_type/extension_type` 都不可用，直接報錯（不做 extension keys 推斷）
179. 測試增補（P2 第十四批）：
   - `tests/test_fundamental_interface_parsers.py` 新增 `test_parse_financial_reports_model_rejects_industry_type_extension_fallback`
   - `tests/test_output_contract_serializers.py` 測試資料改為顯式提供 `extension_type`
   - `tests/test_param_builder_canonical_reports.py` canonical fixture 全面顯式提供 `extension_type`
   - `tests/test_sec_text_forward_signals.py` 補強 provider canonical 化驗證：輸入只給 `industry_type` 仍可產出 canonical `extension_type`
180. 驗證結果（P2 第十四批）：
   - `ruff check finance-agent-core/src/agents/fundamental/interface/contracts.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/canonical_mapper.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_sec_text_forward_signals.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（51 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（87 passed）
181. 計畫對齊檢查（P2 第十四批）：
   - 結果：與 blueprint/P2 一致（canonical owner fallback 持續下降），且符合 blueprint `infrastructure/sec/xbrl` 邊界（adapter 顯式輸出 canonical model shape）
   - 偏離：無
182. P3 第二十批收斂（`param_builder` 型別契約抽離與一致化）：
   - 新增 `domain/valuation/param_builder_types.py`，集中 `TraceInput` 與 `MonteCarloControls`
   - `param_builder.py`、`param_builder_wiring_service.py`、`param_builder_market_controls_service.py`、`param_builders/context.py` 改用共用型別契約
   - `param_builders/saas.py`、`bank.py`、`reit.py` 的 `resolve_monte_carlo_controls` callable 型別改為 `MonteCarloControls`，修正原本註記與實際 3-tuple 回傳不一致
   - `param_builders/multiples.py`、`residual_income.py`、`eva.py` 與 `skills/_template/schemas.py` 移除重複 `TraceInput` alias，統一引用 `param_builder_types`
183. 驗證結果（P3 第二十批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_types.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_wiring_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_market_controls_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/context.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/skills/_template/schemas.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_interface_parsers.py -q` 通過（43 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（87 passed）
184. 計畫對齊檢查（P3 第二十批）：
   - 結果：與 blueprint/P3 一致（`param_builder` owner 契約集中、重複 alias 移除、orchestration 與型別契約邊界更清晰）
   - 偏離：無
185. P2 第十五批收斂（SEC XBRL source-side 輸出 canonical `extension_type`）：
   - `infrastructure/sec_xbrl/models.py::FinancialReport` 新增 `extension_type` 欄位（canonical token：`Industrial` / `FinancialServices` / `RealEstate`）
   - `infrastructure/sec_xbrl/report_factory_common_utils.py` 新增 `resolve_extension_type(...)`，統一以 `normalize_extension_type_token(...)` 將既有 industry label 映射為 canonical extension type
   - `infrastructure/sec_xbrl/factory.py::FinancialReportFactory.create_report(...)` 改為在 source 端直接填入 `extension_type`
186. 測試增補（P2 第十五批）：
   - `tests/test_sec_xbrl_extension_industry_routing.py` 新增 `test_create_report_sets_canonical_extension_type`
   - 覆蓋 `Industrial` / `General` / `Financial Services` / `Real Estate` 四種路徑，驗證 `create_report` 產出 canonical `extension_type`
187. 驗證結果（P2 第十五批）：
   - `ruff check finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/models.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/report_factory_common_utils.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/factory.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_fundamental_interface_parsers.py -q` 通過（38 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（96 passed）
188. 計畫對齊檢查（P2 第十五批）：
   - 結果：與 blueprint/P2 一致（`extension_type` canonical owner 由 source 端前移，`sec_xbrl -> canonical json` 邊界更清晰）
   - 偏離：`canonical_mapper.py` 仍保留 `industry_type -> extension_type` fallback（為過渡期與 synthetic payload 相容）；後續批次再移除
189. P2 第十六批收斂（移除 `canonical_mapper` 的 `industry_type -> extension_type` fallback）：
   - `infrastructure/sec_xbrl/canonical_mapper.py::_normalize_sec_xbrl_report(...)` 改為 strict：
     - `extension` 存在時，`extension_type` 必填
     - 不再用 `industry_type` 補齊 `extension_type`
   - 這使 `sec_xbrl -> canonical json` 路徑與 `interface/contracts.py::FinancialReportModel` 的 strict canonical contract 完全對齊
190. 測試增補（P2 第十六批）：
   - `tests/test_sec_text_forward_signals.py`：
     - `test_fetch_financial_payload_normalizes_reports_to_canonical_json` 改為 source payload 顯式提供 `extension_type`
     - 新增 `test_fetch_financial_payload_rejects_extension_without_extension_type`，鎖定 strict contract
191. 驗證結果（P2 第十六批）：
   - `ruff check finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/canonical_mapper.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/models.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/report_factory_common_utils.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/factory.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_fundamental_interface_parsers.py -q` 通過（39 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（97 passed）
192. 計畫對齊檢查（P2 第十六批）：
   - 結果：與 blueprint/P2 +「最終零相容層」目標一致（`extension_type` strict contract 已在 source/adapter/interface 三層對齊）
   - 偏離：無
193. P3 第二十一批收斂（`ParamBuildResult` 契約抽離）：
   - 新增 `domain/valuation/param_builder_contracts.py`，集中：
     - `ParamBuildResult`
     - `ModelParamBuilder`
   - `param_builder.py` 改為引用 contracts 定義，進一步降低 orchestrator 與 data-shape declaration 的耦合
   - 對外相容性維持：現有 `from ...param_builder import ParamBuildResult` 仍可使用（透過 module import re-export）
194. 驗證結果（P3 第二十一批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_contracts.py finance-agent-core/src/agents/fundamental/application/factory.py finance-agent-core/src/agents/fundamental/application/orchestrator.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（56 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（97 passed）
195. 計畫對齊檢查（P3 第二十一批）：
   - 結果：與 blueprint/P3 一致（`param_builder.py` 進一步朝 thin orchestration 收斂）
   - 偏離：無
196. P3 第二十二批收斂（application/test 引用改指向 contracts owner）：
   - `application/factory.py`、`application/orchestrator.py` 與 `tests/test_fundamental_orchestrator_logging.py` 的 `ParamBuildResult` import 改為
     `domain/valuation/param_builder_contracts.py`
   - 目標：降低上層對 `param_builder.py` 主檔的耦合，強化 contracts owner 邊界
197. 驗證結果（P3 第二十二批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_contracts.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/application/factory.py finance-agent-core/src/agents/fundamental/application/orchestrator.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（56 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（97 passed）
198. 計畫對齊檢查（P3 第二十二批）：
   - 結果：與 blueprint/P3 一致（contracts owner 已開始被 application 層直接採用）
   - 偏離：無
199. P3 第二十三批收斂（`_BuilderPayload` protocol 外提到 contracts）：
   - `domain/valuation/param_builder_contracts.py` 新增 `ParamBuilderPayload` protocol
   - `param_builder.py` 移除本地 `_BuilderPayload`，改以 contracts owner 提供的 `ParamBuilderPayload` 做 `_build_param_result(...)` typing
   - `param_builder.py` 進一步降低「流程編排 + 契約宣告」混雜度
200. 驗證結果（P3 第二十三批）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_contracts.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（22 passed）
   - 擴展回歸：`pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals_eval.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_fundamental_market_data_client.py finance-agent-core/tests/test_fundamental_import_hygiene_guard.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_artifact_contract_registry.py -q` 通過（97 passed）
201. 計畫對齊檢查（P3 第二十三批）：
   - 結果：與 blueprint/P3 一致（`param_builder.py` 主檔語義密度進一步下降，contracts owner 邊界更明確）
   - 偏離：無
202. 跨批次經驗沉澱（新增 refactor lessons 文檔）：
   - 新增 `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 內容涵蓋：
     - fundamental refactor 中反覆出現的實作錯誤（owner ambiguity、compatibility 累積、silent fallback、layer leakage、命名責任漂移、型別契約重複、legacy import 回流、邊界測試不足）
     - 對應可執行 guardrails 與輕量 workflow
     - 對「有效性 vs 認知負荷」的實務判斷標準與控制方式
203. 計畫對齊檢查（經驗文檔）：
   - 結果：與 blueprint「跨 agent 可重用命名/責任規範」方向一致，補強後續 refactor 決策一致性
   - 偏離：無
204. 機制升級（Lessons Review Gate 制度化）：
   - `docs/standards/refactor_lessons_and_cross_agent_playbook.md` 新增「每批 refactor 必做 lessons review」章節與記錄規格
   - `fundamental_refactor_execution_tracker.md` 新增：
     - 執行策略中的 mandatory gate
     - 批次記錄模板（`Lessons Review: updated|no_update` + `Reason`）
205. 計畫對齊檢查（Gate 制度化）：
   - 結果：與「持續沉澱跨 agent 經驗並防止規範漂移」目標一致
   - 偏離：無
206. 文檔整併（backlog 瘦身）：
   - `docs/backlog/backend-findings-06022026.md` 已刪除
   - `docs/backlog/frontend-findings-06022026.md` 已刪除
   - `cross_agent_class_naming_and_layer_responsibility_guideline.md` 遷移至 `docs/standards/`
   - `refactor_lessons_and_cross_agent_playbook.md` 遷移至 `docs/standards/`
   - `sec_xbrl_factory_facade_owner_inventory.md` 內容併入 tracker，獨立文檔移除
207. 計畫對齊檢查（文檔整併）：
   - 結果：與 blueprint/tracker 的「降低相容複雜度、提升可維護性」方向一致
   - 偏離：無
208. P5 清理增量（移除 one-hop compatibility alias module）：
   - `application/factory.py` 改為直接引用 `infrastructure/sec_xbrl/provider.py::fetch_financial_payload`
   - 移除 `infrastructure/sec_xbrl/financial_payload_provider.py`（僅 re-export 的過渡 alias）
   - `rg` 確認程式碼不再依賴 `financial_payload_provider` import path
209. 驗證結果（P5 清理增量）：
   - `ruff check finance-agent-core/src/agents/fundamental/application/factory.py` 通過
   - `pytest finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（8 passed）
   - `pytest finance-agent-core/tests/test_sec_xbrl_provider_import_guard.py -q` 通過（1 passed）
210. Standards 同步更新（跨 agent 規範收斂）：
   - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     新增「禁止 one-hop re-export alias module」規則
   - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
     在 compatibility 章節新增具體反模式案例（`financial_payload_provider.py`）
   - `Lessons Review: updated`
   - `Reason: 本批確認 one-hop alias 會造成 owner 歧義與雙路徑維護，需升級為跨 agent 強約束。`
211. 計畫對齊檢查（P5 清理增量 + standards 同步）：
   - 結果：與 blueprint/P5「最終不保留相容層」及 standards 的 owner 單一路徑原則一致
   - 偏離：無
212. P2 收斂增量（`industry_type` canonical token owner 收斂）：
   - `infrastructure/sec_xbrl/factory.py` 保留 legacy industry label 於內部 routing（mapping/override），但輸出 `FinancialReport.industry_type` 統一為 canonical token（與 `extension_type` 對齊）
   - `infrastructure/sec_xbrl/models.py` 更新 `FinancialReport.industry_type` 註解為 canonical token 語義
   - `tests/test_sec_xbrl_extension_industry_routing.py` 補上 assertion：`report.industry_type == report.extension_type`
   - `tests/test_sec_xbrl_live_golden.py` 的預期值改為 canonical token（`FinancialServices` / `RealEstate`）
213. 驗證結果（P2 收斂增量）：
   - `ruff check finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/factory.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/models.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_live_golden.py` 通過
   - `pytest finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_sec_xbrl_forward_signals.py finance-agent-core/tests/test_sec_text_forward_signals.py -q` 通過（33 passed）
214. Standards 同步更新（canonical token 邊界）：
   - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     新增「canonical contract 欄位不得存 source label」規則（`industry_type` 示例）
   - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
     在 owner ambiguity 章節補上 `industry_type` 混入 source label 的反模式與 guardrail
   - `Lessons Review: updated`
   - `Reason: 本批識別到 canonical 欄位與 source routing label 混用會造成 parser 補正依賴，需上升為跨 agent 強約束。`
215. 計畫對齊檢查（P2 收斂增量 + standards 同步）：
   - 結果：與 blueprint/P2「`SEC XBRL` 端直接產生 canonical `extension_type` / 收斂 canonical owner」方向一致，且降低 mapper/parser 補正責任
   - 偏離：無
216. P2 收斂增量（interface contract 移除 `industry_type` legacy 正規化）：
   - `interface/contracts.py::FinancialReportModel._normalize_report`
     不再用 `normalize_extension_type_token(...)` 解析 `industry_type`
   - 新增 `_parse_canonical_industry_type(...)`，僅接受 `General|Industrial|FinancialServices|RealEstate`
   - 保留 `extension_type` 的正規化，避免本批同時擴大到兩個欄位造成風險
217. 測試更新（P2 interface 收斂）：
   - `test_output_contract_serializers.py` 的 `industry_type` fixture 改為 canonical token（`FinancialServices`）
   - 新增 `test_parse_financial_reports_model_rejects_legacy_industry_type_token`
     鎖定 `industry_type="Financial Services"` 會被拒絕
218. 驗證結果（P2 interface 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/interface/contracts.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（34 passed）
219. Standards 同步更新（interface canonical parser 規則）：
   - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     新增「canonical 欄位不可在 interface parser 靜默正規化 source label」規則
   - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
     Hard Rules 新增「interface parser 對 canonical 欄位不得做 source label 正規化」
   - `Lessons Review: updated`
   - `Reason: 本批將 canonical token 規則落到 interface 邊界，需明確強約束避免跨 agent 回歸。`
220. 計畫對齊檢查（P2 interface 收斂 + standards 同步）：
   - 結果：與 blueprint/P2「canonical owner 嚴格化」一致，進一步減少 parser 端 compatibility 負擔
   - 偏離：無
221. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 發現缺口：`extension_type` strict canonical 要求尚未被明確列為同級硬規則
222. Standards 先行更新（`extension_type` strict canonical）：
   - `cross_agent_class_naming_and_layer_responsibility_guideline.md`
     補上 `extension_type` 與 `industry_type` 同級規則（canonical token only；interface parser 不得靜默正規化）
   - `refactor_lessons_and_cross_agent_playbook.md`
     補上 `extension_type` 混入 source label 的反模式描述與 hard rule
223. P2 收斂增量（`extension_type` parser 嚴格化）：
   - `interface/contracts.py`
     新增 `_parse_canonical_extension_type(...)`，`FinancialReportModel` 不再接受 `extension_type="Financial"` 等 legacy token
   - `domain/valuation/report_contract.py`
     `_resolve_extension_type(...)` 改用 strict canonical parser，對非 canonical token 直接報錯
   - `tests/test_output_contract_serializers.py`
     fixture `extension_type` 改為 canonical `FinancialServices`
224. 測試補強（負向案例）：
   - `tests/test_fundamental_interface_parsers.py`
     新增 `test_parse_financial_reports_model_rejects_legacy_extension_type_token`
   - `tests/test_report_contract_coercion.py`
     新增 `test_parse_domain_financial_reports_rejects_legacy_extension_type_token`
225. 驗證結果（P2 extension_type strict）：
   - `ruff check finance-agent-core/src/agents/fundamental/interface/contracts.py finance-agent-core/src/agents/fundamental/domain/valuation/report_contract.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_report_contract_coercion.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_report_contract_coercion.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（46 passed）
226. Lessons Review Gate（本批）：
   - `Lessons Review: updated`
   - `Reason: 透過 pre-check 發現 standards 對 `extension_type` strict 規則不完整；已先補規範再落代碼，防止跨 agent 回歸。`
227. 計畫對齊檢查（P2 extension_type strict + standards 先行）：
   - 結果：與 blueprint/P2「收斂 canonical owner、移除 compatibility 正規化」一致，且符合「每批先 review/更新 standards」作業方式
   - 偏離：無
228. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 發現缺口：尚未明確規定「source label alias 正規化 helper 的 owner 應在 boundary layer」
229. Standards 先行更新（normalization helper owner 規則）：
   - `cross_agent_class_naming_and_layer_responsibility_guideline.md`
     新增「source label alias normalization helper 應只在 infrastructure/interface」
   - `refactor_lessons_and_cross_agent_playbook.md`
     補上「alias 規則放在 domain shared module 會造成 layer 污染」反模式與 guardrail
230. P2 收尾增量（`report_semantics` helper owner 收斂）：
   - 新增 `infrastructure/sec_xbrl/extension_token_normalizer.py`，承接 source label -> canonical token 正規化
   - `infrastructure/sec_xbrl/canonical_mapper.py`、`report_factory_common_utils.py` 改為引用 infrastructure helper
   - `domain/report_semantics.py` 移除：
     - `normalize_extension_type_token`
     - `infer_extension_type_from_extension`
     - 未使用的 extension key 常數
   - `domain/report_semantics.py` 收斂為 canonical base key owner（`FUNDAMENTAL_BASE_KEYS`）
231. 驗證結果（P2 helper owner 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/report_semantics.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/extension_token_normalizer.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/canonical_mapper.py finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/report_factory_common_utils.py` 通過
   - `pytest finance-agent-core/tests/test_sec_text_forward_signals.py finance-agent-core/tests/test_sec_xbrl_extension_industry_routing.py finance-agent-core/tests/test_fundamental_interface_parsers.py finance-agent-core/tests/test_output_contract_serializers.py -q` 通過（46 passed）
232. Lessons Review Gate（本批）：
   - `Lessons Review: updated`
   - `Reason: 本批新增「normalization helper owner 必須在 boundary layer」規則，屬於可跨 agent 復用的架構防呆。`
233. 計畫對齊檢查（P2 helper owner 收斂 + standards 同步）：
   - 結果：與 blueprint/P2「收斂 canonical owner、限縮 compatibility 行為範圍」一致，並降低 domain 層污染風險
   - 偏離：無
234. P5 維持性監控增量（import hygiene guard 補強）：
   - `tests/test_fundamental_import_hygiene_guard.py` 新增
     `test_domain_report_semantics_has_no_source_label_normalizer`
   - 目的：防止 `normalize_extension_type_token` / `infer_extension_type_from_extension`
     回流到 `domain/report_semantics.py`
235. 驗證結果（P5 維持性監控增量）：
   - `ruff check finance-agent-core/tests/test_fundamental_import_hygiene_guard.py` 通過
   - `pytest finance-agent-core/tests/test_fundamental_import_hygiene_guard.py -q` 通過（2 passed）
236. 計畫對齊檢查（P5 guard 補強）：
   - 結果：與「持續維持性監控、防 legacy/邊界回流」目標一致
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 guardrail 的測試化落地，未新增新類型反模式。`
237. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 發現可補強點：尚未明確要求 entrypoint 主檔不得同時承載 registry/cache wiring
238. P3 拆分增量（`param_builder.py` wiring/owner 邊界收斂）：
   - 新增 `domain/valuation/param_builder_model_registry_service.py`
     - 搬移 model registry cache（`_model_builder_registry`）
     - 搬移 builder context cache（`_builder_context`）
     - 搬移各模型 builder wiring（`_build_*_params`）與 `get_model_builder(...)`
   - `domain/valuation/param_builder.py` 收斂為 thin orchestrator：
     - 保留流程入口 `build_params(...)`
     - 保留 time-alignment / forward-signal policy 應用
     - 改由 service 提供 model builder lookup
239. 驗證結果（P3 param_builder wiring 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
240. Standards 同步更新（entrypoint thin-orchestrator 規則）：
   - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     新增「entrypoint 主檔應保持精簡；registry/cache wiring 放 dedicated `*_service.py`」規則
   - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
     在 God Module 章節補上「entrypoint 混入 registry/cache wiring」反模式與對應 guardrail
241. 計畫對齊檢查（P3 wiring 收斂 + standards 同步）：
   - 結果：與 blueprint/P3「`param_builder.py` 收尾、owner 邊界外提」一致
   - 偏離：無
   - `Lessons Review: updated`
   - `Reason: 本批新增跨 agent 可復用規則（entrypoint thin-orchestrator + wiring owner 外提）。`
242. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批「builder 內部 heuristic policy 外提」已被既有 `God Module/owner 拆分` 規則覆蓋，無需新增 standards 條目
243. P3 拆分增量（`bank` builder heuristic owner 收斂）：
   - 新增 `domain/valuation/param_builders/bank_rorwa_policy_service.py`
   - 將 `bank.py` 內 RoRWA/RWA policy helper（數值轉換、中位數、歷史觀察、outlier/discontinuity 判斷）外提
   - `bank.py` 收斂為 payload 組裝流程，保留 `build_bank_payload(...)` 主責
244. 驗證結果（P3 bank heuristic 拆分）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_rorwa_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
245. 計畫對齊檢查（P3 bank heuristic 拆分）：
   - 結果：與 blueprint/P3「分離 payload assembly 與 policy/heuristic owner」一致，持續降低 `param_builders` 主檔語義密度
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有規則（God Module 拆分/owner 外提）的直接落地，未出現新型反模式。`
246. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `saas.py` 的 CAPM/terminal policy owner 外提，已被既有 `entrypoint thin-orchestrator + owner service` 規則覆蓋，無需新增 standards 條目
247. P3/P4 拆分增量（`saas` builder CAPM/terminal policy owner 收斂）：
   - 新增 `domain/valuation/param_builders/saas_capm_policy_service.py`
   - `saas.py` 改為呼叫 `build_saas_capm_terminal_inputs(...)`，移除主檔內重複的：
     - CAPM 參數預設與 WACC clamp policy
     - terminal growth clamp policy
     - 相關常數與 `_clamp` helper
   - `saas.py` 保留 payload/trace 組裝主責，符合 thin orchestration + owner service 邊界
248. 驗證結果（P3/P4 saas CAPM policy 拆分）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_capm_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
249. 計畫對齊檢查（P3/P4 saas CAPM policy 拆分）：
   - 結果：與 blueprint/P3/P4 一致（持續把 `param_builders/*` 的 policy owner 從 payload assembly 主檔抽離）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分規則的直接落地，未發現新的跨 agent 反模式。`
250. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `saas.py` 的 operating-rate heuristic/policy 外提，已被既有 `owner service 拆分 + thin orchestrator` 規則覆蓋，無需新增 standards 條目
251. P3/P4 拆分增量（`saas` builder operating rates policy owner 收斂）：
   - 新增 `domain/valuation/param_builders/saas_operating_rates_policy_service.py`
   - 將 `saas.py` 內下列 heuristic/policy 段落外提為 `build_saas_operating_rates(...)`：
     - operating margin / tax rate / D&A rate（含 default fallback）
     - CapEx rate / SBC rate
     - working-capital rate（含歷史可用性判斷）
   - `saas.py` 保留 payload/trace/result assembly，降低 builder 主檔語義密度
252. 驗證結果（P3/P4 saas operating rates policy 拆分）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_operating_rates_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_capm_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
253. 計畫對齊檢查（P3/P4 saas operating rates policy 拆分）：
   - 結果：與 blueprint/P3/P4 一致（持續把 `param_builders` 的 heuristic/policy owner 從 assembly 主檔抽離）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分策略延續，未出現新的跨 agent 反模式。`
254. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `saas.py` missing/trace assembly owner 外提，已被既有 `owner service + thin orchestrator` 規則覆蓋，無需新增 standards 條目
255. P3/P4 拆分增量（`saas` builder missing/trace assembly owner 收斂）：
   - 新增 `domain/valuation/param_builders/saas_output_assembly_service.py`
   - 將 `saas.py` 內下列組裝責任外提：
     - `collect_saas_missing_metric_names(...)`（growth/margins/tax/da/capex/wc/sbc 缺值判斷）
     - `build_saas_trace_inputs(...)`（trace input payload 組裝）
   - `saas.py` 保留 model payload orchestration 與最終 params 組裝，降低主檔重複與語義密度
256. 驗證結果（P3/P4 saas missing/trace assembly 拆分）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_operating_rates_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_capm_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
257. 計畫對齊檢查（P3/P4 saas missing/trace assembly 拆分）：
   - 結果：與 blueprint/P3/P4 一致（`saas.py` 持續向 thin orchestration 收斂，owner 邊界更清晰）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分規則的直接延伸，未發現新型反模式。`
258. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `bank.py` 的 CAPM/terminal policy owner 外提，已被既有 `owner service + thin orchestrator` 規則覆蓋，無需新增 standards 條目
259. P3/P4 拆分增量（`bank` builder CAPM/terminal policy owner 收斂）：
   - 新增 `domain/valuation/param_builders/bank_capm_policy_service.py`
   - 將 `bank.py` 內下列 policy 外提為 `build_bank_capm_terminal_inputs(...)`：
     - risk_free_rate default policy
     - beta default policy
     - market_risk_premium policy
     - terminal growth default policy
   - `bank.py` 保留 payload/trace assembly 與 RoRWA owner service 串接流程
260. 驗證結果（P3/P4 bank CAPM/terminal policy 拆分）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_capm_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_rorwa_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
261. 計畫對齊檢查（P3/P4 bank CAPM/terminal policy 拆分）：
   - 結果：與 blueprint/P3/P4 一致（`bank.py` 持續分離 policy owner 與 payload assembly）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分策略延續，未出現新型反模式。`
262. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 發現缺口：現有規範尚未明確禁止「由 assumptions/log 字串內容驅動控制流」的脆弱耦合模式
263. Standards 先行更新（Narrative String Coupling 防呆）：
   - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     新增規則：不得以 assumptions/log 文案字串驅動流程分支；應使用 typed decision 欄位
   - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
     新增 2.9 章節（敘述字串驅動控制流）與 hard rule
   - `Lessons Review: updated`
   - `Reason: 本批 pre-check 發現新的可跨 agent 反模式（narrative string coupling），已先固化為 standards 再進入下一步重構。`
264. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `bank.py` 的 missing/trace assembly + shares_source typed decision 收斂，已被既有規則（含 2.9）覆蓋，無需新增 standards 條目
265. P3/P4 拆分增量（`bank` builder output assembly owner 收斂）：
   - 新增 `domain/valuation/param_builders/bank_output_assembly_service.py`
   - 將 `bank.py` 內下列責任外提：
     - `collect_bank_missing_metric_names(...)`（missing 欄位判斷）
     - `build_bank_trace_inputs(...)`（trace input payload 組裝）
     - `resolve_bank_shares_source(...)`（typed decision，不再依賴 assumptions 字串）
   - `bank.py` 改為保留 payload orchestration，移除 narrative string control-flow 判斷
266. 驗證結果（P3/P4 bank output assembly 拆分）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_capm_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_rorwa_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
267. 計畫對齊檢查（P3/P4 bank output assembly 拆分）：
   - 結果：與 blueprint/P3/P4 一致（`bank.py` 持續向 thin orchestration 收斂，並已移除 assumptions 字串驅動分支）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為已建立規則（owner 拆分 + typed decision）的直接落地，未發現新型反模式。`
268. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `bank.py` RoRWA 主邏輯外提已被既有規則覆蓋（owner 拆分 + typed decision），無需新增 standards 條目
269. P3/P4 拆分增量（`bank` builder RoRWA 主邏輯 owner 收斂）：
   - `domain/valuation/param_builders/bank_rorwa_policy_service.py` 新增
     `build_bank_rorwa_intensity(...)`
   - 將 `bank.py` 內 RoRWA 主邏輯（latest/baseline 比較、outlier/discontinuity fallback、default policy）外提到 owner service
   - `bank.py` 改為薄調用：只保留 `build_bank_rorwa_intensity(...)` orchestration wiring
270. 驗證結果（P3/P4 bank RoRWA 主邏輯外提）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_rorwa_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_capm_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
271. 計畫對齊檢查（P3/P4 bank RoRWA 主邏輯外提）：
   - 結果：與 blueprint/P3/P4 一致（`bank.py` 進一步向 orchestration-only 收斂，RoRWA policy owner 邊界明確化）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分策略延續，未出現新的跨 agent 反模式。`
272. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `bank.py` params/rationale assembly owner 收斂已被既有規則覆蓋，無需新增 standards 條目
273. P3/P4 拆分增量（`bank` builder params/rationale assembly 收斂）：
   - `domain/valuation/param_builders/bank_output_assembly_service.py` 新增 `build_bank_params(...)`
   - `bank.py` 的 `params` 與 `rationale` 組裝改為 owner service 生成
   - `bank.py` 主檔持續收斂為流程拼裝，降低 output payload 細節耦合
274. 驗證結果（P3/P4 bank params/rationale assembly 拆分）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_rorwa_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_capm_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
275. 計畫對齊檢查（P3/P4 bank params/rationale assembly 拆分）：
   - 結果：與 blueprint/P3/P4 一致（`bank.py` output owner 邊界完整化，主檔更接近 orchestration-only）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分規則的直接延伸，未出現新的跨 agent 反模式。`
276. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `saas.py` params/rationale assembly owner 收斂已被既有規則覆蓋，無需新增 standards 條目
277. P3/P4 拆分增量（`saas` builder params/rationale assembly 收斂）：
   - `domain/valuation/param_builders/saas_output_assembly_service.py` 新增：
     - `build_saas_rationale(...)`
     - `build_saas_params(...)`
   - `saas.py` 的 `rationale` 與 `params` 組裝改為 owner service 生成
   - `saas.py` 主檔持續收斂為流程拼裝，降低 output payload 細節耦合
278. 驗證結果（P3/P4 saas params/rationale assembly 拆分）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_operating_rates_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_capm_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
279. 計畫對齊檢查（P3/P4 saas params/rationale assembly 拆分）：
   - 結果：與 blueprint/P3/P4 一致（`saas.py` output owner 邊界完整化，主檔更接近 orchestration-only）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分規則延伸，未出現新的跨 agent 反模式。`
280. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批跨 builder 共用 owner（shares_source）統整已被既有規則覆蓋，無需新增 standards 條目
281. P3/P4 拆分增量（跨 builder `shares_source` 共用 owner 統整）：
   - 新增 `domain/valuation/param_builders/shares_source_service.py`（`resolve_shares_source(...)`）
   - `bank_output_assembly_service.py::resolve_bank_shares_source(...)` 改為委派共用 service
   - `saas_output_assembly_service.py` 新增 `resolve_saas_shares_source(...)` 並委派共用 service
   - `saas.py` 移除本地 `market_shares` 判斷，改調用 owner service（行為保持不變）
282. 驗證結果（P3/P4 跨 builder shares_source 統整）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/shares_source_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py -q` 通過（17 passed）
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
283. 計畫對齊檢查（P3/P4 跨 builder shares_source 統整）：
   - 結果：與 blueprint/P3/P4 一致（跨 builder 重複決策已收斂到單一 owner，維持薄主檔方向）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner consolidation 策略落地，未新增新型反模式。`
284. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批擴展 shares_source 共用 owner 到其他 builders，已被既有規則覆蓋，無需新增 standards 條目
285. P3/P4 拆分增量（跨 builder shares_source 收斂擴展）：
   - `residual_income.py`、`eva.py`、`reit.py`、`multiples.py` 的 `shares_source` 判斷改為共用 `resolve_shares_source(...)`
   - 移除各檔案內重複 `market_shares` 判斷片段，保留既有語義（`filing` fallback）
   - `shares_source_service.py` 成為跨 builder 單一 owner，降低重複與漂移風險
286. 驗證結果（P3/P4 shares_source 收斂擴展）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/shares_source_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
287. 計畫對齊檢查（P3/P4 shares_source 收斂擴展）：
   - 結果：與 blueprint/P3/P4 一致（跨 builder 重複決策持續收斂，避免 control-flow 文案耦合回流）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 cross-builder consolidation 的擴展落地，未引入新的反模式。`
288. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批聚焦 `trace_inputs/params` 共用 owner 收斂（capital-structure + base params），已被既有 `owner service + thin orchestrator` 規則覆蓋，無需新增 standards 條目
289. P3/P4 拆分增量（跨 builder `trace_inputs/params` 共用 owner 收斂）：
   - 新增 `domain/valuation/param_builders/common_output_assembly_service.py`：
     - `build_base_params(...)`
     - `build_capital_structure_trace_inputs(...)`
     - `build_capital_structure_params(...)`
   - `eva.py`、`reit.py`、`multiples.py` 的 capital-structure `trace_inputs/params` 改為委派共用 owner
   - `residual_income.py` 的 `ticker/rationale` base params 改為委派共用 owner
   - 保持既有輸出語義與 fallback 行為不變，降低跨 builder 重複與字串漂移風險
290. 驗證結果（P3/P4 trace_inputs/params 共用 owner 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/common_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
291. 計畫對齊檢查（P3/P4 trace_inputs/params 共用 owner 收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨 builder 重複 output assembly 已集中到單一 owner service，主檔維持 orchestration-only 方向）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner consolidation 策略的直接延伸，未新增新型反模式。`
292. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `multiples.py` 同檔重複去重（`ev_revenue` / `ev_ebitda`）已被既有 `owner helper + thin orchestrator` 規則覆蓋，無需新增 standards 條目
293. P3/P4 拆分增量（`multiples.py` 雙路徑重複收斂）：
   - `multiples.py` 新增同檔 owner helper：`_build_ev_multiple_payload(...)` + `EvMultipleTargetSpec`
   - `build_ev_revenue_payload(...)` / `build_ev_ebitda_payload(...)` 改為只負責 target-spec wiring
   - 共用流程（shares/capital-structure/value-or-missing/params+trace 組裝）集中於 helper，避免跨檔過度抽象
294. 驗證結果（P3/P4 `multiples.py` 雙路徑收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
295. 計畫對齊檢查（P3/P4 `multiples.py` 雙路徑收斂）：
   - 結果：與 blueprint/P3/P4 一致（重複流程收斂到單一 owner helper，公開 builder 維持薄 wiring）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有重複收斂規則的落地，未發現新的跨 agent 反模式。`
296. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `reit.py` helper/assembly owner 抽離已被既有 `owner service + thin orchestrator` 規則覆蓋，無需新增 standards 條目
297. P3/P4 拆分增量（`reit.py` helper/assembly owner 收斂）：
   - 新增 `domain/valuation/param_builders/reit_ffo_policy_service.py`，將 `ffo_multiple` 決策邏輯外提為 `resolve_reit_ffo_multiple(...)`
   - 新增 `domain/valuation/param_builders/reit_output_assembly_service.py`，集中：
     - `build_reit_trace_inputs(...)`
     - `build_reit_params(...)`
   - `reit.py` 移除本地 `_resolve_ffo_multiple` 與 output payload 組裝細節，保留流程拼裝與 owner service wiring
298. 驗證結果（P3/P4 `reit.py` owner 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit_ffo_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
299. 計畫對齊檢查（P3/P4 `reit.py` owner 收斂）：
   - 結果：與 blueprint/P3/P4 一致（`reit.py` 持續向 orchestration-only 收斂，policy/output owner 邊界更清晰）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分策略延伸，未發現新型跨 agent 反模式。`
300. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `reit.py` fallback heuristic policy owner 抽離，已被既有 `owner policy + thin orchestrator` 規則覆蓋，無需新增 standards 條目
301. P3/P4 拆分增量（`reit.py` fallback policy owner 收斂）：
   - 新增 `domain/valuation/param_builders/reit_fallback_policy_service.py`：
     - `resolve_reit_depreciation_for_affo(...)`
     - `resolve_reit_maintenance_capex_ratio(...)`
   - `reit.py` 將 `depreciation_and_amortization` 與 `maintenance_capex_ratio` 的 fallback policy 改為委派 owner service
   - `reit.py` 進一步收斂為 orchestration + owner wiring，保持行為與輸出欄位不變
302. 驗證結果（P3/P4 `reit.py` fallback policy 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit_fallback_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit_ffo_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
303. 計畫對齊檢查（P3/P4 `reit.py` fallback policy 收斂）：
   - 結果：與 blueprint/P3/P4 一致（fallback heuristics 已集中到 policy owner，`reit.py` 主檔語義密度持續下降）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分策略延伸，未出現新型跨 agent 反模式。`
304. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `eva.py` / `residual_income.py` output assembly owner 抽離，已被既有 `owner service + thin orchestrator` 規則覆蓋，無需新增 standards 條目
305. P3/P4 拆分增量（`eva.py` / `residual_income.py` output assembly 收斂）：
   - 新增 `domain/valuation/param_builders/eva_output_assembly_service.py`：
     - `extend_eva_missing_fields(...)`
     - `build_eva_trace_inputs(...)`
     - `build_eva_params(...)`
   - 新增 `domain/valuation/param_builders/residual_income_output_assembly_service.py`：
     - `extend_residual_income_missing_fields(...)`
     - `build_residual_income_trace_inputs(...)`
     - `build_residual_income_params(...)`
   - `eva.py` / `residual_income.py` 改為委派 owner service，主檔保留流程與 policy wiring，不改輸出欄位與文案
306. 驗證結果（P3/P4 `eva/residual_income` output assembly 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
307. 計畫對齊檢查（P3/P4 `eva/residual_income` output assembly 收斂）：
   - 結果：與 blueprint/P3/P4 一致（`eva.py` / `residual_income.py` 持續向 orchestration-only 收斂，output owner 邊界更清晰）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner 拆分策略延伸，未發現新型跨 agent 反模式。`
308. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `eva.py` invested-capital derivation policy owner 抽離，已被既有 `owner policy + thin orchestrator` 規則覆蓋，無需新增 standards 條目
309. P3/P4 拆分增量（`eva.py` invested-capital policy owner 收斂）：
   - 新增 `domain/valuation/param_builders/eva_invested_capital_policy_service.py`：
     - `resolve_eva_invested_capital_field(...)`
   - `eva.py` 將 invested-capital 的 missing/computed 分支改為委派 owner service
   - 保持公式、missing 訊息、provenance inputs 與輸出欄位不變
310. 驗證結果（P3/P4 `eva.py` invested-capital policy 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva_invested_capital_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
311. 計畫對齊檢查（P3/P4 `eva.py` invested-capital policy 收斂）：
   - 結果：與 blueprint/P3/P4 一致（`eva.py` policy owner 更清晰，主檔語義密度下降）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 owner policy 拆分策略的直接延伸，未出現新型跨 agent 反模式。`
312. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `value_or_missing + current_price` 重複收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
313. P3/P4 拆分增量（`eva.py` / `residual_income.py` value extraction 收斂）：
   - 新增 `domain/valuation/param_builders/value_extraction_service.py`：
     - `extract_required_values(...)`
     - `extract_market_value(...)`
   - `eva.py` 與 `residual_income.py` 以共用 service 收斂 `value_or_missing` 批次取值與 `current_price` 讀取
   - 保持 missing 行為、欄位命名與輸出 payload 不變
314. 驗證結果（P3/P4 value extraction 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
315. 計畫對齊檢查（P3/P4 value extraction 收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨 builder 重複取值邏輯進一步收斂，主檔維持 orchestration-only 方向）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未發現新的跨 agent 反模式。`
316. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `multiples.py` / `reit.py` 對接 `value_extraction_service` 屬既有 consolidation 規則範圍，無需新增 standards 條目
317. P3/P4 拆分增量（`multiples.py` / `reit.py` value extraction 對接）：
   - `multiples.py` 在 `_build_ev_multiple_payload(...)` 導入 `extract_required_values(...)` 與 `extract_market_value(...)`
   - `reit.py` 在 `build_reit_payload(...)` 導入 `extract_required_values(...)` 與 `extract_market_value(...)`
   - 保持欄位語義、missing 行為與輸出 payload 不變，僅收斂重複取值流程
318. 驗證結果（P3/P4 `multiples/reit` value extraction 對接）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
319. 計畫對齊檢查（P3/P4 `multiples/reit` value extraction 對接）：
   - 結果：與 blueprint/P3/P4 一致（共用取值 owner 已擴展至更多 builders，未增加語義負擔）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略擴展，未出現新型跨 agent 反模式。`
320. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `bank.py` / `saas.py` 對接 `value_extraction_service` 屬既有 consolidation 規則範圍，無需新增 standards 條目
321. P3/P4 拆分增量（`bank.py` / `saas.py` value extraction 對接）：
   - `bank.py` 在 `build_bank_payload(...)` 導入 `extract_required_values(...)` 與 `extract_market_value(...)`
   - `saas.py` 在 `build_saas_payload(...)` 導入 `extract_required_values(...)` 與 `extract_market_value(...)`
   - 保持欄位語義、missing 行為與輸出 payload 不變，僅收斂重複取值流程
322. 驗證結果（P3/P4 `bank/saas` value extraction 對接）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
323. 計畫對齊檢查（P3/P4 `bank/saas` value extraction 對接）：
   - 結果：與 blueprint/P3/P4 一致（共用取值 owner 已覆蓋核心 builder 主線，主檔維持 orchestration-only 方向）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略擴展，未出現新的跨 agent 反模式。`
324. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 output assembly services 的 missing-collection 去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
325. P3/P4 拆分增量（`*_output_assembly_service.py` missing 收斂）：
   - 新增 `domain/valuation/param_builders/missing_metrics_service.py`：
     - `collect_missing_metric_names(...)`
     - `extend_missing_fields(...)`
   - `bank_output_assembly_service.py` / `saas_output_assembly_service.py` 的 missing collector 改為委派共用 service
   - `eva_output_assembly_service.py` / `residual_income_output_assembly_service.py` 的 missing extend 改為委派共用 service
   - 保持 missing 欄位名稱與判定語義不變
326. 驗證結果（P3/P4 output assembly missing 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/missing_metrics_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
327. 計畫對齊檢查（P3/P4 output assembly missing 收斂）：
   - 結果：與 blueprint/P3/P4 一致（output owner 層重複進一步收斂，未引入過度抽象）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未發現新的跨 agent 反模式。`
328. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `build_*_params` base payload 去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
329. P3/P4 拆分增量（`build_*_params` base payload 收斂：bank/saas）：
   - `bank_output_assembly_service.py::build_bank_params(...)` 改為委派 `build_base_params(...)` 組裝 `ticker/rationale`
   - `saas_output_assembly_service.py::build_saas_params(...)` 改為委派 `build_base_params(...)` + `build_capital_structure_params(...)`
   - 保持欄位語義、缺值行為與輸出 payload 不變
330. 驗證結果（P3/P4 `build_*_params` base payload 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
331. 計畫對齊檢查（P3/P4 `build_*_params` base payload 收斂）：
   - 結果：與 blueprint/P3/P4 一致（共用 output owner 進一步覆蓋核心 builder，主檔維持 orchestration-only）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
332. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `saas_output_assembly_service` trace-input assembly 去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
333. P3/P4 拆分增量（`saas_output_assembly_service.py` trace-input assembly 收斂）：
   - `build_saas_trace_inputs(...)` 的 capital structure trace inputs（`cash/total_debt/preferred_stock/shares_outstanding`）改為委派 `build_capital_structure_trace_inputs(...)`
   - 保持 provenance、欄位鍵名與輸出 payload 不變
334. 驗證結果（P3/P4 `saas_output_assembly_service` trace-input assembly 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
335. 計畫對齊檢查（P3/P4 `saas_output_assembly_service` trace-input assembly 收斂）：
   - 結果：與 blueprint/P3/P4 一致（trace-input owner 更集中，維持 thin assembly 邊界）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 output assembly consolidation 的直接延伸，未發現新的跨 agent 反模式。`
336. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 `sec_xbrl` 預設 rationale 去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
337. P3/P4 拆分增量（`sec_xbrl` 預設 rationale 收斂）：
   - `common_output_assembly_service.py` 新增：
     - `SEC_XBRL_RATIONALE`
     - `build_sec_xbrl_base_params(...)`
   - 以下 builder 改為委派 `build_sec_xbrl_base_params(...)`，移除重複字串與重複 base 組裝：
     - `bank_output_assembly_service.py`
     - `eva_output_assembly_service.py`
     - `residual_income_output_assembly_service.py`
     - `reit_output_assembly_service.py`
     - `multiples.py`
   - 保持欄位語義與輸出 payload 不變
338. 驗證結果（P3/P4 `sec_xbrl` 預設 rationale 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/common_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
339. 計畫對齊檢查（P3/P4 `sec_xbrl` 預設 rationale 收斂）：
   - 結果：與 blueprint/P3/P4 一致（output owner 進一步集中，減少 narrative string duplication）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 output assembly consolidation 的延伸，未出現新的跨 agent 反模式。`
340. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 equity-value/shares trace 組裝收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
341. P3/P4 拆分增量（equity-value/shares trace 組裝收斂）：
   - `common_output_assembly_service.py` 新增：
     - `build_equity_value_params(...)`
     - `build_shares_trace_inputs(...)`
   - `bank_output_assembly_service.py`：
     - `build_bank_trace_inputs(...)` 的 `shares_outstanding` 改為委派 `build_shares_trace_inputs(...)`
     - `build_bank_params(...)` 的 `shares_outstanding/current_price` 改為委派 `build_equity_value_params(...)`
   - `residual_income_output_assembly_service.py`：
     - `build_residual_income_trace_inputs(...)` 的 `shares_outstanding` 改為委派 `build_shares_trace_inputs(...)`
     - `build_residual_income_params(...)` 的 `shares_outstanding/current_price` 改為委派 `build_equity_value_params(...)`
   - 保持欄位語義、provenance 與輸出 payload 不變
342. 驗證結果（P3/P4 equity-value/shares trace 組裝收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/common_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
343. 計畫對齊檢查（P3/P4 equity-value/shares trace 組裝收斂）：
   - 結果：與 blueprint/P3/P4 一致（shared output assembly owner 擴展，主檔維持 orchestration-only）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 output assembly consolidation 的直接延伸，未發現新的跨 agent 反模式。`
344. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 CAPM trace-input owner 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
345. P3/P4 拆分增量（CAPM trace-input owner 收斂：bank/saas）：
   - `common_output_assembly_service.py` 新增 `build_capm_market_trace_inputs(...)`
   - `bank_output_assembly_service.py::build_bank_trace_inputs(...)` 改為委派共用 helper 組裝：
     - `risk_free_rate`
     - `beta`
     - `market_risk_premium`
   - `saas_output_assembly_service.py::build_saas_trace_inputs(...)` 改為委派共用 helper 組裝同三個欄位
   - 保持欄位鍵名、provenance author 與描述字串不變（bank 與 saas 各自描述仍分別保留）
346. 驗證結果（P3/P4 CAPM trace-input owner 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/common_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
347. 計畫對齊檢查（P3/P4 CAPM trace-input owner 收斂）：
   - 結果：與 blueprint/P3/P4 一致（trace-input owner 更集中，重複 TraceableField 組裝下降）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 output assembly consolidation 的延伸，未出現新的跨 agent 反模式。`
348. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 DCF variant payload 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
349. P3/P4 拆分增量（DCF variant payload 收斂）：
   - 新增 `dcf_variant_payload_service.py`：
     - `build_dcf_variant_payload(...)`
   - `dcf_standard.py` 與 `dcf_growth.py` 改為委派共用 service，移除重複的：
     - `params["model_variant"]` 注入
     - assumptions variant 訊息附加
     - `SaasBuildPayload` 回組裝樣板
   - 保持 `model_variant` 值與 assumptions 字串內容不變
350. 驗證結果（P3/P4 DCF variant payload 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_variant_payload_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_standard.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_growth.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
351. 計畫對齊檢查（P3/P4 DCF variant payload 收斂）：
   - 結果：與 blueprint/P3/P4 一致（builder 主檔樣板下降，owner service 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
352. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 registry 的 DCF wrapper 去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
353. P3/P4 拆分增量（registry DCF wrapper 收斂）：
   - `param_builder_model_registry_service.py` 新增 `_build_dcf_variant_params(...)`
   - `_build_dcf_standard_params(...)` / `_build_dcf_growth_params(...)` 改為委派共用 helper
   - 共用 helper 內保留 variant-specific deps dispatch：
     - `dcf_standard -> context.dcf_standard_deps()`
     - `dcf_growth -> context.dcf_growth_deps()`
   - 保持輸出 payload 與 registry 對外介面不變
354. 驗證結果（P3/P4 registry DCF wrapper 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
355. 計畫對齊檢查（P3/P4 registry DCF wrapper 收斂）：
   - 結果：與 blueprint/P3/P4 一致（orchestration 樣板下降，owner 邊界更清晰）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
356. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 registry 的 EV multiples wrapper 去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
357. P3/P4 拆分增量（registry EV multiples wrapper 收斂）：
   - `param_builder_model_registry_service.py` 新增 `_build_ev_multiple_params(...)`
   - `_build_ev_revenue_params(...)` / `_build_ev_ebitda_params(...)` 改為委派共用 helper
   - 共用 helper 內保留 variant-specific payload dispatch：
     - `ev_revenue -> build_ev_revenue_payload(...)`
     - `ev_ebitda -> build_ev_ebitda_payload(...)`
   - 保持輸出 payload 與 registry 對外介面不變
358. 驗證結果（P3/P4 registry EV multiples wrapper 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
359. 計畫對齊檢查（P3/P4 registry EV multiples wrapper 收斂）：
   - 結果：與 blueprint/P3/P4 一致（orchestration 樣板進一步下降，wrapper owner 更清晰）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
360. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 registry 的 single-report wrapper 去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
361. P3/P4 拆分增量（registry single-report wrapper 收斂）：
   - `param_builder_model_registry_service.py` 新增 `_build_single_report_params(...)`
   - `_build_reit_ffo_params(...)` / `_build_residual_income_params(...)` / `_build_eva_params(...)` 改為委派共用 helper
   - 共用 helper 內保留 variant-specific payload dispatch：
     - `reit_ffo -> build_reit_payload(...)`
     - `residual_income -> build_residual_income_payload(...)`
     - `eva -> build_eva_payload(...)`
   - 保持輸出 payload 與 registry 對外介面不變
362. 驗證結果（P3/P4 registry single-report wrapper 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
363. 計畫對齊檢查（P3/P4 registry single-report wrapper 收斂）：
   - 結果：與 blueprint/P3/P4 一致（orchestration 樣板進一步下降，single-report wrapper owner 更清晰）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
364. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 registry 的 multi-report wrapper 去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
365. P3/P4 拆分增量（registry multi-report wrapper 收斂）：
   - `param_builder_model_registry_service.py` 新增 `_build_multi_report_params(...)`
   - `_build_saas_params(...)` / `_build_bank_params(...)` 改為委派共用 helper
   - 共用 helper 內保留 variant-specific payload dispatch：
     - `saas -> build_saas_payload(...)`
     - `bank -> build_bank_payload(...)`
   - 保持輸出 payload 與 registry 對外介面不變
366. 驗證結果（P3/P4 registry multi-report wrapper 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
367. 計畫對齊檢查（P3/P4 registry multi-report wrapper 收斂）：
   - 結果：與 blueprint/P3/P4 一致（orchestration 樣板進一步下降，multi-report wrapper owner 更清晰）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
368. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 DCF deps 類型去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
369. P3/P4 拆分增量（DCF deps 類型收斂）：
   - `dcf_variant_payload_service.py` 新增共用 dataclass：`DCFVariantBuilderDeps`
   - `dcf_standard.py`：
     - `DCFStandardBuilderDeps` 改為 alias 到 `DCFVariantBuilderDeps`
   - `dcf_growth.py`：
     - `DCFGrowthBuilderDeps` 改為 alias 到 `DCFVariantBuilderDeps`
   - 保持既有對外名稱（`DCFStandardBuilderDeps` / `DCFGrowthBuilderDeps`）與 payload 行為不變
370. 驗證結果（P3/P4 DCF deps 類型收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_variant_payload_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_standard.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_growth.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
371. 計畫對齊檢查（P3/P4 DCF deps 類型收斂）：
   - 結果：與 blueprint/P3/P4 一致（重複型別定義下降，owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
372. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 DCF deps 供應路徑去重屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
373. P3/P4 拆分增量（DCF deps 供應路徑收斂）：
   - `context.py` 新增 `dcf_variant_deps(...)`（共用 DCF deps owner）
   - `dcf_standard_deps(...)` / `dcf_growth_deps(...)` 改為委派 `dcf_variant_deps(...)`
   - `param_builder_model_registry_service.py::_build_dcf_variant_params(...)` 改為使用單一 `dcf_deps = context.dcf_variant_deps()`，移除雙路徑 deps dispatch 重複
   - 保持 builder 入口與輸出 payload 不變
374. 驗證結果（P3/P4 DCF deps 供應路徑收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/context.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
375. 計畫對齊檢查（P3/P4 DCF deps 供應路徑收斂）：
   - 結果：與 blueprint/P3/P4 一致（deps owner 更集中，registry 重複 dispatch 降低）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
376. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 registry variant dispatch mapping 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
377. P3/P4 拆分增量（registry variant dispatch mapping 收斂）：
   - `param_builder_model_registry_service.py`：
     - `_build_dcf_variant_params(...)`
     - `_build_ev_multiple_params(...)`
     - `_build_multi_report_params(...)`
     - `_build_single_report_params(...)`
   - 以上四個 helper 由 `if/elif` 分支改為 explicit variant-to-builder/deps mapping dispatch
   - 保持 variant 型別約束（`Literal[...]`）、輸出 payload 與對外介面不變
378. 驗證結果（P3/P4 registry variant dispatch mapping 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
379. 計畫對齊檢查（P3/P4 registry variant dispatch mapping 收斂）：
   - 結果：與 blueprint/P3/P4 一致（orchestration 分支樣板下降，variant owner 更清晰）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
380. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批移除未使用 DCF deps wrapper 屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
381. P3/P4 拆分增量（移除未使用 DCF deps wrapper）：
   - `context.py` 刪除未使用方法：
     - `dcf_standard_deps(...)`
     - `dcf_growth_deps(...)`
   - 保留 `dcf_variant_deps(...)` 為唯一 DCF deps owner 入口
   - 清理對應未使用 import（`DCFStandardBuilderDeps` / `DCFGrowthBuilderDeps`）
382. 驗證結果（P3/P4 移除未使用 DCF deps wrapper）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/context.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
383. 計畫對齊檢查（P3/P4 移除未使用 DCF deps wrapper）：
   - 結果：與 blueprint/P3/P4 一致（內部 deps API 噪音下降，owner 邊界更單一）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
384. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 registry mapping owner 提升屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
385. P3/P4 拆分增量（registry mapping owner 提升）：
   - `param_builder_model_registry_service.py` 新增模組常量 mapping：
     - `_DCF_VARIANT_PAYLOAD_BUILDERS`
     - `_EV_MULTIPLE_PAYLOAD_BUILDERS`
     - `_MULTI_REPORT_PAYLOAD_BUILDERS`
     - `_MULTI_REPORT_DEPS_RESOLVERS`
     - `_SINGLE_REPORT_PAYLOAD_BUILDERS`
     - `_SINGLE_REPORT_DEPS_RESOLVERS`
   - `_build_dcf_variant_params(...)` / `_build_ev_multiple_params(...)` / `_build_multi_report_params(...)` / `_build_single_report_params(...)` 改為使用模組常量 mapping dispatch
   - 保持 variant 型別約束、輸出 payload 與對外介面不變
386. 驗證結果（P3/P4 registry mapping owner 提升）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
387. 計畫對齊檢查（P3/P4 registry mapping owner 提升）：
   - 結果：與 blueprint/P3/P4 一致（variant owner 更集中，函式內樣板進一步下降）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
388. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 DCF variant builder 流程收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
389. P3/P4 拆分增量（DCF variant builder 流程收斂）：
   - `dcf_variant_payload_service.py` 新增 `build_dcf_variant_model_payload(...)`
   - `dcf_standard.py` / `dcf_growth.py` 改為委派 `build_dcf_variant_model_payload(...)`，移除兩檔重複的 `build_saas_payload(...)` 組裝樣板
   - 保持 `model_variant` 值、assumptions 字串與輸出 payload 不變
390. 驗證結果（P3/P4 DCF variant builder 流程收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_variant_payload_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_standard.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_growth.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
391. 計畫對齊檢查（P3/P4 DCF variant builder 流程收斂）：
   - 結果：與 blueprint/P3/P4 一致（builder 主檔樣板進一步下降，variant owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
392. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 DCF deps 命名收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
393. P3/P4 拆分增量（DCF deps 命名收斂）：
   - 移除 `DCFStandardBuilderDeps` / `DCFGrowthBuilderDeps` 重複別名
   - `dcf_standard.py` / `dcf_growth.py` 的 `deps` 型別統一為 `DCFVariantBuilderDeps`
   - `param_builders/__init__.py` export 改為單一 `DCFVariantBuilderDeps`
   - 保持 `build_dcf_standard_payload(...)` / `build_dcf_growth_payload(...)` 對外函式與輸出 payload 不變
394. 驗證結果（P3/P4 DCF deps 命名收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_variant_payload_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_standard.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/dcf_growth.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/__init__.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
395. 計畫對齊檢查（P3/P4 DCF deps 命名收斂）：
   - 結果：與 blueprint/P3/P4 一致（重複命名下降，deps owner 更單一）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
396. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 CAPM market params 組裝收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
397. P3/P4 拆分增量（CAPM market params 組裝收斂）：
   - `common_output_assembly_service.py` 新增 `build_capm_market_params(...)`，統一 CAPM market scalar params 的組裝 owner
   - `bank_output_assembly_service.py` 與 `saas_output_assembly_service.py` 的 params 組裝改為委派 `build_capm_market_params(...)`
   - 保持 `risk_free_rate` / `beta` / `market_risk_premium` 欄位與輸出 payload 不變
398. 驗證結果（P3/P4 CAPM market params 組裝收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/common_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
399. 計畫對齊檢查（P3/P4 CAPM market params 組裝收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨 model 的相同輸出欄位組裝 owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
400. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 Monte Carlo controls 組裝收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
401. P3/P4 拆分增量（Monte Carlo controls 組裝收斂）：
   - `common_output_assembly_service.py` 新增 `build_monte_carlo_params(...)`，統一 `monte_carlo_iterations/seed/sampler` 欄位組裝 owner
   - `bank_output_assembly_service.py`、`saas_output_assembly_service.py`、`reit_output_assembly_service.py` 的 params 組裝改為委派 `build_monte_carlo_params(...)`
   - 保持輸出 payload 欄位與語義不變
402. 驗證結果（P3/P4 Monte Carlo controls 組裝收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/common_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
403. 計畫對齊檢查（P3/P4 Monte Carlo controls 組裝收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨 model 的共用控制欄位 owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
404. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 optional trace-input fallback 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
405. P3/P4 拆分增量（optional trace-input fallback 收斂）：
   - `common_output_assembly_service.py` 新增 `resolve_optional_trace_input(...)`，統一 `TraceableField | None` 的缺值 fallback 組裝 owner
   - `bank_output_assembly_service.py`：
     - `tier1_target_ratio` trace input 改為委派 `resolve_optional_trace_input(...)`
   - `reit_output_assembly_service.py`：
     - `ffo` 與 `ffo_multiple` trace inputs 改為委派 `resolve_optional_trace_input(...)`
   - 保持缺值時欄位名稱與 missing reason、輸出 trace payload 語義不變
406. 驗證結果（P3/P4 optional trace-input fallback 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/common_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit_output_assembly_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
407. 計畫對齊檢查（P3/P4 optional trace-input fallback 收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨 model 的相同缺值 fallback owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
408. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 optional ratio-input fallback 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
409. P3/P4 拆分增量（optional ratio-input fallback 收斂）：
   - `param_builder_core_ops_service.py` 新增 `ratio_with_optional_inputs(...)`，統一 optional numerator/denominator 的 ratio fallback owner
   - `saas_operating_rates_policy_service.py`：
     - `capex_rate_tf` 的 `ratio(...) / missing_field(...)` 分支改為委派 `ratio_with_optional_inputs(...)`
   - `bank_rorwa_policy_service.py`：
     - `latest_rorwa_tf` 的 `ratio(...) / missing_field(...)` 分支改為委派 `ratio_with_optional_inputs(...)`
   - 保持 `missing_reason` 字串、fallback 條件與輸出 `TraceableField` 語義不變
410. 驗證結果（P3/P4 optional ratio-input fallback 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_core_ops_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_operating_rates_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_rorwa_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
411. 計畫對齊檢查（P3/P4 optional ratio-input fallback 收斂）：
   - 結果：與 blueprint/P3/P4 一致（policy 層相同缺值分支 owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
412. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 CAPM market defaults 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
413. P3/P4 拆分增量（CAPM market defaults 收斂）：
   - 新增 `capm_market_defaults_service.py`：
     - `CapmMarketDefaults`
     - `resolve_capm_market_defaults(...)`
   - `bank_capm_policy_service.py` 與 `saas_capm_policy_service.py` 的共同段落（risk-free/beta/market_risk_premium default + assumptions）改為委派 `resolve_capm_market_defaults(...)`
   - 保持各 model 的 default 值與訊息格式差異（bank: `.1%/.1f`，saas: `.2%/.2f`）不變
414. 驗證結果（P3/P4 CAPM market defaults 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/capm_market_defaults_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_capm_policy_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_capm_policy_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
415. 計畫對齊檢查（P3/P4 CAPM market defaults 收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨 model 的 CAPM default policy owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
416. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 shares-source one-hop wrapper 移除屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
417. P3/P4 拆分增量（shares-source one-hop wrapper 移除）：
   - `bank_output_assembly_service.py`：
     - 移除 `resolve_bank_shares_source(...)` wrapper 與 `BankSharesSource` alias
   - `saas_output_assembly_service.py`：
     - 移除 `resolve_saas_shares_source(...)` wrapper
   - `bank.py` / `saas.py`：
     - 改為直接委派 canonical owner `resolve_shares_source(...)`，分別傳入 `filing_source=\"xbrl_filing\"` 與 `filing_source=\"filing\"`
   - 保持 shares source 判斷條件與輸出值不變
418. 驗證結果（P3/P4 shares-source one-hop wrapper 移除）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas_output_assembly_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
419. 計畫對齊檢查（P3/P4 shares-source one-hop wrapper 移除）：
   - 結果：與 blueprint/P3/P4 一致（去除 one-hop alias wrapper，owner 邊界更直接）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
420. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 current-price 提取 owner 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
421. P3/P4 拆分增量（current-price 提取 owner 收斂；小幅擴大範圍）：
   - `value_extraction_service.py` 新增 `extract_current_price(...)`，統一 `current_price` 市場欄位提取 owner
   - 以下 builder 改為委派 `extract_current_price(...)`（取代重複 `extract_market_value(..., field_name="current_price")`）：
     - `bank.py`
     - `saas.py`
     - `multiples.py`
     - `reit.py`
     - `eva.py`
     - `residual_income.py`
   - 保持 market field key（`"current_price"`）與輸出行為不變
422. 驗證結果（P3/P4 current-price 提取 owner 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
423. 計畫對齊檢查（P3/P4 current-price 提取 owner 收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨多 builder 的同一市場欄位提取 owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
424. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 shares-source semantic entrypoint 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
425. P3/P4 拆分增量（shares-source semantic entrypoint 收斂；小幅擴大範圍）：
   - `shares_source_service.py` 新增：
     - `resolve_filing_shares_source(...)`
     - `resolve_xbrl_filing_shares_source(...)`
   - 以下 builder 改為使用語義化入口（移除散落 `filing_source` 字串常量）：
     - `bank.py` -> `resolve_xbrl_filing_shares_source(...)`
     - `saas.py` / `multiples.py` / `reit.py` / `eva.py` / `residual_income.py` -> `resolve_filing_shares_source(...)`
   - 保持 shares source 判斷條件與輸出值不變
426. 驗證結果（P3/P4 shares-source semantic entrypoint 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/shares_source_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
427. 計畫對齊檢查（P3/P4 shares-source semantic entrypoint 收斂）：
   - 結果：與 blueprint/P3/P4 一致（shares-source owner 更集中且 call site 字面常量下降）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
428. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 capital-structure values 提取收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
429. P3/P4 拆分增量（capital-structure values 提取收斂；小幅擴大範圍）：
   - `value_extraction_service.py` 新增：
     - `CapitalStructureValues`
     - `extract_capital_structure_values(...)`
   - 以下 builder 改為委派 `extract_capital_structure_values(...)`，收斂重複的 `shares/cash/debt/preferred` 提取樣板：
     - `saas.py`
     - `reit.py`
     - `eva.py`
     - `multiples.py`
   - 各 builder 的 model-specific 欄位（如 `initial_revenue` / `ffo` / `current_invested_capital` / target metric）保持原有缺值紀錄語義不變
430. 驗證結果（P3/P4 capital-structure values 提取收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
431. 計畫對齊檢查（P3/P4 capital-structure values 提取收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨多 builder 的資本結構欄位提取 owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
432. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 filing-equity/capital-market values 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
433. P3/P4 拆分增量（filing equity/capital market values 收斂；小幅擴大範圍）：
   - `value_extraction_service.py` 新增：
     - `FilingEquityMarketValues`
     - `FilingCapitalStructureMarketValues`
     - `extract_filing_equity_market_values(...)`
     - `extract_filing_capital_structure_market_values(...)`
   - 以下 builder 改為委派上述 helper，收斂重複的 `shares_source/current_price/shares_outstanding` 與 capital-structure 提取樣板：
     - `saas.py`
     - `reit.py`
     - `eva.py`
     - `multiples.py`
     - `residual_income.py`
   - 保持 shares source 判斷條件、market field key（`"current_price"`）與 missing 記錄語義不變
434. 驗證結果（P3/P4 filing equity/capital market values 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/eva.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/multiples.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/residual_income.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
435. 計畫對齊檢查（P3/P4 filing equity/capital market values 收斂）：
   - 結果：與 blueprint/P3/P4 一致（跨多 builder 的 market/equity 提取 owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
436. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 bank xbrl-equity market extraction 收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
437. P3/P4 拆分增量（bank xbrl-equity market extraction 收斂）：
   - `value_extraction_service.py` 新增：
     - `extract_xbrl_filing_equity_market_values(...)`
     - 內部 `extract_filing_equity_market_values(...)` 改為共用 `_extract_equity_market_values(...)`（依 resolver 決定 shares_source）
   - `bank.py` 改為委派 `extract_xbrl_filing_equity_market_values(...)`，收斂 `shares_source/current_price/shares_outstanding` owner；移除 direct shares-source service 呼叫
   - 保持 xbrl_filing shares source 判斷條件、market field key（`"current_price"`）與 missing 記錄語義不變
438. 驗證結果（P3/P4 bank xbrl-equity market extraction 收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/bank.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
439. 計畫對齊檢查（P3/P4 bank xbrl-equity market extraction 收斂）：
   - 結果：與 blueprint/P3/P4 一致（bank 與其他 builder 的 market/equity 提取 owner 對齊）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
440. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 extraction service 邊界/型別語義收斂屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
441. P3/P4 拆分增量（value extraction owner 邊界與型別語義收斂）：
   - `value_extraction_service.py`：
     - 新增明確型別別名 `MarketFloatOp`、`ValueOrMissingOp`
     - 新增 `SharesSourceResolver` protocol（取代過寬 `Callable[..., str]`）
     - 新增 `_extract_capital_structure_market_values(...)` 私有 owner helper
     - `extract_filing_capital_structure_market_values(...)` 改為委派上述 helper
   - 保持 shares source 判斷邏輯、market key（`"current_price"`）與 missing 記錄語義不變
442. 驗證結果（P3/P4 value extraction owner 邊界與型別語義收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
443. 計畫對齊檢查（P3/P4 value extraction owner 邊界與型別語義收斂）：
   - 結果：與 blueprint/P3/P4 一致（owner helper 邊界更清晰、callable 契約更精確）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 策略延伸，未出現新的跨 agent 反模式。`
444. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 registry entrypoint thin 化屬既有 wiring-owner/entrypoint-boundary 規則範圍，無需新增 standards 條目
445. P3/P4 拆分增量（registry default context wiring owner 下沉）：
   - 新增 `param_builder_default_context_service.py`：
     - `build_default_builder_context(...)`
     - 承接 default builder context wiring（shares/monte-carlo/growth closures + BuilderContextDeps 組裝）
   - `param_builder_model_registry_service.py`：
     - `_builder_context()` 改為委派 `build_default_builder_context(...)`
     - 移除 registry 對多個 core wiring 依賴的直接 import
   - 行為不變：`_builder_context()` 仍保留 `lru_cache(maxsize=1)`，default constants 與輸出 context 語義不變
446. 驗證結果（P3/P4 registry default context wiring owner 下沉）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_default_context_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
447. 計畫對齊檢查（P3/P4 registry default context wiring owner 下沉）：
   - 結果：與 blueprint/P3/P4 一致（entrypoint 更薄、wiring owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 與 entrypoint-thin 策略延伸，未出現新的跨 agent 反模式。`
448. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 shares-source owner 內聚化屬既有 owner/consolidation 規則範圍，無需新增 standards 條目
449. P3/P4 拆分增量（shares-source owner 內聚化與檔案收斂）：
   - `value_extraction_service.py`：
     - 內聚 shares source 判斷 helper（`_resolve_shares_source` + filing/xbrl 兩個語義化 helper）
     - 原本 extraction 流程改為呼叫本檔 helper，不改判斷語義
   - 移除 `param_builders/shares_source_service.py`（已無外部呼叫）
   - 行為不變：shares source 判斷條件與輸出值（`market_data` / `filing` / `xbrl_filing`）不變
450. 驗證結果（P3/P4 shares-source owner 內聚化與檔案收斂）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/value_extraction_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builders` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
451. 計畫對齊檢查（P3/P4 shares-source owner 內聚化與檔案收斂）：
   - 結果：與 blueprint/P3/P4 一致（one-hop/孤立 service 檔移除，owner 更集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 consolidation 與檔案收斂策略延伸，未出現新的跨 agent 反模式。`
452. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 registry wrapper 收斂屬既有 entrypoint-thin/wiring-owner 規則範圍，無需新增 standards 條目
453. P3/P4 較大切片（registry wrapper consolidation / factory-based routing）：
   - `param_builder_model_registry_service.py`：
     - 新增 variant type aliases（`DcfVariant` / `EvMultipleVariant` / `MultiReportVariant` / `SingleReportVariant`）
     - 新增 `LatestOnlyModelBuilder` callable type
     - 移除 9 個一跳 wrapper（`_build_*_params`）並改為 4 個 factory builders：
       - `_build_dcf_variant_builder(...)`
       - `_build_multi_report_builder(...)`
       - `_build_ev_multiple_latest_builder(...)`
       - `_build_single_report_latest_builder(...)`
     - `_model_builder_registry()` 改為以 factory closures 組裝 registry，保留既有 wiring service owner
   - 行為不變：各 model_type 的 builder routing、deps 解析與 payload/result 組裝語義保持一致
454. 驗證結果（P3/P4 registry wrapper consolidation / factory-based routing）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
455. 計畫對齊檢查（P3/P4 registry wrapper consolidation / factory-based routing）：
   - 結果：與 blueprint/P3/P4 一致（entrypoint 進一步瘦身，重複 wrapper 明顯下降）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 entrypoint-thin 與 owner consolidation 策略的擴大套用，未出現新的跨 agent 反模式。`
456. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - 結論：本批 model dispatch 下沉屬既有 entrypoint-thin / dispatch-owner 分離規則範圍，無需新增 standards 條目
457. P3/P4 較大切片（model dispatch owner service 化）：
   - 新增 `param_builder_model_dispatch_service.py`：
     - 承接 model payload dispatch maps 與 deps resolver maps
     - 承接四類 builder factory（dcf variant / multi-report / ev latest-only / single-report latest-only）
   - `param_builder_model_registry_service.py`：
     - 移除 dispatch maps、variant aliases、payload dispatch 函式與 factory 細節
     - 保留 `result assembly + registry wiring + default context` 的 entrypoint 職責
     - 透過 dispatch service factory + `_assemble_param_result` 完成 registry 組裝
   - 行為不變：model_type -> builder routing、deps 解析、payload/result 組裝語義與 `lru_cache` 行為保持一致
458. 驗證結果（P3/P4 model dispatch owner service 化）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_dispatch_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
459. 計畫對齊檢查（P3/P4 model dispatch owner service 化）：
   - 結果：與 blueprint/P3/P4 一致（registry 入口更薄，dispatch owner 明確化）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 entrypoint-thin 與 owner consolidation 策略的進一步擴大，未出現新的跨 agent 反模式。`
460. Pre-check（本批開始前 standards review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批 dispatch 進一步 owner 下沉屬既有 entrypoint-thin / owner-consolidation 規則範圍，無需新增 standards 條目
461. P3/P4 較大切片（registry payload dispatch 全量下沉）：
   - 新增 `param_builder_model_dispatch_service.py`：
     - 集中 `model payload builders` 與 `deps resolvers` maps
     - 集中 payload dispatch flow（dcf/multi-report/ev/single-report）
     - 對外提供四類 builder factories，供 registry wiring 直接使用
   - `param_builder_model_registry_service.py` 重整為 thin entrypoint：
     - 移除 dispatch maps / variant aliases / payload dispatch 函式與 factory 細節
     - 保留 `result assembly + registry wiring + default context` 邏輯
     - 以 dispatch service + `_assemble_param_result` 組裝各 model builder
   - 行為不變：model_type 路由、deps 解析、payload/result 組裝與 `lru_cache` 語義保持一致
462. 驗證結果（P3/P4 registry payload dispatch 全量下沉）：
   - `ruff check finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_dispatch_service.py finance-agent-core/src/agents/fundamental/domain/valuation/param_builder_model_registry_service.py` 通過
   - `pytest finance-agent-core/tests/test_param_builder_canonical_reports.py finance-agent-core/tests/test_error_handling_fundamental.py finance-agent-core/tests/test_fundamental_orchestrator_logging.py -q` 通過（25 passed）
463. 計畫對齊檢查（P3/P4 registry payload dispatch 全量下沉）：
   - 結果：與 blueprint/P3/P4 一致（registry 入口進一步精簡，dispatch owner 明確集中）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有 entrypoint-thin 與 owner consolidation 策略的擴大執行，未出現新的跨 agent 反模式。`
464. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批將執行 `valuation/skills` 命名清理與 registry 語義收斂，屬既有 P4 naming cleanup 規則範圍
465. P3/P4 較大切片（valuation `skills -> models` + registry 命名收斂）：
   - 路徑重構：
     - `domain/valuation/skills/*` -> `domain/valuation/models/*`
     - `domain/valuation/registry.py` -> `domain/valuation/valuation_model_registry.py`
   - 命名收斂：
     - `SkillRegistry` -> `ValuationModelRegistry`
     - `get_skill(...)` -> `get_model_runtime(...)`
     - `ValuationSkillRuntime/parse_valuation_skill_runtime` -> `ValuationModelRuntime/parse_valuation_model_runtime`
     - `run_valuation(..., get_skill_fn=...)` -> `run_valuation(..., get_model_runtime_fn=...)`
   - call sites 全量更新：`application/factory.py`、`application/orchestrator.py`、`domain/valuation/backtest.py`、相關測試檔與 imports
   - 測試命名同步：
     - `test_fundamental_dcf_growth_skill_registry.py` -> `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_skill_registry.py` -> `test_fundamental_dcf_standard_model_registry.py`
   - 相容層：不保留 legacy alias/shim
466. 驗證結果（P3/P4 valuation models + registry naming cleanup）：
   - `ruff check`（valuation/application/interface + 相關 tests）通過
   - `pytest -q` 通過：
     - `test_fundamental_interface_parsers.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_backtest_runner.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
   - 合計：`53 passed`（warnings 與前批一致）
467. 計畫對齊檢查（P4 naming cleanup / remove valuation skills naming）：
   - 結果：主方向與 blueprint/P4 一致（`valuation/skills` 命名已移除，registry 與 runtime 介面語義化）
   - 偏離：小幅偏離（路徑落在 `domain/valuation/models`，未搬到 `application/valuation/*`）
   - 偏離原因：估值 schema/calculator/audit rule 仍屬 deterministic domain rule，先保留在 domain 以避免 layer leakage；後續可再按 blueprint 的 package 結構做第二階段細拆
   - `Lessons Review: no_update`
   - `Reason: 本批主要為命名與路徑收斂，已被既有 cross-agent naming 規約覆蓋，未新增新型反模式。`
468. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦移除 `valuation/models/*/tools.py` 命名，屬既有命名規約（`tools.py -> calculator.py/service.py`）範圍，無需新增 standards 條目
469. P3/P4 較大切片（valuation model calculators 命名收斂）：
   - 檔名重構（不保留相容層）：
     - `valuation_bank/tools.py` -> `valuation_bank/calculator.py`
     - `valuation_dcf_growth/tools.py` -> `valuation_dcf_growth/calculator.py`
     - `valuation_dcf_standard/tools.py` -> `valuation_dcf_standard/calculator.py`
     - `valuation_ev_ebitda/tools.py` -> `valuation_ev_ebitda/calculator.py`
     - `valuation_ev_revenue/tools.py` -> `valuation_ev_revenue/calculator.py`
     - `valuation_eva/tools.py` -> `valuation_eva/calculator.py`
     - `valuation_reit_ffo/tools.py` -> `valuation_reit_ffo/calculator.py`
     - `valuation_residual_income/tools.py` -> `valuation_residual_income/calculator.py`
     - `valuation_saas/tools.py` -> `valuation_saas/calculator.py`
   - call site 全量更新：
     - `valuation_model_registry.py` import 全部改為 `.calculator`
     - `valuation_dcf_standard/__init__.py`、`valuation_dcf_growth/__init__.py` 改為 `.calculator`
     - 測試 import 路徑同步（dcf graph / bank+reit / saas MC / registry/backtest 相關）
470. 驗證結果（P3/P4 valuation model calculators 命名收斂）：
   - `ruff check`（valuation models/registry + 相關 tests）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
   - 合計：`43 passed`（warnings 與前批一致）
   - 補充 guard：`test_fundamental_import_hygiene_guard.py` 通過（`2 passed`）
471. 計畫對齊檢查（P4 tools -> calculator naming cleanup）：
   - 結果：與 blueprint/P4 與 standards 命名規範一致（valuation models 中 generic `tools.py` 已移除）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有命名規約的落地執行，未新增新型反模式。`
472. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：下一步執行 `valuation/models` 子 package 去冗餘命名（移除 `valuation_*` stutter）
473. P3/P4 較大切片（valuation models package stutter 命名清理）：
   - 路徑重構（不保留相容層）：
     - `models/valuation_bank` -> `models/bank`
     - `models/valuation_dcf_growth` -> `models/dcf_growth`
     - `models/valuation_dcf_standard` -> `models/dcf_standard`
     - `models/valuation_ev_ebitda` -> `models/ev_ebitda`
     - `models/valuation_ev_revenue` -> `models/ev_revenue`
     - `models/valuation_eva` -> `models/eva`
     - `models/valuation_reit_ffo` -> `models/reit_ffo`
     - `models/valuation_residual_income` -> `models/residual_income`
     - `models/valuation_saas` -> `models/saas`
   - import/call-site 全量更新：
     - `valuation_model_registry.py`
     - `models/auditor/rules.py`
     - 相關 tests（dcf graph / bank+reit / saas MC / model registry / backtest）
   - 修正批量替換副作用：
     - `models/auditor/rules.py` log event 維持 `valuation_audit_completed`（避免行為漂移）
474. 驗證結果（P3/P4 valuation models package stutter 命名清理）：
   - `ruff check`（valuation models/registry + 相關 tests）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
   - 合計：`43 passed`（warnings 與前批一致）
   - `test_fundamental_import_hygiene_guard.py` 通過（`2 passed`）
475. 計畫對齊檢查（P4 package naming cleanup / remove context stutter）：
   - 結果：與 blueprint/P4 命名去歧義方向一致（`models/valuation_*` stutter 已移除）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「避免 bounded context 內 package prefix stutter」規約與實作經驗。`
476. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦 `models/auditor/rules.py` 去泛化命名，屬 P4 命名收斂主線
477. P3/P4 較大切片（auditor -> audit_policies + rules.py 語義化）：
   - 路徑重構（不保留相容層）：
     - `models/auditor` -> `models/audit_policies`
     - `models/audit_policies/rules.py` -> `models/audit_policies/valuation_audit_policy.py`
   - call-site 更新：
     - `valuation_model_registry.py` import 改為 `.models.audit_policies.valuation_audit_policy`
   - 安全修正：
     - 修復批量替換副作用，保留 audit log event 常量為 `valuation_audit_completed`
478. 驗證結果（P3/P4 audit policy naming cleanup）：
   - `ruff check`（valuation models/registry + 相關 tests）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
   - 合計：`43 passed`（warnings 與前批一致）
   - `test_fundamental_import_hygiene_guard.py` 通過（`2 passed`）
479. 計畫對齊檢查（P4 policy naming cleanup / remove generic rules.py）：
   - 結果：與 blueprint/P4 命名去歧義方向一致（generic `rules.py` 已移除，policy owner 模組語義更清晰）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：把 generic rules.py 納入反模式，要求 policy 模組使用語義化檔名。`
480. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批將 `audit policy` owner 從 `models/*` 提升到 `domain/valuation/policies/*`，對齊 domain policy 邊界
481. P3/P4 較大切片（audit policy owner boundary 收斂）：
   - 路徑重構（不保留相容層）：
     - `domain/valuation/models/audit_policies/valuation_audit_policy.py`
       -> `domain/valuation/policies/valuation_audit_policy.py`
   - `domain/valuation/policies/__init__.py` 新增 canonical exports
   - call-site 更新：
     - `valuation_model_registry.py` import 改為 `.policies.valuation_audit_policy`
   - 移除 legacy owner 殘留：
     - 刪除 `models/audit_policies/__init__.py`
     - 刪除 `models/audit_policies/SKILL.md`
     - 刪除 `models/audit_policies/` 空目錄
482. 驗證結果（P3/P4 audit policy owner boundary 收斂）：
   - `ruff check`（valuation/policies/models + 相關 tests）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
   - 合計：`43 passed`（warnings 與前批一致）
   - `test_fundamental_import_hygiene_guard.py` 通過（`2 passed`）
483. 計畫對齊檢查（P4 policy owner boundary to domain/policies）：
   - 結果：與 blueprint domain layer 目標一致（policy 從 model 子樹抽離）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「跨模型 policy 必須放 domain/.../policies」規約。`
484. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦 runtime 結構降噪（移除 `_template` 與 runtime `SKILL.md` 殘留），屬 P4 命名/結構收斂主線
485. P3/P4 較大切片（runtime template 殘留清理）：
   - owner 收斂：
     - 新增 `domain/valuation/models/base_valuation_params.py` 作為 base params canonical owner
     - 各 model schema import 改為 `..base_valuation_params`
   - 路徑清理（不保留相容層）：
     - 刪除 `domain/valuation/models/_template/schemas.py`
     - 刪除 `domain/valuation/models/_template/__init__.py`
     - 刪除 `domain/valuation/models/_template/` 目錄
   - runtime 雜訊清理：
     - 刪除 `domain/valuation/models/bank/SKILL.md`
     - 刪除 `domain/valuation/models/saas/SKILL.md`
486. 驗證結果（P3/P4 runtime template 殘留清理）：
   - `ruff check`（valuation/models/policies + 相關 tests）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
   - 合計：`43 passed`（warnings 與前批一致）
   - `test_fundamental_import_hygiene_guard.py` 通過（`2 passed`）
487. 計畫對齊檢查（P4 runtime structure cleanup / remove template artifacts）：
   - 結果：與 blueprint/P4 命名去歧義與結構收斂方向一致（runtime model tree 僅保留語義化 owner）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「runtime package 禁用 `_template` 與 `SKILL.md` 殘留」規約與實作經驗。`
488. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦 valuation models contract module 命名收斂（`schemas.py -> contracts.py`），屬 P4 命名去歧義主線
489. P3/P4 較大切片（valuation model contract module 命名收斂）：
   - 檔名重構（不保留相容層）：
     - `models/bank/schemas.py` -> `models/bank/contracts.py`
     - `models/dcf_growth/schemas.py` -> `models/dcf_growth/contracts.py`
     - `models/dcf_standard/schemas.py` -> `models/dcf_standard/contracts.py`
     - `models/ev_ebitda/schemas.py` -> `models/ev_ebitda/contracts.py`
     - `models/ev_revenue/schemas.py` -> `models/ev_revenue/contracts.py`
     - `models/eva/schemas.py` -> `models/eva/contracts.py`
     - `models/reit_ffo/schemas.py` -> `models/reit_ffo/contracts.py`
     - `models/residual_income/schemas.py` -> `models/residual_income/contracts.py`
     - `models/saas/schemas.py` -> `models/saas/contracts.py`
   - call-site 全量更新：
     - `valuation_model_registry.py`
     - `policies/valuation_audit_policy.py`
     - 各 model `calculator.py` 與 `__init__.py`
     - 相關 tests（dcf graph / bank+reit / saas MC / model registry）
490. 驗證結果（P3/P4 valuation model contract module 命名收斂）：
   - `ruff check`（valuation + 相關 tests）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`17 passed`（含既有 warnings）
491. 計畫對齊檢查（P4 model contract naming cleanup / remove schemas.py）：
   - 結果：與 blueprint/P4 命名去歧義方向一致（model contract owner 命名統一為 `contracts.py`）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「domain model contract module 一律使用 contracts.py」規約。`
492. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦 DCF standard/growth 共用計算 owner 收斂，對齊 blueprint 的 `domain/valuation/calculators` 目標
493. P3/P4 較大切片（DCF family shared calculator owner 收斂）：
   - 新增 canonical owner：
     - `domain/valuation/calculators/dcf_variant_calculator.py`
     - `domain/valuation/calculators/__init__.py`
   - `dcf_standard` 與 `dcf_growth` 收斂：
     - 將重複的 validation/trace-input merge/結果組裝/Monte Carlo batch evaluate 移到 shared owner
     - 各自 `models/*/calculator.py` 改為 thin wrapper，只保留：
       - graph factory 綁定（`create_dcf_standard_graph` / `create_dcf_growth_graph`）
       - variant-specific Monte Carlo policy 參數
   - 相容策略：不新增 compatibility alias；直接以 canonical owner + wrapper 方式收斂。
494. 驗證結果（P3/P4 DCF shared calculator owner 收斂）：
   - `ruff check`（valuation calculators + DCF models + registry/tests）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`45 passed`（含既有 warnings）
495. 計畫對齊檢查（P4 calculators package convergence for DCF family）：
   - 結果：與 blueprint `domain/valuation/calculators` 方向一致（至少 DCF family 已收斂成 shared calculator owner）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「模型家族共用公式需收斂到 shared calculator owner，model calculator 保持薄封裝」規約。`
496. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批擴大 `domain/valuation/calculators` 收斂，覆蓋 EV/REIT/Residual，並統一 calculator runtime support owner
497. P3/P4 較大切片（EV + REIT + Residual calculators owner 收斂）：
   - 新增 shared runtime support owner：
     - `domain/valuation/calculators/calculator_runtime_support.py`
       - owner 職責：`apply_trace_inputs` / `unwrap_traceable_value` / `compute_upside`
   - 新增 shared calculator owners：
     - `domain/valuation/calculators/ev_multiple_variant_calculator.py`
     - `domain/valuation/calculators/reit_ffo_calculator.py`
     - `domain/valuation/calculators/residual_income_calculator.py`
   - model calculator 收斂為 thin wrappers：
     - `models/ev_revenue/calculator.py`
     - `models/ev_ebitda/calculator.py`
     - `models/reit_ffo/calculator.py`
     - `models/residual_income/calculator.py`
   - DCF shared owner 一致性收斂：
     - `dcf_variant_calculator.py` 改為使用 `calculator_runtime_support`，移除 local 重複 runtime 函式
   - `domain/valuation/calculators/__init__.py` 更新 canonical exports
498. 驗證結果（P3/P4 EV + REIT + Residual calculators convergence）：
   - `ruff check`（valuation calculators/models + registry）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`45 passed`（含既有 warnings）
499. 計畫對齊檢查（P4 calculators package convergence extension）：
   - 結果：與 blueprint `domain/valuation/calculators` 目標一致（DCF + EV + REIT + Residual 主要計算 owner 已收斂到 calculators package）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「calculator runtime support 函式必須集中 owner，不得各 model 重複維護」規約。`
500. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批在不改變對外 API 的前提下，將 Bank/EVA/SaaS calculator 的重複 runtime support 收斂到 shared owner
501. P3/P4 中等切片（Bank + EVA + SaaS runtime support 收斂）：
   - `models/bank/calculator.py`：
     - 移除 local `_unwrap`、`_apply_trace_inputs`
     - 改用 `calculators/calculator_runtime_support`（`apply_trace_inputs` / `unwrap_traceable_value` / `compute_upside`）
   - `models/eva/calculator.py`：
     - 移除 local `_unwrap`、`_apply_trace_inputs`
     - 改用 shared runtime support
   - `models/saas/calculator.py`：
     - 移除 local `_unwrap`、`_apply_trace_inputs`
     - 改用 shared runtime support
   - 結果：`models/*/calculator.py` 的重複 support function 再次下降，owner 收斂一致
502. 驗證結果（P3/P4 Bank + EVA + SaaS runtime support convergence）：
   - `ruff check`（valuation calculators + bank/eva/saas）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`45 passed`（含既有 warnings）
503. 計畫對齊檢查（P4 calculator runtime support convergence completion）：
   - 結果：與 blueprint `domain/valuation/calculators` 收斂方向一致（跨模型 runtime support 已集中 owner）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批落地的是 499 已新增規約，未出現新的反模式類型。`
504. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批目標為移除 `models/*/calculator.py` 相容層，讓 registry 與測試直接依賴 `domain/valuation/calculators` canonical owner
505. P3/P4 較大切片（remove model calculator compatibility layer）：
   - calculator canonical owner 擴展：
     - 新增 `calculators/bank_calculator.py`
     - 新增 `calculators/saas_calculator.py`
     - 新增 `calculators/eva_calculator.py`
     - 新增 `calculators/dcf_growth_calculator.py`
     - 新增 `calculators/dcf_standard_calculator.py`
     - 新增 `calculators/ev_revenue_calculator.py`
     - 新增 `calculators/ev_ebitda_calculator.py`
   - registry/call-site 直接依賴 calculators owner：
     - `valuation_model_registry.py` imports 改為 `.calculators.*_calculator`
     - 測試 imports 改為 `domain.valuation.calculators.*`
   - 路徑清理（不保留相容層）：
     - 刪除 `models/*/calculator.py`（bank/dcf_growth/dcf_standard/ev_ebitda/ev_revenue/eva/reit_ffo/residual_income/saas）
   - model package owner 收斂：
     - `models/dcf_growth/__init__.py`、`models/dcf_standard/__init__.py` 改為 contracts-only export
506. 驗證結果（P3/P4 remove model calculator compatibility layer）：
   - `ruff check`（valuation calculators/models + registry + 相關 tests）通過
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_dcf_growth_model_registry.py`
     - `test_fundamental_dcf_standard_model_registry.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`45 passed`（含既有 warnings）
507. 計畫對齊檢查（P4 calculators canonicalization / no compatibility layer）：
   - 結果：與 blueprint `domain/valuation/calculators` 目標更一致（registry 與 tests 均直接依賴 calculators owner，models 保留 contracts owner）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「成熟階段移除 models calculator 相容層，registry 直接依賴 calculators canonical owner」規約。`
508. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦 `param_builders/value_extraction_service.py` owner 拆分，對齊 blueprint Phase 2 的 service decomposition 與高內聚目標。
509. P3/P4 較大切片（param_builder value extraction owner 拆分）：
   - 新增 extraction owner modules：
     - `param_builders/value_extraction_common_service.py`
     - `param_builders/equity_market_value_extraction_service.py`
     - `param_builders/capital_structure_value_extraction_service.py`
   - 既有 `value_extraction_service.py` 拆分：
     - common（required values / market values / shares-source resolver）
     - equity market values（filing/xbrl-filing equity extraction）
     - capital structure market values（cash/debt/preferred + market context）
   - call-site 全量切換（不保留 compatibility layer）：
     - `param_builders/bank.py`
     - `param_builders/eva.py`
     - `param_builders/multiples.py`
     - `param_builders/reit.py`
     - `param_builders/residual_income.py`
     - `param_builders/saas.py`
   - 路徑清理：
     - 刪除 `param_builders/value_extraction_service.py`
510. 驗證結果（P3/P4 param_builder value extraction decomposition）：
   - `ruff check`（新 extraction modules + 6 個 builder call-sites）通過
   - `pytest -q` 通過：
     - `test_param_builder_canonical_reports.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`39 passed`（含既有 warnings）
511. 計畫對齊檢查（P4 param_builder extraction owner boundary convergence）：
   - 結果：與 blueprint Phase 2「Service Decomposition」及「提升內聚」方向一致（同一 extraction 責任不再集中於單一混合檔案）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批屬既有規約（避免 god module、按語義 owner 拆分）的直接落地，未出現新的反模式類型。`
512. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦 `param_builder` 的 dispatch/registry owner 再收斂，對齊 blueprint 的 `builders/registry/shared` 邊界與薄 entrypoint 原則。
513. P3/P4 較大切片（param_builder dispatch + registry owner 收斂）：
   - 新增 payload dispatch owner：
     - `param_builder_payload_dispatch_service.py`
   - 新增 model builder factory owner：
     - `param_builder_model_builder_factory_service.py`
   - 新增 result assembly owner：
     - `param_builder_result_assembly_service.py`
   - `param_builder_registry_service.py` 收斂為 wiring/cache owner：
     - 移除本地 result assembly 實作，改依賴 `build_param_result(...)`
     - builder 生成改依賴 `param_builder_model_builder_factory_service`
   - 路徑清理（不保留 compatibility layer）：
     - 刪除 `param_builder_model_dispatch_service.py`
514. 驗證結果（P3/P4 param_builder dispatch + registry convergence）：
   - `ruff check` 通過（payload dispatch + model builder factory + result assembly + registry + param_builder）
   - `pytest -q` 通過：
     - `test_param_builder_canonical_reports.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`39 passed`（含既有 warnings）
515. 計畫對齊檢查（P4 param_builder builders/registry/shared boundary convergence）：
   - 結果：與 blueprint `application/valuation/{builders,registry,shared}` 的 owner 分離方向一致（registry 僅 wiring，dispatch/result assembly 各有 owner）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批為既有規約「entrypoint 薄化、wiring 與 owner 拆分」的落地，未出現新的反模式類型。`
516. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦 application 層 `fundamental_service.py` 拆分，對齊 blueprint `application/services` 能力導向拆分與高內聚目標。
517. P3/P4 較大切片（application fundamental_service 解耦 + service owner 收斂）：
   - 新增 application service owners：
     - `application/services/model_selection_artifact_service.py`
     - `application/services/valuation_update_service.py`
     - `application/services/__init__.py`
   - owner 拆分：
     - model-selection artifact 組裝與存儲流程移入 `model_selection_artifact_service.py`
     - valuation update / assumption-breakdown / data-freshness 組裝移入 `valuation_update_service.py`
   - call-site 收斂：
     - `application/orchestrator.py` imports 改為直接依賴新的 services owners
     - `tests/test_fundamental_application_services.py` imports 改為新的 services owners
   - 路徑清理（不保留 compatibility layer）：
     - 刪除 `application/fundamental_service.py`
518. 驗證結果（P3/P4 application service decomposition）：
   - `ruff check` 通過：
     - `application/orchestrator.py`
     - `application/services/*`
     - `tests/test_fundamental_application_services.py`
   - `pytest -q` 通過：
     - `test_fundamental_application_services.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`35 passed`（含既有 warnings）
519. 計畫對齊檢查（P4 application services convergence / remove god service module）：
   - 結果：與 blueprint `application/services` 方向一致（service capability owner 明確化，移除單一 god module）
   - 偏離：無
   - `Lessons Review: no_update`
   - `Reason: 本批屬既有規約（拆分 god module、能力導向 service owner）直接落地，未出現新的反模式類型。`
520. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批聚焦 `application/use_cases` 化，將 orchestrator 的 `run_*` 主流程抽離到 use-case owners，對齊 blueprint 的 application use-case 分層目標。
521. P3/P4 較大切片（application use_cases 收斂 + orchestrator 薄化）：
   - 新增 use-case owners：
     - `application/use_cases/run_financial_health_use_case.py`
     - `application/use_cases/run_model_selection_use_case.py`
     - `application/use_cases/run_valuation_use_case.py`
     - `application/use_cases/__init__.py`
   - `application/orchestrator.py` 收斂：
     - `run_financial_health` / `run_model_selection` / `run_valuation` 改為 thin delegator
     - 保留 runtime capabilities（artifact load/save + service wrappers），流程控制移交 use-cases
   - 補充呼叫路徑調整：
     - `load_financial_reports_bundle` 改用 use-case owner 的 `normalize_forward_signals`
     - `test_fundamental_orchestrator_logging.py` patch target 改為 use-case owner module
522. 驗證結果（P3/P4 application use_cases convergence）：
   - `ruff check` 通過：
     - `application/orchestrator.py`
     - `application/use_cases/*`
     - `tests/test_fundamental_orchestrator_logging.py`
   - `pytest -q` 通過：
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_fundamental_application_services.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`35 passed`（含既有 warnings）
523. 計畫對齊檢查（P4 application use-case decomposition / thin orchestrator）：
   - 結果：與 blueprint `application/use_cases` + `application/services` 職責分離方向一致（orchestrator 降為薄編排入口）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「application orchestrator 應作 thin delegator，run_* 流程 owner 在 application/use_cases」規約。`
524. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批優先進入 infrastructure 大切片，拆 `infrastructure/sec_xbrl/mappings/base.py`，將 mapping catalog 依語義 owner 模組化，對齊 blueprint Phase 2/3「service decomposition + package re-layout」方向。
525. P3/P4 較大切片（sec_xbrl base mapping registry owner 拆分）：
   - 新增 mapping owner modules：
     - `infrastructure/sec_xbrl/mappings/base_core_fields.py`
     - `infrastructure/sec_xbrl/mappings/base_debt_fields.py`
     - `infrastructure/sec_xbrl/mappings/base_income_fields.py`
     - `infrastructure/sec_xbrl/mappings/base_cash_flow_fields.py`
   - `infrastructure/sec_xbrl/mappings/base.py` 收斂為 thin orchestrator：
     - 只保留 `register_base_fields(...)`
     - 改為依序委派給 core/debt/income/cash-flow registration owners
   - 相容性策略：
     - 不新增 compatibility layer；既有入口 `register_base_fields` 保持不變
526. 驗證結果（P3/P4 sec_xbrl base mapping registry decomposition）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/mappings/base.py`
     - `infrastructure/sec_xbrl/mappings/base_core_fields.py`
     - `infrastructure/sec_xbrl/mappings/base_debt_fields.py`
     - `infrastructure/sec_xbrl/mappings/base_income_fields.py`
     - `infrastructure/sec_xbrl/mappings/base_cash_flow_fields.py`
   - `pytest -q` 通過：
     - `test_sec_xbrl_mapping_fallbacks.py`
     - `test_sec_xbrl_resolver.py`
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`50 passed`（含既有 warnings）
527. 計畫對齊檢查（P4 infrastructure mapping owner modularization）：
   - 結果：與 blueprint `infrastructure/sec/xbrl` 方向一致（`base.py` entrypoint 薄化 + mapping owner 模組邊界明確化）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「大型 mapping registry catalog 必須按語義 owner 拆分，entrypoint 只保留註冊編排」規約。`
528. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批進入 `infrastructure/sec_xbrl/extractor.py` 大切片，優先做「高內聚 owner 拆分」而非單純 LOC 壓縮；保留 extractor 入口責任並將 config/result/search-processing 下沉。
529. P3/P4 較大切片（sec_xbrl extractor owner decomposition + side-effect bootstrap 收斂）：
   - 新增 extractor owners：
     - `infrastructure/sec_xbrl/extractor_models.py`
     - `infrastructure/sec_xbrl/extractor_search_processing_service.py`
     - `infrastructure/sec_xbrl/sec_identity_service.py`
   - `infrastructure/sec_xbrl/extractor.py` 收斂為入口 owner：
     - 保留 `SECReportExtractor`（report loading + search orchestration + debug）
     - search/filter/format 的資料列處理邏輯委派到 `extractor_search_processing_service.py`
     - `SearchConfig/SearchType/SECExtractResult` 模型 owner 轉移到 `extractor_models.py`
   - import-time side-effect 修正：
     - 移除 module import 時直接 `set_identity(...)`
     - 改為 runtime `ensure_sec_identity()`（idempotent）在 report load 時執行
   - 相容性處理：
     - 保留 extractor entrypoint 相容符號與 utility wrapper（包含 `SearchType` export、`_period_sort_key`、`_normalize_unit`、`_statement_matches`）
530. 驗證結果（P3/P4 sec_xbrl extractor decomposition）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/extractor.py`
     - `infrastructure/sec_xbrl/extractor_models.py`
     - `infrastructure/sec_xbrl/extractor_search_processing_service.py`
     - `infrastructure/sec_xbrl/sec_identity_service.py`
   - `pytest -q` 通過：
     - `test_sec_xbrl_resolver.py`
     - `test_sec_xbrl_mapping_fallbacks.py`
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_sec_xbrl_total_debt_policy.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`57 passed`（含既有 warnings）
531. 計畫對齊檢查（P4 infrastructure extractor decomposition / maintainability-first）：
   - 結果：與 blueprint `infrastructure/sec/xbrl` 拆分方向一致（entrypoint 保持清晰、processing owner 外提、import-time side effect 收斂）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「拆分 widely-used owner module 時，utility entrypoint 要么同批遷移 call sites、要么保留薄 wrapper」規約。`
532. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批進入 `infrastructure/sec_xbrl/base_model_debt_builder.py` 大切片，採「內聚優先」拆分（config/extraction/orchestration owner）而非僅 LOC 壓縮，並避免新增長期 compatibility layer。
533. P3/P4 較大切片（sec_xbrl debt builder owner decomposition）：
   - 新增 debt owner modules：
     - `infrastructure/sec_xbrl/base_model_debt_config_service.py`
     - `infrastructure/sec_xbrl/base_model_debt_component_extraction_service.py`
   - `infrastructure/sec_xbrl/base_model_debt_builder.py` 收斂為 thin orchestrator：
     - `build_total_debt_field(...)` 只保留流程編排（strict -> relaxed retry -> diagnostics）
     - config 組裝下沉到 `build_debt_config_bundle(...)`
     - strict/relaxed 抽取流程下沉到 `extract_debt_component_fields(...)`
   - 結構改善：
     - `base_model_debt_builder.py` LOC `557 -> 180`
     - strict/relaxed fallback 不再維護兩份大段流程碼
   - 相容性策略：
     - 不新增新 alias/shim；既有公開入口維持 `DebtBuilderOps + build_total_debt_field`。
534. 驗證結果（P3/P4 sec_xbrl debt builder decomposition）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/base_model_debt_builder.py`
     - `infrastructure/sec_xbrl/base_model_debt_config_service.py`
     - `infrastructure/sec_xbrl/base_model_debt_component_extraction_service.py`
     - `infrastructure/sec_xbrl/factory.py`
   - `pytest -q` 通過：
     - `test_sec_xbrl_total_debt_policy.py`
     - `test_sec_xbrl_resolver.py`
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`43 passed`（含既有 warnings）
535. 計畫對齊檢查（P4 infrastructure debt owner modularization）：
   - 結果：與 blueprint `infrastructure/sec/xbrl` 的 service decomposition 方向一致（entrypoint 薄化、owner 邊界明確、fallback 流程去重）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「strict/relaxed fallback 分支必須共用 extraction owner，以 config transformation 切換」規約。`
536. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批進入 `domain/valuation/assumptions.py` 大切片，採 capability-based policy 拆分（growth/manual/forward-signal），並以「原子遷移 call sites + 刪除舊 owner」達成無 compatibility façade 收斂。
537. P3/P4 較大切片（domain assumptions monolith 拆分 + no-compat migration）：
   - 新增 domain policy owners：
     - `domain/valuation/policies/growth_assumption_policy.py`
     - `domain/valuation/policies/manual_assumption_policy.py`
     - `domain/valuation/policies/forward_signal_policy.py`
   - call sites 原子遷移：
     - `param_builder_growth_blend_service.py`
     - `param_builder_policy_service.py`
     - `param_builder_registry_service.py`
     - `param_builders/bank_capm_policy_service.py`
     - `param_builders/saas_capm_policy_service.py`
     - `param_builders/saas_operating_rates_policy_service.py`
     - `tests/test_forward_signal_policy.py`
     - `tests/test_fundamental_growth_blender.py`
   - 路徑清理（不保留 compatibility layer）：
     - 刪除 `domain/valuation/assumptions.py`
   - 補充：
     - `policies/__init__.py` 匯出更新為 capability-oriented policy exports。
538. 驗證結果（P3/P4 domain assumptions decomposition / remove compatibility）：
   - `ruff check` 通過：
     - `domain/valuation/policies/*`
     - `domain/valuation/param_builder_*`（受影響檔案）
     - `domain/valuation/param_builders/*`（受影響檔案）
     - `tests/test_forward_signal_policy.py`
     - `tests/test_fundamental_growth_blender.py`
   - `pytest -q` 通過：
     - `test_forward_signal_policy.py`
     - `test_fundamental_growth_blender.py`
     - `test_param_builder_canonical_reports.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_error_handling_fundamental.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`37 passed`（含既有 warnings）
539. 計畫對齊檢查（P4 domain policy owner modularization / no-compat execution）：
   - 結果：與 blueprint `domain/valuation/policies` 方向一致（policy owner 清晰化，移除 assumptions 混責任入口）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「domain policy monolith 不可長期存在，必須 capability-based owner 拆分並原子遷移 call sites」規約。`
540. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批優先完成 `infrastructure/sec_xbrl/fls_filter.py` 大切片，採「stateful lifecycle owner + pure processing service」拆分，以提高內聚與可測性，同時維持既有 entrypoint 行為。
541. P3/P4 較大切片（sec_xbrl fls_filter owner decomposition）：
   - 新增 fls owners：
     - `infrastructure/sec_xbrl/fls_filter_prefilter_service.py`
     - `infrastructure/sec_xbrl/fls_filter_inference_service.py`
     - `infrastructure/sec_xbrl/fls_filter_stats.py`
   - `infrastructure/sec_xbrl/fls_filter.py` 收斂為 stateful orchestrator：
     - 保留 classifier lifecycle（load/warmup/cache/concurrency/fallback 入口）
     - prefilter 規則委派到 `prefilter_for_inference(...)`
     - inference batching/cache-key/label resolution 委派到 `predict_labels_with_cache(...)` / `predict_keep_flags_torch(...)`
     - stats owner 統一為 `FLSFilterStats`
   - 結構改善：
     - `fls_filter.py` LOC `501 -> 327`
     - 保持既有 public entrypoints：
       - `filter_forward_looking_sentences(...)`
       - `filter_forward_looking_sentences_with_stats(...)`
       - `warmup_forward_looking_filter(...)`
542. 驗證結果（P3/P4 sec_xbrl fls_filter decomposition）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/fls_filter.py`
     - `infrastructure/sec_xbrl/fls_filter_prefilter_service.py`
     - `infrastructure/sec_xbrl/fls_filter_inference_service.py`
     - `infrastructure/sec_xbrl/fls_filter_stats.py`
   - `pytest -q` 通過：
     - `test_sec_text_sentence_pipeline.py`
     - `test_sec_text_model_loader_circuit_breaker.py`
     - `test_sec_text_forward_signals.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`46 passed`（含既有 warnings）
543. 計畫對齊檢查（P4 infrastructure fls_filter decomposition / maintainability-first）：
   - 結果：與 blueprint `infrastructure/sec/xbrl` 拆分方向一致（orchestrator 保留 lifecycle，pure processing owner 外提）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「stateful inference owner 需拆成薄 orchestrator + prefilter/inference/stats owners」規約。`
544. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批進入 `domain/valuation/engine/monte_carlo.py` 大切片，採「maintainability/cohesion 優先」拆分，避免為 LOC 而犧牲責任邊界；保持外部呼叫契約不變。
545. P3/P4 較大切片（domain monte_carlo engine owner decomposition）：
   - 新增 domain owners：
     - `domain/valuation/engine/monte_carlo_contracts.py`
     - `domain/valuation/engine/monte_carlo_sampling_service.py`
     - `domain/valuation/engine/monte_carlo_psd_service.py`
     - `domain/valuation/engine/monte_carlo_diagnostics_service.py`
   - `domain/valuation/engine/monte_carlo.py` 收斂為 thin orchestrator：
     - 保留 `MonteCarloEngine.run(...)` batch orchestration / early-stop / final assembly
     - sampling + correlated draw + distribution transform 下沉至 `monte_carlo_sampling_service.py`
     - PSD repair policy（clip/higham/error）下沉至 `monte_carlo_psd_service.py`
     - summary/convergence/correlation diagnostics 下沉至 `monte_carlo_diagnostics_service.py`
     - contracts owner 收斂至 `monte_carlo_contracts.py`，`monte_carlo.py` 僅 re-export public API
   - 結構改善：
     - `monte_carlo.py` LOC `796 -> 124`
     - 無新增 compatibility alias/shim；既有 import 入口 `...engine.monte_carlo` 保持可用
546. 驗證結果（P3/P4 domain monte_carlo decomposition）：
   - `ruff check` 通過：
     - `domain/valuation/engine/monte_carlo.py`
     - `domain/valuation/engine/monte_carlo_contracts.py`
     - `domain/valuation/engine/monte_carlo_sampling_service.py`
     - `domain/valuation/engine/monte_carlo_psd_service.py`
     - `domain/valuation/engine/monte_carlo_diagnostics_service.py`
   - `pytest -q` 通過：
     - `test_monte_carlo_engine.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_dcf_graph_tools.py`
     - `test_fundamental_application_services.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`52 passed`（含既有 warnings）
547. 計畫對齊檢查（P4 domain monte_carlo decomposition / maintainability-first）：
   - 結果：與 blueprint `domain/valuation/monte_carlo` 拆分方向一致（contracts/sampling/diagnostics/psd owner 邊界明確，engine entrypoint 薄化）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「deterministic engine 不可混放 contracts + orchestration + low-level math，需拆為 contracts + thin engine + owner services」規約。`
548. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批進入 `infrastructure/sec_xbrl/base_model_income_cashflow_builder.py` 大切片，採「內聚優先」拆分為 config/component/derived owners，避免為 LOC 下降而犧牲可維護性與責任邊界。
549. P3/P4 較大切片（sec_xbrl income/cashflow builder owner decomposition）：
   - 新增 income/cashflow owners：
     - `infrastructure/sec_xbrl/base_model_income_cashflow_contracts.py`
     - `infrastructure/sec_xbrl/base_model_income_cashflow_config_service.py`
     - `infrastructure/sec_xbrl/base_model_income_cashflow_component_extraction_service.py`
     - `infrastructure/sec_xbrl/base_model_income_cashflow_derived_metrics_service.py`
   - `infrastructure/sec_xbrl/base_model_income_cashflow_builder.py` 收斂為 thin orchestrator：
     - config bundle 組裝委派 `build_income_cashflow_config_bundle(...)`
     - source extraction/EBITDA 組裝委派 `extract_income_cashflow_component_fields(...)`
     - ratio/derived metrics 委派 `build_income_cashflow_derived_metrics(...)`
     - builder 僅保留 orchestration + final `IncomeCashflowDerivedFields` assembly
   - 結構改善：
     - `base_model_income_cashflow_builder.py` LOC `456 -> 94`
     - 不新增 compatibility alias/shim；既有 `IncomeCashflowOps` 與 `build_income_cashflow_and_derived_fields(...)` 入口保持可用
550. 驗證結果（P3/P4 sec_xbrl income/cashflow decomposition）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/base_model_income_cashflow_builder.py`
     - `infrastructure/sec_xbrl/base_model_income_cashflow_contracts.py`
     - `infrastructure/sec_xbrl/base_model_income_cashflow_config_service.py`
     - `infrastructure/sec_xbrl/base_model_income_cashflow_component_extraction_service.py`
     - `infrastructure/sec_xbrl/base_model_income_cashflow_derived_metrics_service.py`
     - `infrastructure/sec_xbrl/factory.py`
     - `infrastructure/sec_xbrl/base_model_assembler.py`
   - `pytest -q` 通過：
     - `test_sec_xbrl_total_debt_policy.py`
     - `test_sec_xbrl_resolver.py`
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_sec_text_forward_signals.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`65 passed`（含既有 warnings）
551. 計畫對齊檢查（P4 infrastructure income/cashflow decomposition / maintainability-first）：
   - 結果：與 blueprint `infrastructure/sec/xbrl` 拆分方向一致（statement builder owner 邊界清楚，entrypoint 薄化）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「financial statement builder 不可混放 concept catalog + extraction + derived metrics，需拆為 config/component/derived owners」規約。`
552. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批進入 `infrastructure/sec_xbrl/record_processor.py` 大切片，採「pipeline entrypoint 薄化」策略，將 record-level preparation 與 metric-level aggregation 分離，避免單檔混責任。
553. P3/P4 較大切片（sec_xbrl record_processor owner decomposition）：
   - 新增 text pipeline owners：
     - `infrastructure/sec_xbrl/record_processor_preparation_service.py`
     - `infrastructure/sec_xbrl/record_processor_metric_service.py`
   - `infrastructure/sec_xbrl/record_processor.py` 收斂為 thin orchestrator：
     - record preparation（focus/8-K/FLS/doc metadata）委派 `prepare_record_processing_payload(...)`
     - metric hit aggregation/evidence merge 委派 `process_metric_signal_for_record(...)`
     - 主檔僅保留 batch orchestration、retrieval preview、pipeline diagnostics accumulation
   - 結構改善：
     - `record_processor.py` LOC `441 -> 233`
     - 不新增 compatibility alias/shim；既有入口 `_process_records_for_signals(...)` 保持可用
554. 驗證結果（P3/P4 sec_xbrl record_processor decomposition）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/record_processor.py`
     - `infrastructure/sec_xbrl/record_processor_preparation_service.py`
     - `infrastructure/sec_xbrl/record_processor_metric_service.py`
     - `infrastructure/sec_xbrl/forward_signals_text.py`
   - `pytest -q` 通過：
     - `test_sec_text_forward_signals.py`
     - `test_sec_text_forward_signals_eval.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_sec_text_sentence_pipeline.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`34 passed`（含既有 warnings）
555. 計畫對齊檢查（P4 infrastructure record_processor decomposition / maintainability-first）：
   - 結果：與 blueprint `infrastructure/sec/xbrl/text_signals` 方向一致（record preparation 與 metric aggregation owner 分離，entrypoint 轉為 orchestration-only）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「text pipeline processor 不可混放 record preparation 與 metric aggregation/evidence policy，需拆為 preparation + metric owners」規約。`
556. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批進入 `domain/valuation/policies/forward_signal_policy.py` 大切片，採「policy capability owner」拆分（contracts/parser/scoring），避免 payload parsing 與 scoring 決策混檔。
557. P3/P4 較大切片（domain forward_signal_policy owner decomposition）：
   - 新增 policy owners：
     - `domain/valuation/policies/forward_signal_contracts.py`
     - `domain/valuation/policies/forward_signal_parser_service.py`
     - `domain/valuation/policies/forward_signal_scoring_service.py`
   - `domain/valuation/policies/forward_signal_policy.py` 收斂為 thin entrypoint：
     - dataclass/constants owner 下沉至 contracts module
     - parsing owner 下沉至 parser service
     - weighting/risk/scoring owner 下沉至 scoring service
     - 主檔保留 public exports（`parse_forward_signals` / `apply_forward_signal_policy`）
   - 結構改善：
     - `forward_signal_policy.py` LOC `423 -> 33`
     - 不新增 compatibility alias/shim；既有 import path 保持可用
558. 驗證結果（P3/P4 domain forward_signal_policy decomposition）：
   - `ruff check` 通過：
     - `domain/valuation/policies/forward_signal_policy.py`
     - `domain/valuation/policies/forward_signal_contracts.py`
     - `domain/valuation/policies/forward_signal_parser_service.py`
     - `domain/valuation/policies/forward_signal_scoring_service.py`
     - `domain/valuation/param_builder_policy_service.py`
     - `domain/valuation/policies/__init__.py`
     - `tests/test_forward_signal_policy.py`
   - `pytest -q` 通過：
     - `test_forward_signal_policy.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_application_services.py`
     - `test_fundamental_growth_blender.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`33 passed`（含既有 warnings）
559. 計畫對齊檢查（P4 domain forward_signal_policy decomposition / maintainability-first）：
   - 結果：與 blueprint `domain/valuation/policies` 方向一致（policy parsing 與 scoring owner 邊界明確，entrypoint 薄化）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「policy 模組不得混放 payload parsing + scoring/risk 決策，需拆為 parser + scoring owners」規約。`
560. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：本批進入 `application/use_cases/run_valuation_use_case.py` 大切片，採「use-case orchestration 薄化」策略，將 context loading、execution、completion fields 拆為 owner services，避免主檔混責任。
561. P3/P4 較大切片（application run_valuation_use_case owner decomposition）：
   - 新增 application service owners：
     - `application/services/valuation_execution_context_service.py`
     - `application/services/valuation_execution_result_service.py`
     - `application/services/valuation_completion_fields_service.py`
   - `application/use_cases/run_valuation_use_case.py` 收斂為 thin use-case entrypoint：
     - state/runtime/artifact 載入與驗證委派 `resolve_valuation_execution_context(...)`
     - param build + calculator execution + result parse 委派 `execute_valuation_calculation(...)`
     - completion telemetry fields（monte carlo / forward signals）委派 dedicated completion service
     - 主檔僅保留 node-level branching、error mapping、state update routing、事件發送
   - 結構改善：
     - `run_valuation_use_case.py` LOC `374 -> 236`
     - 不新增 compatibility alias/shim；既有 use-case entrypoint 與 log event 行為保持可用
562. 驗證結果（P3/P4 application run_valuation_use_case decomposition）：
   - `ruff check` 通過：
     - `application/use_cases/run_valuation_use_case.py`
     - `application/services/valuation_execution_context_service.py`
     - `application/services/valuation_execution_result_service.py`
     - `application/services/valuation_completion_fields_service.py`
   - `pytest -q` 通過：
     - `test_fundamental_orchestrator_logging.py`
     - `test_error_handling_fundamental.py`
     - `test_fundamental_application_services.py`
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`35 passed`（含既有 warnings）
563. 計畫對齊檢查（P4 application run_valuation_use_case decomposition / maintainability-first）：
   - 結果：與 blueprint `application/use_cases + application/services` 方向一致（use-case entrypoint 薄化，context/execution/completion owner 邊界明確）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「application run_* use-case 不可混放 context loading + execution + completion shaping，需拆為 context/execution/completion owners」規約。`
564. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：優先完成 `infrastructure/sec_xbrl/hybrid_retriever.py` owner 拆分，將 dense model lifecycle、sparse ranking、fusion policy 與 entrypoint orchestration 分離。
565. P3/P4 較大切片（sec_xbrl hybrid_retriever owner decomposition）：
   - 新增 retrieval owners：
     - `infrastructure/sec_xbrl/hybrid_retriever_dense_service.py`
     - `infrastructure/sec_xbrl/hybrid_retriever_sparse_service.py`
     - `infrastructure/sec_xbrl/hybrid_retriever_fusion_service.py`
   - `infrastructure/sec_xbrl/hybrid_retriever.py` 收斂為 thin orchestrator：
     - dense retrieval lifecycle（model load/cache/embedding）委派 `hybrid_retriever_dense_service`
     - sparse ranking owner 委派 `sparse_rank_many(...)`
     - RRF fusion owner 委派 `rrf_fuse(...)`
     - 主檔保留 retrieval entrypoints：`retrieve_relevant_sentences` / `retrieve_relevant_sentences_batch`
   - 結構改善：
     - `hybrid_retriever.py` 收斂為 `58 LOC` orchestration-only entrypoint
     - 不新增 compatibility shim；既有 API 入口保持可用
566. 驗證結果（P3/P4 sec_xbrl hybrid_retriever decomposition）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/hybrid_retriever.py`
     - `infrastructure/sec_xbrl/hybrid_retriever_dense_service.py`
     - `infrastructure/sec_xbrl/hybrid_retriever_sparse_service.py`
     - `infrastructure/sec_xbrl/hybrid_retriever_fusion_service.py`
   - `pytest -q` 通過：
     - `test_sec_text_sentence_pipeline.py`
     - `test_sec_text_model_loader_circuit_breaker.py`
     - `test_sec_text_forward_signals.py`
     - `test_sec_text_forward_signals_eval.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`48 passed`（含既有 warnings）
567. 計畫對齊檢查（P4 infrastructure hybrid_retriever decomposition / maintainability-first）：
   - 結果：與 blueprint `infrastructure/sec_xbrl` 方向一致（retrieval orchestration 與 dense/sparse/fusion owners 分離，entrypoint 薄化）
   - 偏離：無
   - `Lessons Review: no_update`
   - `原因：本批主要是 owner 拆分與 entrypoint 薄化，未引入新的反模式類型。`
568. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 `infrastructure/sec_xbrl/pipeline_helpers.py` 大切片，移除 catch-all helpers 聚合桶並改為 capability owner modules。
569. P3/P4 較大切片（sec_xbrl pipeline_helpers capability-owner decomposition / no-compat）：
   - 新增 capability owners：
     - `infrastructure/sec_xbrl/pipeline_scalar_service.py`
     - `infrastructure/sec_xbrl/pipeline_text_normalization_service.py`
     - `infrastructure/sec_xbrl/pipeline_filing_access_service.py`
     - `infrastructure/sec_xbrl/pipeline_filing_metadata_service.py`
     - `infrastructure/sec_xbrl/pipeline_evidence_service.py`
   - 遷移 call sites：
     - `infrastructure/sec_xbrl/forward_signals_text.py`
     - `infrastructure/sec_xbrl/text_signal_record_loader_service.py`
     - `infrastructure/sec_xbrl/focus_text_extractor.py`
     - `tests/test_sec_text_forward_signals.py`
   - 移除舊模組：
     - 刪除 `infrastructure/sec_xbrl/pipeline_helpers.py`
   - 結構改善：
     - 不保留 compatibility re-export/shim；call sites 已原子遷移至語義 owner 模組
570. 驗證結果（P3/P4 sec_xbrl pipeline helper decomposition）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/pipeline_scalar_service.py`
     - `infrastructure/sec_xbrl/pipeline_text_normalization_service.py`
     - `infrastructure/sec_xbrl/pipeline_filing_access_service.py`
     - `infrastructure/sec_xbrl/pipeline_filing_metadata_service.py`
     - `infrastructure/sec_xbrl/pipeline_evidence_service.py`
     - `infrastructure/sec_xbrl/forward_signals_text.py`
     - `infrastructure/sec_xbrl/text_signal_record_loader_service.py`
     - `infrastructure/sec_xbrl/focus_text_extractor.py`
     - `tests/test_sec_text_forward_signals.py`
   - `pytest -q` 通過：
     - `test_sec_text_sentence_pipeline.py`
     - `test_sec_text_model_loader_circuit_breaker.py`
     - `test_sec_text_forward_signals.py`
     - `test_sec_text_forward_signals_eval.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`48 passed`（含既有 warnings）
571. 計畫對齊檢查（P4 infrastructure pipeline helper decomposition / no-compat）：
   - 結果：與 blueprint `infrastructure/sec_xbrl` 方向一致（payload shaping / filing access / normalization / evidence policy owner 邊界明確化）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「禁止 catch-all helpers 模組，需以 capability owners 直接承載並原子遷移 call sites」規約。`
572. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 `domain/model_selection.py` 大切片，採「內聚優先」拆分為 contracts/spec-catalog/signal/scoring/reasoning owners，避免主檔混責任。
573. P3/P4 較大切片（domain model_selection capability-owner decomposition）：
   - 新增 domain owners：
     - `domain/model_selection_contracts.py`
     - `domain/model_selection_spec_catalog.py`
     - `domain/model_selection_signal_service.py`
     - `domain/model_selection_scoring_service.py`
     - `domain/model_selection_reasoning_service.py`
   - `domain/model_selection.py` 收斂為 thin entrypoint：
     - 保留對外 API：`select_valuation_model(...)`
     - 評分入口 `_evaluate_spec(...)` 委派 `evaluate_model_spec(...)`
     - 主檔僅保留 logging + owner delegation + top candidate assembly
   - 結構改善：
     - `model_selection.py` LOC `409 -> 97`
     - 不新增 compatibility shim；既有 imports（含測試）保持可用
574. 驗證結果（P3/P4 domain model_selection decomposition）：
   - `ruff check` 通過：
     - `domain/model_selection.py`
     - `domain/model_selection_contracts.py`
     - `domain/model_selection_spec_catalog.py`
     - `domain/model_selection_signal_service.py`
     - `domain/model_selection_scoring_service.py`
     - `domain/model_selection_reasoning_service.py`
     - `tests/test_model_selection_scoring_weights.py`
     - `tests/test_fundamental_model_selection_projection.py`
   - `pytest -q` 通過：
     - `test_fundamental_model_selection_projection.py`
     - `test_model_selection_scoring_weights.py`
     - `test_error_handling_fundamental.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_application_services.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`21 passed`（含既有 warnings）
575. 計畫對齊檢查（P4 domain model_selection decomposition / maintainability-first）：
   - 結果：與 blueprint `domain + application/use_cases` 收斂方向一致（model-selection domain 主檔薄化，catalog/signals/scoring/reasoning owner 邊界明確）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「model_selection 不得混放 contracts/catalog/signals/scoring/reasoning，需拆為 capability owners + thin entrypoint」規約。`
576. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 `domain/valuation/backtest.py` 大切片，採「維護性/內聚優先」拆分為 contracts/I-O/runtime/drift/report owners，避免主檔混責任。
577. P3/P4 較大切片（domain valuation backtest capability-owner decomposition）：
   - 新增 domain owners：
     - `domain/valuation/backtest_contracts.py`
     - `domain/valuation/backtest_io_service.py`
     - `domain/valuation/backtest_runtime_service.py`
     - `domain/valuation/backtest_drift_service.py`
     - `domain/valuation/backtest_report_service.py`
   - `domain/valuation/backtest.py` 收斂為 thin API entrypoint：
     - 保留既有 API：`load_cases` / `load_baseline` / `run_cases` / `compare_with_baseline` / `build_baseline_payload` / `build_report_payload`
     - 主檔僅保留對外符號 re-export，不承載 dataset 解析、runtime 執行、drift 比對、report 組裝細節
   - 結構改善：
     - `backtest.py` LOC `399 -> 37`
     - 不新增 compatibility shim；scripts/tests 既有 import path 保持可用
578. 驗證結果（P3/P4 domain valuation backtest decomposition）：
   - `ruff check` 通過：
     - `domain/valuation/backtest.py`
     - `domain/valuation/backtest_contracts.py`
     - `domain/valuation/backtest_io_service.py`
     - `domain/valuation/backtest_runtime_service.py`
     - `domain/valuation/backtest_drift_service.py`
     - `domain/valuation/backtest_report_service.py`
     - `tests/test_fundamental_backtest_runner.py`
     - `scripts/run_fundamental_backtest.py`
   - `pytest -q` 通過：
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_import_hygiene_guard.py`
     - `test_fundamental_model_selection_projection.py`
     - `test_model_selection_scoring_weights.py`
   - 合計：`8 passed`（含既有 warnings）
579. 計畫對齊檢查（P4 domain valuation backtest decomposition / maintainability-first）：
   - 結果：與 blueprint `valuation/backtest baseline drift controllable` 方向一致（dataset/runtime/drift/report owner 邊界明確，entrypoint 薄化）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「backtest 不得混放 I/O/runtime/drift/report，需拆為 capability owners + thin backtest entrypoint」規約。`
580. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 `domain/valuation/calculators/dcf_variant_calculator.py` 核心大切片，採「內聚優先」拆分 validation / Monte Carlo distribution / result assembly owners，避免主檔混責任。
581. P3/P4 核心切片（domain dcf_variant_calculator capability-owner decomposition）：
   - 新增 calculator owners：
     - `domain/valuation/calculators/dcf_variant_contracts.py`
     - `domain/valuation/calculators/dcf_variant_validation_service.py`
     - `domain/valuation/calculators/dcf_variant_distribution_service.py`
     - `domain/valuation/calculators/dcf_variant_result_service.py`
   - `domain/valuation/calculators/dcf_variant_calculator.py` 收斂為 thin orchestrator：
     - validation 委派 `validate_dcf_variant_projection_lengths(...)`
     - Monte Carlo distribution 委派 `run_dcf_variant_monte_carlo(...)`
     - result/detail assembly 委派 `extract_dcf_variant_converged_inputs(...)` + `build_dcf_variant_details(...)`
     - 主檔保留對外契約與入口（`DcfVariantParams` / `DcfMonteCarloPolicy` / `calculate_dcf_variant_valuation`）
   - 結構改善：
     - `dcf_variant_calculator.py` LOC `381 -> 80`
     - 不新增 compatibility shim；`dcf_standard_calculator` / `dcf_growth_calculator` 既有 import 路徑保持可用
582. 驗證結果（P3/P4 domain dcf_variant_calculator decomposition）：
   - `ruff check` 通過：
     - `domain/valuation/calculators/dcf_variant_calculator.py`
     - `domain/valuation/calculators/dcf_variant_contracts.py`
     - `domain/valuation/calculators/dcf_variant_validation_service.py`
     - `domain/valuation/calculators/dcf_variant_distribution_service.py`
     - `domain/valuation/calculators/dcf_variant_result_service.py`
     - `domain/valuation/calculators/dcf_standard_calculator.py`
     - `domain/valuation/calculators/dcf_growth_calculator.py`
     - `domain/valuation/calculators/__init__.py`
   - `pytest -q` 通過：
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_backtest_runner.py`
     - `test_fundamental_import_hygiene_guard.py`
     - `test_param_builder_canonical_reports.py`
   - 合計：`35 passed`（含既有 warnings）
583. 計畫對齊檢查（P4 domain dcf_variant_calculator decomposition / maintainability-first）：
   - 結果：與 blueprint `domain calculators shared runtime support` 方向一致（shared DCF variant 主檔薄化，validation/distribution/result owners 邊界明確）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「DCF variant calculator 不得混放 validation/distribution/result assembly，需拆為 capability owners + thin entrypoint」規約。`
584. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 P5 最後收尾，優先移除 implementation compatibility residue：`sec_xbrl/utils.py` 與 extractor utility static wrappers，改為 capability service 直接依賴。
585. P5 最後收尾切片（remove utility-wrapper compatibility residue / no-compat）：
   - infrastructure 清理：
     - 新增 `infrastructure/sec_xbrl/financial_payload_service.py`（承接原 `utils.py` 的 financial payload owner）
     - `infrastructure/sec_xbrl/provider.py` 改為依賴 `financial_payload_service`，不再依賴 `utils.py`
     - 刪除 `infrastructure/sec_xbrl/utils.py`
   - extractor/resolver utility wrapper 清理：
     - `infrastructure/sec_xbrl/resolver.py` 改為直接依賴 `extractor_search_processing_service.period_sort_key/statement_matches`
     - `infrastructure/sec_xbrl/extractor.py` 移除 static utility wrappers（`_period_sort_key` / `_statement_matches` / `_normalize_unit` / `_identify_dimension_columns`）
   - tests 同步遷移：
     - `test_sec_text_forward_signals.py` patch 路徑改為 `financial_payload_service`
     - `test_sec_xbrl_mapping_fallbacks.py` 改為直接測 `extractor_search_processing_service` utilities
     - `test_sec_xbrl_provider_import_guard.py` banned implementation import 更新為 `financial_payload_service`
   - 收斂結果：
     - 不保留 compatibility shim/alias；舊 `utils.py` 入口已完全移除
586. 驗證結果（P5 utility-wrapper residue cleanup）：
   - `ruff check` 通過：
     - `infrastructure/sec_xbrl/provider.py`
     - `infrastructure/sec_xbrl/financial_payload_service.py`
     - `infrastructure/sec_xbrl/resolver.py`
     - `infrastructure/sec_xbrl/extractor.py`
     - `tests/test_sec_text_forward_signals.py`
     - `tests/test_sec_xbrl_mapping_fallbacks.py`
     - `tests/test_sec_xbrl_provider_import_guard.py`
   - `pytest -q` 通過：
     - `test_sec_text_forward_signals.py`
     - `test_sec_xbrl_mapping_fallbacks.py`
     - `test_sec_xbrl_provider_import_guard.py`
     - `test_sec_xbrl_resolver.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_fundamental_import_hygiene_guard.py`
   - 合計：`47 passed`（含既有 warnings）
587. 計畫對齊檢查（P5 remove utility-wrapper residue / zero-compat convergence）：
   - 結果：與 blueprint/P5 及「最終零相容層」方向一致（utility compatibility residue 已清除，implementation owner 路徑語義化）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「不得保留 utils/static-wrapper 類型 implementation residue，需改為 capability service 直接依賴」規約。`
588. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：核心架構已收斂，先做 post-convergence baseline 驗證，並清理可直接修復的 runtime contract deprecation 噪音（不新增 compatibility layer）。
589. P5 維持性驗證切片（fundamental curated baseline / fixed explicit-file execution）：
   - 執行 `fundamental/sec/param_builder/dcf` 定向 baseline（33 test files）：
     - `pytest -q` 結果：`181 passed, 5 skipped, 3 warnings`
   - 變更重點：
     - 修正 baseline 執行方式為明確檔案集合（避免動態拼接造成 pytest path argument 誤判）
     - 確認 refactor 主線無新增 regressions；現存 warning 僅剩第三方 `edgar` deprecation
590. P5 維持性清理（Pydantic V2 contract deprecation hardening）：
   - `domain/valuation/models/saas/contracts.py`：
     - `Field(min_items/max_items)` -> `Field(min_length/max_length)`（行為不變）
   - 驗證結果：
     - `ruff check` 通過：`domain/valuation/models/saas/contracts.py`
     - `pytest -q` 通過：
       - `test_saas_monte_carlo_integration.py`
       - `test_dcf_graph_tools.py`
     - re-run curated baseline：`181 passed, 5 skipped, 3 warnings`
591. 計畫對齊檢查（P5 post-convergence maintenance / deprecation hardening）：
   - 結果：與 blueprint/P5 一致（維持零相容層，不回引 shim；以 regression baseline + 小幅硬化維持可運行收斂）
   - 偏離：無
   - `Lessons Review: no_update`
   - `原因：本批為驗證基線與框架 deprecation 參數更新，未新增跨 agent 架構反模式。`
592. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 P5 維持性大切片，收斂 `valuation/param_builder*.py` + `valuation/param_builders/*` 分散邊界，整合為單一 capability package，避免後續跨 agent 複製結構反模式。
593. P5 較大切片（valuation parameterization package convergence / no-compat）：
   - 結構收斂：
     - 新增 package：`domain/valuation/parameterization/`
     - 搬遷 `domain/valuation/param_builder*.py` -> `domain/valuation/parameterization/param_builder*.py`
     - `domain/valuation/param_builders/` 重新命名與搬遷為 `domain/valuation/parameterization/model_builders/`
   - call sites 全量遷移（不保留 compatibility shim）：
     - `application/*`、`domain/valuation/calculators/*`、`domain/valuation/models/base_valuation_params.py`、`tests/*` 的 import 路徑改為 `domain.valuation.parameterization.*`
     - `valuation/__init__.py` 改為由 `parameterization` canonical boundary re-export `build_params` / `ParamBuildResult`
   - package 內依賴收斂：
     - `param_builder_payload_dispatch_service.py` 改依賴 `.model_builders.*`
     - `model_builders/*` 內跨層 import 修正為 `...report_contract` / `...policies.*`
     - 新增 `parameterization/__init__.py` 作為明確 owner 邊界入口
594. 驗證結果（P5 valuation parameterization package convergence）：
   - `ruff check` 通過：
     - `src/agents/fundamental/domain/valuation/*`
     - `src/agents/fundamental/application/*`
     - `tests/test_param_builder_canonical_reports.py`
     - `tests/test_fundamental_orchestrator_logging.py`
   - `pytest -q` 通過（核心回歸）：
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_application_services.py`
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - 合計：`43 passed`
   - `pytest -q` 通過（curated baseline）：
     - `fundamental/sec/param_builder/dcf` 33 files
     - 合計：`181 passed, 5 skipped, 3 warnings`
595. 計畫對齊檢查（P5 capability package boundary convergence / maintainability-first）：
   - 結果：與 blueprint `Phase 2 service decomposition + Phase 4 naming cleanup` 一致（`parameterization` 單一 owner 邊界明確，原先分散命名結構已收斂）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「同一 bounded capability 不得分散在 root 前綴檔與 sibling package，需收斂為單一 canonical capability package」規約。`
596. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 P5 naming convergence 大切片，收斂 `parameterization` package 內的 `param_builder_*` module stutter；採 no-compat 原子遷移 call sites。
597. P5 較大切片（parameterization inner naming convergence / remove module stutter）：
   - `domain/valuation/parameterization/` 檔名語義化：
     - `param_builder.py` -> `orchestrator.py`
     - `param_builder_contracts.py` -> `contracts.py`
     - `param_builder_types.py` -> `types.py`
     - `param_builder_*_service.py` -> `*_service.py`（去除 `param_builder_` 前綴）
   - import/call sites 原子遷移（不保留 compatibility shim）：
     - `application/*`、`domain/valuation/calculators/*`、`domain/valuation/models/base_valuation_params.py`、`tests/*` 皆改為 `domain.valuation.parameterization.{orchestrator,contracts,types,...}`
     - `parameterization/__init__.py` 改為由 `{orchestrator,contracts}` re-export
   - 結構結果：
     - `parameterization` package 邊界維持單一 canonical owner，且 package 內 module naming 去 stutter 完成
598. 驗證結果（P5 parameterization inner naming convergence）：
   - `ruff check` 通過：
     - `src/agents/fundamental/domain/valuation/parameterization/*`
     - `src/agents/fundamental/domain/valuation/calculators/*`
     - `src/agents/fundamental/domain/valuation/models/base_valuation_params.py`
     - `src/agents/fundamental/application/*`
   - `pytest -q` 通過（核心回歸）：
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_application_services.py`
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_import_hygiene_guard.py`
     - 合計：`45 passed`
   - `pytest -q` 通過（curated baseline）：
     - `fundamental/sec/param_builder/dcf` 33 files
     - 合計：`181 passed, 5 skipped, 3 warnings`
599. 計畫對齊檢查（P5 canonical package inner naming cleanup / maintainability-first）：
   - 結果：與 blueprint `Phase 4 naming cleanup` 方向一致（canonical package 內命名語義化、stutter 降噪、owner 邊界可掃描性提升）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「canonical capability package 內不得重複能力前綴命名，需使用語義 owner 模組名」規約。`
600. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 P5 較大切片，進一步收斂 `parameterization/model_builders` 內聚性：由單層平鋪改為 `per-model subpackages + shared subpackage`。
601. P5 較大切片（model_builders package stratification / maintainability-first）：
   - 目錄收斂：
     - 新增 subpackages：
       - `model_builders/bank/`
       - `model_builders/saas/`
       - `model_builders/reit/`
       - `model_builders/eva/`
       - `model_builders/residual_income/`
       - `model_builders/multiples/`
       - `model_builders/dcf/`
       - `model_builders/shared/`
     - 既有 model-specific modules 依能力搬遷到對應子 package（例如 `bank/*`, `saas/*`, `reit/*`, `dcf/*`）。
     - 跨模型共用模組搬遷到 `model_builders/shared/*`（capital/equity extraction、common output、missing metrics、value extraction、capm defaults）。
   - package 邊界對齊：
     - `model_builders/context.py` 保留在 parent，作為 builder deps/context owner
     - `payload_dispatch_service.py` 保留在 parent，作為 variant dispatch owner
     - 各子 package 新增 `__init__.py`，維持穩定 package-level exports
   - import/call sites 原子遷移（不保留 compatibility shim）：
     - `payload_dispatch_service.py` 改為依賴 `model_builders.{bank,dcf,eva,multiples,reit,residual_income,saas}`
     - 各 model 子包改用 `..shared.*` 與 `...{types,core_ops_service}` 等語義層級引用
602. 驗證結果（P5 model_builders package stratification）：
   - `ruff check` 通過：
     - `src/agents/fundamental/domain/valuation/parameterization/*`
     - `src/agents/fundamental/domain/valuation/calculators/*`
     - `src/agents/fundamental/application/*`
     - `tests/test_param_builder_canonical_reports.py`
     - `tests/test_fundamental_orchestrator_logging.py`
   - `pytest -q` 通過（核心回歸）：
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_application_services.py`
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - `test_fundamental_import_hygiene_guard.py`
     - 合計：`45 passed`
   - `pytest -q` 通過（curated baseline）：
     - `fundamental/sec/param_builder/dcf` 33 files
     - 合計：`181 passed, 5 skipped, 3 warnings`
603. 計畫對齊檢查（P5 model_builders package stratification / maintainability-first）：
   - 結果：與 blueprint `Phase 2 service decomposition + Phase 4 naming cleanup` 一致（parameterization 下 model-specific 與 shared owner 邊界更明確，平鋪結構收斂）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「model-builders 不得單層平鋪，需採 per-model subpackages + shared subpackage」規約。`
604. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：進入 P3/P4 大切片，拆分 `parameterization/policy_service.py` 的混合責任，收斂為 parser/adjustment/time-alignment guard capability owners。
605. P3/P4 較大切片（parameterization policy owner decomposition）：
   - 新增 capability owners：
     - `domain/valuation/parameterization/forward_signal_parser_service.py`
     - `domain/valuation/parameterization/forward_signal_adjustment_service.py`
     - `domain/valuation/parameterization/time_alignment_guard_service.py`
   - `domain/valuation/parameterization/policy_service.py` 改為 thin entrypoint/re-export：
     - 不再承載 parsing/adjustment/time-alignment 實作
     - 對外入口符號保持穩定（`apply_forward_signal_adjustments`、`apply_time_alignment_guard` 等）
   - 收斂結果：
     - forward-signal payload parsing、forward-signal parameter adjustment、time-alignment freshness guard 三者 owner 邊界已解耦
     - orchestrator call sites 無需擴散改動
606. 驗證結果（P3/P4 policy owner decomposition）：
   - `ruff check` 通過：
     - `domain/valuation/parameterization/policy_service.py`
     - `domain/valuation/parameterization/forward_signal_parser_service.py`
     - `domain/valuation/parameterization/forward_signal_adjustment_service.py`
     - `domain/valuation/parameterization/time_alignment_guard_service.py`
   - `pytest -q` 通過：
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_application_services.py`
     - `test_forward_signal_policy.py`
     - 合計：`33 passed`
607. 計畫對齊檢查（P3/P4 policy decomposition / maintainability-first）：
   - 結果：與 blueprint `Phase 2 service decomposition` 一致（policy capability owners 邊界更清晰，`policy_service.py` 已收斂為薄入口）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「policy-oriented package 不得在單檔混放 forward-signal 與 time-alignment guard 等獨立能力」規約。`
608. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：執行「避免過度設計」的中等切片；只拆 `model_builder_factory_service.py` 的通用 adapter 責任，維持既有入口與行為，不引入額外抽象層。
609. P3/P4 中等切片（model builder factory owner 邊界收斂 / no-overdesign）：
   - 新增 `domain/valuation/parameterization/model_builder_adapter_service.py`：
     - 擁有通用 adapter 責任（multi-report / latest-only payload -> model builder）
     - 集中 `ContextProvider`、`AssembleResultOp` 等 builder wiring type aliases
   - `domain/valuation/parameterization/model_builder_factory_service.py` 收斂：
     - 移除內部通用 `_build_multi_report_model_builder` / `_build_latest_only_model_builder`
     - 保留 variant-level payload wiring（dcf/multi-report/ev-multiple/single-report）
     - 行為不變，call sites 無需擴散改動
610. 驗證結果（P3/P4 model builder factory owner convergence）：
   - `ruff check` 通過：
     - `domain/valuation/parameterization/model_builder_adapter_service.py`
     - `domain/valuation/parameterization/model_builder_factory_service.py`
   - `pytest -q` 通過：
     - `test_param_builder_canonical_reports.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_application_services.py`
     - `test_dcf_graph_tools.py`
     - `test_bank_reit_strategyized_models.py`
     - `test_saas_monte_carlo_integration.py`
     - 合計：`43 passed`
611. 計畫對齊檢查（P3/P4 model builder factory boundary refinement / maintainability-first）：
   - 結果：與 blueprint `Phase 2 service decomposition` 一致（factory 與 adapter owner 邊界更清晰，且未引入過度抽象）
   - 偏離：無
   - `Lessons Review: no_update`
   - `原因：本批屬既有規約落地（owner 邊界收斂與薄 factory），未新增跨 agent 新反模式。`
612. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：改用較大切片合併重構，且以「不過度設計」為原則，同批完成 application concrete 依賴收斂 + registry import-time side effect 清理 + infrastructure provider owner 命名收斂。
613. P3/P4 較大切片（application boundary + registry bootstrap + provider naming convergence）：
   - application 邊界收斂：
     - `application/ports.py` 補齊 `IFundamentalReportRepo.load_financial_reports_bundle(...)`
     - `application/orchestrator.py` 改依賴 `IFundamentalReportRepo`（移除對 `FundamentalArtifactRepository` concrete 型別依賴）
     - `infrastructure/artifacts/fundamental_artifact_repository.py` 新增 `load_financial_reports_bundle(...)`
   - composition root 收斂（concrete wiring 移出 application）：
     - `application/factory.py` 改為 pure application assembly（需顯式注入 `port/fetch provider/market service`）
     - 新增 `agents/fundamental/wiring.py` 作為 concrete wiring owner，提供 `fundamental_workflow_runner`
     - `workflow/nodes/fundamental_analysis/nodes.py` 改由 `agents.fundamental.wiring` 取用 runtime
   - registry import-time side effect 清理：
     - `infrastructure/sec_xbrl/mapping.py` 移除 import-time `_register_default_mappings()` 呼叫
     - 新增 `build_default_mapping_registry()` + `get_mapping_registry()`（lazy/cached）
     - `infrastructure/sec_xbrl/factory.py` 改由 `get_mapping_registry()` 取得 registry
   - infrastructure provider 命名與檔案 owner 收斂：
     - 刪除 `infrastructure/market_data/providers.py`
     - 新增 `infrastructure/market_data/yahoo_finance_provider.py`
     - 新增 `infrastructure/market_data/fred_macro_provider.py`（`FredMacroProvider`）
     - `market_data_service.py` 改依賴新 provider owner modules
   - tests 同步遷移（無 compatibility shim）：
     - `test_sec_xbrl_mapping_fallbacks.py` / `test_sec_xbrl_extension_industry_routing.py` 改用 `get_mapping_registry()`
     - `test_fundamental_orchestrator_logging.py` fake repo 改提供 `load_financial_reports_bundle(...)`
     - `test_error_handling_fundamental.py` patch 目標改為新 wiring/portfolio 入口
614. 驗證結果（P3/P4 merged larger slice）：
   - `ruff check` 通過：
     - application/factory/orchestrator/ports
     - fundamental/wiring
     - workflow fundamental nodes
     - sec_xbrl mapping/factory
     - market_data service + provider modules
     - touched tests
   - `pytest -q` 通過（主回歸）：
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_application_services.py`
     - `test_error_handling_fundamental.py`
     - `test_fundamental_market_data_client.py`
     - `test_param_builder_canonical_reports.py`
     - `test_sec_xbrl_mapping_fallbacks.py`
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_forward_signal_policy.py`
     - 合計：`62 passed`
   - `pytest -q` 通過（guard 補驗）：
     - `test_fundamental_import_hygiene_guard.py`
     - `test_sec_xbrl_provider_import_guard.py`
     - 合計：`3 passed`
615. 計畫對齊檢查（P3/P4 merged larger slice / standards-strict）：
   - 結果：與 blueprint `Phase 2 service decomposition + Phase 4 naming cleanup` 一致（application 邊界 concrete 依賴移除、registry side effect 清除、provider owner 命名收斂）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「application concrete wiring 必須外置 composition module」與「registry 不得 import-time bootstrap」規約。`
616. Pre-check（本批開始前 standards + blueprint review）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - 結論：以較大切片完成「generic module 收斂」：同批清理 domain 泛名 owner modules + infrastructure sec_xbrl 泛名 contract module，且不保留 compatibility shim。
617. P3/P4 較大切片（generic module convergence / no-compat）：
   - domain owner 收斂（移除泛名模組）：
     - 刪除：
       - `domain/models.py`
       - `domain/rules.py`
       - `domain/services.py`
     - 新增 semantic owners：
       - `domain/valuation_model.py`
       - `domain/financial_math_service.py`
       - `domain/financial_health_service.py`
       - `domain/valuation_model_type_service.py`
       - `domain/valuation_output_service.py`
     - call sites 原子遷移（application/domain/tests）：
       - `application/services/model_selection_artifact_service.py`
       - `application/view_models.py`
       - `application/use_cases/run_model_selection_use_case.py`
       - `domain/model_selection_signal_service.py`
       - `test_domain_artifact_ports_fundamental.py`
       - `test_fundamental_model_type_mapping.py`
       - `test_fundamental_model_selection_projection.py`
       - `test_model_selection_scoring_weights.py`
   - infrastructure owner 收斂（sec_xbrl 泛名模組）：
     - `infrastructure/sec_xbrl/models.py` -> `infrastructure/sec_xbrl/report_contracts.py`
     - 原子更新 `sec_xbrl/*` 與相關 tests imports（不保留 alias/shim）。
618. 驗證結果（P3/P4 generic module convergence）：
   - 殘留路徑掃描通過（`rg`）：
     - 無 `src.agents.fundamental.domain.(models|rules|services)` 引用
     - 無 `sec_xbrl.models` / `.models import` 引用
   - `ruff check` 通過：
     - `src/agents/fundamental`（本批 touched 範圍）
     - `src/agents/fundamental/infrastructure/sec_xbrl`（重命名後全包）
     - touched tests
   - `pytest -q` 通過（domain/application 回歸）：
     - `test_domain_artifact_ports_fundamental.py`
     - `test_fundamental_model_type_mapping.py`
     - `test_fundamental_model_selection_projection.py`
     - `test_model_selection_scoring_weights.py`
     - `test_fundamental_orchestrator_logging.py`
     - `test_fundamental_application_services.py`
     - `test_error_handling_fundamental.py`
     - 合計：`27 passed`
   - `pytest -q` 通過（sec_xbrl 回歸）：
     - `test_sec_xbrl_extension_industry_routing.py`
     - `test_sec_xbrl_forward_signals.py`
     - `test_sec_xbrl_live_golden.py`
     - `test_sec_xbrl_provider_import_guard.py`
     - 合計：`23 passed, 5 skipped`
   - `pytest -q` 通過（guard 補驗）：
     - `test_fundamental_import_hygiene_guard.py`
     - 合計：`2 passed`
619. 計畫對齊檢查（P3/P4 generic module convergence / standards-strict）：
   - 結果：與 blueprint `Phase 2 service decomposition + Phase 4 naming cleanup` 一致（generic owner module 已收斂為語義化 capability owners，且無 compatibility 殘留）
   - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「成熟 bounded context 禁止 generic root modules（models/services/rules）」規約。`
620. Pre-check（治理切片：blueprint 同步）：
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - review `docs/backlog/fundamental_refactor_execution_tracker.md`
   - 結論：目前程式碼主線已收斂，但 blueprint 仍含舊目錄映射與舊 phase 描述；需同步文檔以降低後續判讀成本。
621. P5 治理切片（blueprint path/status convergence）：
   - 更新 `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`：
     - 狀態日期更新為 `2026-03-01`
     - 補充已完成項：application wiring 外置、generic module 收斂
     - `目標目錄` 與 `舊路徑到新路徑` 映射改為現況 canonical 路徑：
       - `infrastructure/sec_xbrl/*`
       - `infrastructure/market_data/{yahoo_finance_provider.py, fred_macro_provider.py}`
     - `分階段遷移計畫` 補充狀態：`Phase 0-4` 核心已完成、剩餘為 `P5` 非阻塞治理。
   - 驗證：
     - 文檔治理切片，無程式碼行為變更與測試需求。
   - 計畫對齊：
     - 與 blueprint 目標一致（收斂「文檔與實際目錄一致」）。
     - `Lessons Review: no_update`（本批僅文檔對齊，未新增新反模式）。
622. P5 治理切片（hygiene guard 強化：generic-module 回流防線）：
   - 更新 `tests/test_fundamental_import_hygiene_guard.py`：
     - 新增禁止 import 回流檢查：
       - `src.agents.fundamental.domain.models`
       - `src.agents.fundamental.domain.rules`
       - `src.agents.fundamental.domain.services`
       - `src.agents.fundamental.infrastructure.sec_xbrl.models`
     - 新增禁止 legacy 泛名模組檔案回流檢查：
       - `domain/models.py`
       - `domain/rules.py`
       - `domain/services.py`
       - `infrastructure/sec_xbrl/models.py`
   - 驗證：
     - `ruff check` 通過：`tests/test_fundamental_import_hygiene_guard.py`
     - `pytest -q` 通過：`4 passed`
   - 計畫對齊：
     - 與 blueprint `Phase 4 naming cleanup` 一致（防止 generic naming 回流）。
     - `Lessons Review: no_update`（既有規約落地，無新增反模式）。
623. Final Hardening Pre-check（standards + backlog 收斂檢查）：
   - review `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
   - review `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - review `docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
   - review `docs/backlog/fundamental_refactor_execution_tracker.md`
   - 結論：進入 final hardening 驗證批次；目標是用擴大 lint + regression 覆蓋確認 fundamental 主線已達「可交付收斂」。
624. Final Hardening 驗證結果（expanded lint + regression）：
   - `ruff check` 通過：
     - `src/agents/fundamental/*`（全 fundamental source 範圍）
     - fundamental/sec/param_builder 相關 tests（擴大集合）
   - `pytest -q` 通過（分片並行）：
     - fundamental 主線 + param builder + valuation integration：
       - `107 passed`
     - `test_sec_xbrl_*`：
       - `48 passed, 5 skipped`
     - `test_sec_text_*`：
       - `46 passed`
     - 匯總：
       - `201 passed, 5 skipped`
   - 注意：
     - 存在既有第三方 `edgar` deprecation warnings（非本次重構回歸）。
   - 計畫對齊：
     - 與 blueprint 目標一致（程式碼主線、命名、layer 邊界、治理守護均已收斂）。
     - `Lessons Review: no_update`（本批為驗證批次，無新增反模式/規約）。
625. 架構深度評審（valuation backtest package grouping）：
   - 評審範圍：
     - `domain/valuation/backtest.py`
     - `domain/valuation/backtest_contracts.py`
     - `domain/valuation/backtest_io_service.py`
     - `domain/valuation/backtest_runtime_service.py`
     - `domain/valuation/backtest_drift_service.py`
     - `domain/valuation/backtest_report_service.py`
   - 判定：
     - 建議「需要」升級為 `domain/valuation/backtest/` dedicated subpackage。
   - 依據：
     - 同一能力已有 `6` 個緊耦合 owner modules（總計約 `457 LOC`），且 capability 邊界已成熟（contracts/io/runtime/drift/report + thin entrypoint）。
     - 當前平鋪於 `valuation` root 會提高 package 掃描成本，與其他能力（registry/report_contract/parameterization）邊界混視。
   - 反思（為何此前未先做）：
     - 先前優先目標是「降低行為風險」與「快速完成 monolith 拆分」，因此先把職責拆分到 `backtest_*`，暫緩路徑重排，避免與同時進行的 `parameterization/sec_xbrl` 大切片產生路徑 churn 疊加風險。
     - 在 final hardening 前，尚未把「flat capability cluster 何時必須 package 化」抽成跨 agent 明確規約，導致決策依賴個人判斷。
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「成熟能力 4+ owner modules 應升級 dedicated subpackage，避免長期 flat <capability>_* cluster」規約。`
626. P3/P4 實作切片（一次對位：valuation backtest package 化）：
   - 目標：
     - 將 `domain/valuation` 下平鋪的 `backtest_*` 模組群原子收斂為 `domain/valuation/backtest/*` dedicated subpackage。
   - 實作內容：
     - 新增 package：
       - `domain/valuation/backtest/__init__.py`（保持 `valuation.backtest` 公開入口語義）
       - `domain/valuation/backtest/contracts.py`
       - `domain/valuation/backtest/io_service.py`
       - `domain/valuation/backtest/runtime_service.py`
       - `domain/valuation/backtest/drift_service.py`
       - `domain/valuation/backtest/report_service.py`
     - 移除 root 平鋪模組：
       - `domain/valuation/backtest.py`
       - `domain/valuation/backtest_contracts.py`
       - `domain/valuation/backtest_io_service.py`
       - `domain/valuation/backtest_runtime_service.py`
       - `domain/valuation/backtest_drift_service.py`
       - `domain/valuation/backtest_report_service.py`
     - package 內 imports 收斂為語義檔名（`contracts/io_service/runtime_service/drift_service/report_service`），並修正跨層引用為 `..valuation_model_registry`。
   - 驗證結果：
     - `ruff check` 通過：
       - `src/agents/fundamental/*`
       - expanded fundamental/sec tests
     - `pytest -q` 通過：
       - `test_fundamental_backtest_runner.py`：`3 passed`
       - fundamental 主線回歸：`107 passed`
       - sec_xbrl + sec_text 回歸：`94 passed, 5 skipped`
     - import 殘留掃描：
       - 無 `backtest_contracts/backtest_*_service` 舊路徑引用。
   - 計畫對齊檢查：
     - 與 standards 新增規約一致（mature capability subpackage grouping）。
     - `Lessons Review: no_update`（本批為規約落地實作；新規約已於 625 更新）。
627. P5 治理切片（backtest package 回流防線）：
   - 更新 `tests/test_fundamental_import_hygiene_guard.py`：
     - 新增禁止 legacy import 回流：
       - `src.agents.fundamental.domain.valuation.backtest_contracts`
       - `src.agents.fundamental.domain.valuation.backtest_io_service`
       - `src.agents.fundamental.domain.valuation.backtest_runtime_service`
       - `src.agents.fundamental.domain.valuation.backtest_drift_service`
       - `src.agents.fundamental.domain.valuation.backtest_report_service`
     - 新增禁止 legacy 平鋪檔案回流：
       - `domain/valuation/backtest_contracts.py`
       - `domain/valuation/backtest_io_service.py`
       - `domain/valuation/backtest_runtime_service.py`
       - `domain/valuation/backtest_drift_service.py`
       - `domain/valuation/backtest_report_service.py`
   - 驗證：
     - `ruff check` 通過（guard + backtest package）
     - `pytest -q` 通過：`test_fundamental_import_hygiene_guard.py` + `test_fundamental_backtest_runner.py`，合計 `7 passed`
   - `Lessons Review: no_update`（屬既有規約落地，無新增反模式）。
628. P5 Hardening 切片（SEC XBRL parser empty-facts fallback）：
   - 問題背景：
     - 真實流程中 `GOOG` `2023 FY` filing 可成功抓取（`0001652044-24-000022`），但 `xb.facts.to_dataframe()` 回傳空表，導致被誤判為「yearly report not found」。
   - 實作內容（infrastructure owner 保持單一職責）：
     - 更新 `infrastructure/sec_xbrl/extractor.py`：
       - 將 primary dataframe 解析改為 `resolve` 流程：先驗證 schema + row count，再在同一 filing 內做 forced instance fallback。
       - 新增 fallback helpers：
         - `_resolve_xbrl_facts_dataframe(...)`
         - `_build_dataframe_from_filing_attachments(...)`
         - `_select_instance_candidates(...)`
         - linkbase 收集/套用 helpers
       - schema 驗證強化：空列 (`row_count == 0`) 視為 invalid，避免空表靜默流入後續。
       - 新增可觀測事件：
         - `fundamental_xbrl_instance_fallback_started`
         - `fundamental_xbrl_instance_fallback_succeeded`
         - `fundamental_xbrl_instance_fallback_no_data_files`
         - `fundamental_xbrl_instance_fallback_no_candidates`
         - `fundamental_xbrl_instance_candidate_failed`
         - `fundamental_xbrl_instance_candidate_invalid`
   - 驗證結果：
     - `ruff check finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/extractor.py` 通過
     - `pytest -q finance-agent-core/tests/test_sec_xbrl_total_debt_policy.py` 通過（`7 passed`）
   - 計畫對齊檢查：
     - 結果：與 blueprint `infrastructure/sec_xbrl` 能力邊界一致（adapter robustness 在 infrastructure 層收斂，不把 parser 退化策略外溢到 domain/application）。
     - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「External Parser Empty Facts」反模式與 guardrail（先同 filing forced instance fallback，再考慮跨年份 fallback）。`
629. P5 Hardening 切片（SEC HTTP timeout runtime config 收斂）：
   - 問題背景：
     - 真實流程中 `GOOG 2023` filing URL 可命中，但多次出現 `ReadTimeout`，導致 `fundamental_xbrl_year_failed` 後降級年份。
   - 實作內容（infrastructure config owner）：
     - 更新 `infrastructure/sec_xbrl/sec_identity_service.py`：
       - `ensure_sec_identity()` 擴充為一次性初始化：
         1) `configure_http(timeout=...)`
         2) `set_identity(...)`
       - 新增 `SEC_HTTP_TIMEOUT_SECONDS` env（default `45.0`，下限 `5.0`）作為 external SDK timeout 配置入口。
       - 以單一 lock + flags 保證初始化只執行一次，避免重覆設定與分散呼叫。
   - 測試與驗證：
     - 新增 `tests/test_sec_xbrl_sec_identity_service.py`：
       - 驗證 timeout + identity 只初始化一次。
       - 驗證 env 低於下限會 clamp 至 `5.0`。
     - `ruff check` 通過：
       - `src/agents/fundamental/infrastructure/sec_xbrl/sec_identity_service.py`
       - `tests/test_sec_xbrl_sec_identity_service.py`
     - `pytest -q` 通過：
       - `tests/test_sec_xbrl_sec_identity_service.py`（`2 passed`）
       - `tests/test_sec_xbrl_filing_fetcher.py`（`2 passed`）
   - 計畫對齊檢查：
     - 結果：與 blueprint/standards 一致（external runtime config 收斂於 infrastructure owner，避免散落與過度設計）。
     - 偏離：無
   - `Lessons Review: updated`
   - `更新文件：`
     - `docs/standards/refactor_lessons_and_cross_agent_playbook.md`
   - `更新重點：新增「External SDK Large-Payload Timeout」反模式與集中 runtime config 規約。`

In Progress:

1. P5 維持性監控：以 import hygiene guard + regression tests 防止 legacy import 回流（持續性工作，非架構阻塞）。

Not Started:

1. 無阻塞性程式碼重構切片（核心架構已完成收斂）。
2. 無阻塞性治理切片（目前無新增待辦，按需補充）。

## 6. 下一步（Next Actions）

1. 執行 P3/P4 後續拆分：
   - P3/P4 核心拆分已完成，維持現有 thin orchestration 結構並防止回流。
2. 執行 P5 清理增量：
   - 零相容層目標已達到可運行收斂狀態；後續以 guard 與回歸測試維持。
3. 剩餘切片估算（接近 blueprint 目標架構）：
   - 約 `0` 個阻塞或既定治理切片：
     - 程式碼主線與文檔已收斂
     - 後續僅保留按需維持性監控（guard/回歸）
4. 持續補回歸測試，覆蓋 `sec_xbrl model -> canonical json -> valuation input` 路徑並回填本文件。

## 7. 風險與控制

1. 風險：命名改動造成測試 patch 路徑失效。
   控制：先批次改 call sites 與測試，再刪 alias；不長期保留雙命名。
2. 風險：契約調整引發隱性行為變更。
   控制：先做命名修正，再分開提交契約收斂。
3. 風險：大檔拆解時功能漂移。
   控制：先補關鍵 golden/smoke tests，再拆檔。
