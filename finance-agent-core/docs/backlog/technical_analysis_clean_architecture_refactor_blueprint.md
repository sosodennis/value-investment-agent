# Technical Analysis Clean Architecture Refactor Blueprint

Date: 2026-03-02
Scope: `finance-agent-core/src/agents/technical`
Status: In Progress (Focused hardening P0-P2)
Policy baseline:
1. `finance-agent-core/docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
2. `finance-agent-core/docs/standards/refactor_lessons_and_cross_agent_playbook.md`

Status update (2026-03-02):
1. P1 started and implemented:
   - technical artifact repository port moved to `application/ports.py`
   - concrete repository moved to `infrastructure/artifacts/technical_artifact_repository.py`
   - runtime composition moved to `src/agents/technical/wiring.py`
   - `workflow/nodes/technical_analysis/nodes.py` switched to wiring-owned runner
   - removed `technical/data/ports.py` and `technical/data/mappers.py`.
2. P2 started and implemented:
   - `run_data_fetch`, `run_fracdiff_compute`, `run_semantic_translate` moved into `application/use_cases/*`
   - `application/orchestrator.py` reduced to thin delegation to use-case owners
   - use-case runtime capability requirements defined via `Protocol` contracts.
3. Standards/Lessons review for P2: `no_update`
   - reason: changes are direct application of existing guardrails (`thin orchestrator`, `use-case ownership`, `application depends on ports/contracts`) and did not reveal a new cross-agent anti-pattern class.
4. P3 started and implemented:
   - moved fracdiff/statistics/indicator deterministic owners from `data/tools/*` to `domain/fracdiff/*`
   - moved fracdiff serialization owner from application helper into `domain/fracdiff/serialization_service.py`
   - migrated call sites/tests to `domain/fracdiff` imports and removed legacy files:
     - `technical/data/tools/fracdiff.py`
     - `technical/data/tools/indicators.py`
     - `technical/data/tools/stats.py`.
5. Standards/Lessons review for P3: `no_update`
   - reason: refactor followed existing rules (`deterministic owner in domain`, `remove legacy compatibility`, `atomic call-site migration`) without surfacing a new anti-pattern category.
6. P4 started and implemented:
   - split backtest capability into `domain/backtest/*`:
     - `contracts.py`
     - `strategy_registry.py`
     - `engine_service.py`
     - `walk_forward_service.py`
   - moved narrative formatting (`format_backtest_for_llm`, `format_wfa_for_llm`) into `application/semantic_context_formatter_service.py`
   - removed legacy backtest owner modules:
     - `technical/data/tools/backtester.py`
     - `technical/data/tools/strategies.py`.
7. Standards/Lessons review for P4: `no_update`
   - reason: refactor is direct application of existing rules (`quant engine vs narrative separation`, `capability subpackage grouping`, `no compatibility residue`) and did not introduce a new cross-agent anti-pattern class.
8. P5 started and implemented:
   - moved market data adapters to `infrastructure/market_data/*`:
     - `yahoo_ohlcv_provider.py`
     - `yahoo_risk_free_rate_provider.py`
   - moved LLM interpretation adapter to `infrastructure/llm/technical_interpretation_provider.py`
   - switched `src/agents/technical/wiring.py` imports to infrastructure owners
   - removed legacy runtime files:
     - `technical/data/tools/ohlcv.py`
     - `technical/data/tools/market.py`
     - `technical/data/tools/semantic_layer.py`
     - `technical/data/tools/utils.py`
     - `technical/data/tools/__init__.py`
     - `technical/data/__init__.py`.
9. Standards/Lessons review for P5: `no_update`
   - reason: refactor is covered by existing guardrails (`infrastructure adapter ownership`, `remove legacy compatibility residue`, `no mixed utility bucket`) and did not expose a new anti-pattern class.
10. P6 started and implemented:
   - consolidated semantic signal contracts/state/policy from generic domain root modules into `domain/signal_policy/*`:
     - `contracts.py`
     - `policy_service.py`
     - `state_service.py`
   - migrated application/interface/tests call sites to `domain/signal_policy` imports
   - removed legacy generic domain-root modules:
     - `technical/domain/models.py`
     - `technical/domain/services.py`
     - `technical/domain/policies.py`.
11. Standards/Lessons review for P6: `no_update`
   - reason: refactor directly applies existing guardrails (`no generic domain-root modules`, `capability package ownership`, `atomic call-site migration`) without introducing a new anti-pattern category.
12. P7 started and implemented (hardening):
   - added `tests/test_technical_import_hygiene_guard.py` to block legacy import/file regressions:
     - ban `src.agents.technical.data*` imports
     - ban `src.agents.technical.domain.models/services/policies*` imports
     - assert removed legacy module files remain absent.
13. Standards/Lessons review for P7: `no_update`
   - reason: this is direct execution of existing guardrails (`legacy import hygiene guard`) and does not require a new standard rule.
14. P8 started and implemented:
   - decomposed `application/semantic_service.py` into semantic owner services:
     - `application/semantic_pipeline_contracts.py`
     - `application/semantic_policy_input_service.py`
     - `application/semantic_backtest_context_service.py`
     - `application/semantic_finalize_service.py`
     - `application/semantic_pipeline_service.py`
   - migrated all call sites (`run_semantic_translate_use_case`, `report_service`, tests) to new owners
   - removed legacy monolith:
     - `application/semantic_service.py`
   - hardened import/file guard to block semantic monolith regression:
     - `tests/test_technical_import_hygiene_guard.py` bans `src.agents.technical.application.semantic_service*` and file reintroduction.
15. Standards/Lessons review for P8: `no_update`
   - reason: decomposition is already covered by existing guardrails (`run_* context/execution/completion separation`, `avoid mixed helper sinks`, `owner-module split`) and does not introduce a new anti-pattern class.
16. P9 started and implemented:
   - introduced typed runtime ports in `application/ports.py`:
     - `ITechnicalMarketDataProvider`
     - `ITechnicalInterpretationProvider`
     - `ITechnicalBacktestRuntime`
   - refactored `factory/orchestrator/use_cases/semantic_pipeline` to depend on typed runtime ports instead of function-level dependency lists
   - added concrete runtime owners:
     - `application/backtest_runtime_service.py`
     - `infrastructure/market_data/yahoo_market_data_provider.py`
     - `infrastructure/llm/TechnicalInterpretationProvider` (class in `technical_interpretation_provider.py`)
   - updated error-handling test patch path to provider owner (`YahooMarketDataProvider.fetch_daily_ohlcv`).
17. Standards/Lessons review for P9: `updated`
   - update: added cross-agent guideline rule + checklist entry for runtime dependency sprawl control:
     - avoid long `*_fn` callable bundles in workflow runners/orchestrators
     - converge runtime capabilities into typed ports injected from composition root.
18. P10 started and implemented:
   - introduced typed fracdiff runtime port in `application/ports.py`:
     - `ITechnicalFracdiffRuntime`
   - added fracdiff runtime owner services:
     - `application/fracdiff_runtime_contracts.py`
     - `application/fracdiff_runtime_service.py`
   - refactored `run_fracdiff_compute_use_case` to consume `fracdiff_runtime.compute(...)` instead of 7 function-level parameters
   - refactored `orchestrator/factory/wiring` to inject fracdiff runtime as a typed capability
   - updated error-handling test patch path to runtime owner (`TechnicalFracdiffRuntimeService.compute`).
19. Standards/Lessons review for P10: `no_update`
   - reason: refactor is a direct application of the new runtime typed-port guardrail added in P9 and did not reveal a new anti-pattern category.
20. P11 started and implemented:
   - reused existing `ITechnicalFracdiffRuntime` to absorb semantic-backtest indicator preparation (`stat_strength`/`bollinger`/`obv`) via `build_backtest_inputs(...)`
   - refactored semantic path (`semantic_backtest_context_service`, `semantic_pipeline_service`, `run_semantic_translate_use_case`, `orchestrator`, `factory`) to remove remaining indicator callable-parameter bundle
   - kept implementation pragmatic by extending existing fracdiff runtime owner instead of adding a new abstraction layer.
21. Standards/Lessons review for P11: `updated`
   - update: added explicit anti-overdesign guideline/checklist entries:
     - add ports/services only when they remove real complexity
     - verify refactors improve readability/maintainability without unnecessary abstraction layers.
22. P12 started and implemented:
   - extracted semantic-translate context resolution into:
     - `application/semantic_translate_context_service.py`
   - extracted semantic-translate success completion shaping into:
     - `application/semantic_translate_completion_service.py`
   - reduced `run_semantic_translate_use_case` to thin node control-flow (context resolve -> pipeline -> report -> completion/error routing).
23. Standards/Lessons review for P12: `no_update`
   - reason: this refactor directly applies existing use-case guardrails (`context loading`, `execution`, `completion shaping`) without introducing a new anti-pattern class.
24. P13 started and implemented:
   - replaced `object`-typed backtest runtime boundaries with minimal typed contracts:
     - domain backtest contracts now expose `BacktestResults` and `WalkForwardResult`
     - application ports now use `ITechnicalBacktester` / `ITechnicalWfaOptimizer` handles
   - updated `backtest_runtime_service` and semantic formatter signatures to use typed backtest contracts
   - maintained pragmatic scope: no extra layer added, only boundary type tightening for maintainability and robustness.
25. Standards/Lessons review for P13: `updated`
   - update: added explicit rule/checklist guardrail to avoid `object`-typed runtime boundaries when minimal typed contracts are available.
26. P14 started and implemented (hardening):
   - added regression guard in `tests/test_technical_import_hygiene_guard.py`:
     - enforce `ITechnicalBacktestRuntime` has no `object`-typed parameter/return annotations
   - expanded targeted regression batch to include:
     - technical core tests
     - technical interface/preview tests
     - workflow command adapter + kernel workflow contract tests.
27. Standards/Lessons review for P14: `no_update`
   - reason: hardening is direct enforcement of existing standards (runtime typed-port boundaries + import hygiene) without introducing a new anti-pattern category.
28. Post-P14 compliance review and implemented convergence fixes:
   - tightened technical artifact port boundaries from `object` to explicit `str | None` (artifact ids) and `JSONObject` (canonical payload input)
   - moved interpretation prompt spec owner from `domain/prompt_builder.py` to `interface/interpretation_prompt_spec.py` to keep prompt concerns out of domain
   - verified no legacy source modules remain under `technical/data` (only transient bytecode cache directories may exist locally and are non-runtime, ignored artifacts).
29. Standards/Lessons review for post-P14 compliance fix: `updated`
   - update: standards were consolidated to reduce duplication; prompt ownership and typed-boundary guidance are now captured in one canonical cross-agent standard document with a shorter operational playbook.
30. Naming/ownership convergence slice implemented:
   - moved preview projection owner from `application/view_models.py` to `interface/preview_projection_service.py`
   - updated technical/fundamental interface mappers and preview tests to import projection owners from interface layer
   - removed legacy `application/view_models.py` modules in technical/fundamental (no compatibility alias kept).
31. Standards/Lessons review for preview projection convergence: `updated`
   - update: cross-agent standard now explicitly requires preview projection ownership in `interface` and discourages generic `view_models.py` module naming in mature agents.
32. P15 started and implemented (2026-03-03, hardening P0):
   - fixed async blocking tail in `application/semantic_backtest_context_service.py`:
     - `run_backtest(...)` and `run_wfa(...)` are now offloaded with `asyncio.to_thread(...)`
     - added bounded compute concurrency via module-owned semaphore guard
   - preserved degraded fallback/error contract behavior.
33. Validation + Standards/Lessons review for P15: `no_update`
   - validation:
     - `ruff check` (changed technical/fundamental files + new tests) passed
     - targeted tests passed, including new
       `tests/test_technical_semantic_backtest_context_service.py`
   - reason: this slice is direct application of existing standards (`async boundary offload`, `heavy compute gate`) without introducing a new anti-pattern class.
34. P16 started and implemented (2026-03-04, P1/P2 convergence hardening):
   - semantic translate degraded state is now externally visible in workflow state (not logs-only):
     - `technical_analysis.is_degraded`
     - `technical_analysis.degraded_reasons`
   - `run_semantic_translate_use_case.py` now computes degraded reasons from pipeline quality and artifact fallback, then writes them via completion/update owner.
   - `semantic_translate_completion_service.py` / `state_updates.py` updated so success updates carry quality flags for UI/downstream consumers.
35. P17 started and implemented (2026-03-04, P3 boundary ownership convergence):
   - moved backtest/WFA narrative formatter owner from application to interface:
     - new owner: `interface/semantic_context_formatter_service.py`
     - removed legacy owner: `application/semantic_context_formatter_service.py`
   - updated runtime wiring/imports to interface owner and added hygiene guard to block legacy module reintroduction.
36. Validation + Standards/Lessons review for P16/P17: `no_update`
   - validation:
     - `ruff check` passed on changed technical modules/tests
     - `pytest finance-agent-core/tests/test_technical_* finance-agent-core/tests/test_error_handling_technical.py -q` passed (`33 passed`)
   - plan alignment: no deviation from this blueprint; this batch is direct convergence on existing standards (`degraded observability`, `interface ownership for narrative formatting`, `no compatibility residue`).

## 1. Review 結論（先回答你的判斷）

你的判斷是正確的，`technical` 現況確實存在「package 分塊混亂、命名不清、內聚性低」問題，且與 fundamental 重構前的反模式高度相似。

核心證據（現況掃描）：

1. 模組總量偏大且重心集中於混責任檔案：
   - `technical` 總 LOC：約 `3558`
   - `data/tools/backtester.py`：`536 LOC`
   - `application/orchestrator.py`：`403 LOC`
   - `application/semantic_service.py`：`329 LOC`
2. `application` 直接依賴 `data` concrete（跨層滲漏）：
   - `application/factory.py` 直接 import `data.tools.*` 與 `technical_artifact_port` singleton。
3. `data` package 同時承載多種 owner：
   - 外部 I/O（yfinance、artifact manager）
   - deterministic quant 引擎（fracdiff/backtester/strategies）
   - LLM prompt/interpretation adapter（`semantic_layer.py`）
4. 命名與責任不一致：
   - concrete class `TechnicalArtifactPort`（實際是 repository adapter）
   - generic root module（`domain/models.py`, `domain/services.py`）在成熟能力中語義過泛。
5. singleton wiring 放在 runtime package 內（`technical_artifact_port`、`technical_workflow_runner` 模組級實例），使測試與替換依賴困難。

## 2. 目標與非目標

目標：

1. 收斂到 `domain/application/interface/infrastructure` 清晰分層。
2. 大切片重構（每批次覆蓋完整能力片段），加速收斂。
3. 不保留 legacy compatibility alias/shim。
4. 以可維護性、可讀性、壯健性為主，避免過度設計。

非目標：

1. 不更改 technical 指標或策略的業務含義（只做 owner 收斂與邊界重整）。
2. 不在此藍圖階段引入新交易策略或新數學模型。

## 3. 目標架構（Technical）

```text
src/agents/technical/
  domain/
    fracdiff/
      contracts.py
      fracdiff_service.py
      indicator_service.py
      stats_service.py
      serialization_service.py
    signal_policy/
      contracts.py
      policy_service.py
      state_service.py
    backtest/
      contracts.py
      strategy_registry.py
      engine_service.py
      walk_forward_service.py
  application/
    ports.py
    factory.py
    orchestrator.py
    backtest_runtime_service.py
    fracdiff_runtime_contracts.py
    fracdiff_runtime_service.py
    report_service.py
    state_readers.py
    state_updates.py
    semantic_pipeline_contracts.py
    semantic_policy_input_service.py
    semantic_translate_context_service.py
    semantic_translate_completion_service.py
    semantic_backtest_context_service.py
    semantic_finalize_service.py
    semantic_pipeline_service.py
    use_cases/
      data_fetch_use_case.py
      fracdiff_compute_use_case.py
      semantic_translate_use_case.py
  wiring.py
  interface/
    semantic_context_formatter_service.py
    contracts.py
    serializers.py
    mappers.py
    formatters.py
    prompt_renderers.py
    types.py
  infrastructure/
    artifacts/
      technical_artifact_repository.py
    market_data/
      yahoo_market_data_provider.py
      yahoo_ohlcv_provider.py
      yahoo_risk_free_rate_provider.py
    llm/
      technical_interpretation_provider.py
```

### 3.1 Layer 職責與邊界

1. `domain`
   - 負責 deterministic 規則與數學引擎（fracdiff/backtest/signal policy）。
   - 不得做網路 I/O、artifact 存取、LLM 呼叫。
2. `application`
   - 負責 use-case 編排與 workflow 狀態更新。
   - 僅依賴 `ports`，不得 import infrastructure concrete。
3. `interface`
   - 負責契約、序列化、preview formatting、prompt rendering。
   - 不承載業務決策、不做 I/O。
4. `infrastructure`
   - 負責 yfinance/LLM/artifact manager adapter。
   - 不做 workflow control，不做 domain policy 決策。

## 4. 主要問題到重構對位

1. `data/tools/backtester.py` 混合：
   - 策略回測 engine
   - walk-forward optimizer
   - LLM narrative formatter
   - 對位：拆成 `domain/backtest/*`（數值）+ `application/semantic_backtest_context_service.py`（組 context）+ `interface/semantic_context_formatter_service.py`（文字格式化）。
2. `application/orchestrator.py` 過胖：
   - 同時做 state 讀取、計算、artifact IO、錯誤路由與 payload 組裝。
   - 對位：拆成 `use_cases/*`，orchestrator 保留薄 delegation。
3. `data/ports.py` concrete + singleton：
   - `TechnicalArtifactPort` 與 `technical_artifact_port` 模組級實例。
   - 對位：改為 `application/ports/ArtifactRepositoryPort` + `infrastructure/artifacts/TechnicalArtifactRepository`，wiring 集中於 `src/agents/technical/wiring.py`。
4. `data/tools/semantic_layer.py` 直接 `get_llm()`：
   - 對位：移到 `infrastructure/llm/technical_interpretation_provider.py`，由 `InterpretationPort` 注入。
5. generic domain root modules：
   - `domain/models.py`, `domain/services.py`。
   - 對位：收斂為 capability package + semantic owner module。

## 5. 執行切片（大切片、無 compatibility）

## P1: Layer 收斂與 Composition Root（大切片）

範圍：

1. 建立 `application/ports/*`。
2. 新增 `infrastructure/artifacts/technical_artifact_repository.py`。
3. 新增 `src/agents/technical/wiring.py`，承接 concrete 組裝。
4. 移除 `data/ports.py` 與 module-level singleton 用法。

驗收：

1. `application/*` 不再 import `technical.data.*`。
2. workflow nodes 只依賴 application entrypoint（非 concrete singleton）。

## P2: Use-Case 拆分（大切片）

範圍：

1. `run_data_fetch`, `run_fracdiff_compute`, `run_semantic_translate` 拆到 `application/use_cases/*`。
2. `state_readers.py` / `state_updates.py` 保持 owner 清晰，並由 use-case 統一路由更新。
3. `orchestrator.py` 變成薄 delegator。

驗收：

1. `application/orchestrator.py` 顯著降 LOC（目標 < 160）。
2. 每個 use-case 單檔僅負責單一步驟流程。

## P3: Quant Engine 能力化（大切片）

範圍：

1. `data/tools/fracdiff.py`, `indicators.py`, `stats.py`, `mappers.py` 收斂到：
   - `domain/fracdiff/contracts.py`
   - `domain/fracdiff/fracdiff_service.py`
   - `domain/fracdiff/indicator_service.py`
   - `domain/fracdiff/stats_service.py`
   - `domain/fracdiff/serialization_service.py`
2. `domain/models.py` 的 fracdiff snapshots 同批遷移至 `domain/fracdiff/contracts.py`。

驗收：

1. `data/tools` 不再承載 deterministic 指標/序列化 owner。
2. call sites 全部原子遷移，零 shim。

## P4: Backtest 能力化與語義解耦（大切片）

範圍：

1. 拆 `backtester.py` 為：
   - `domain/backtest/contracts.py`
   - `domain/backtest/engine_service.py`
   - `domain/backtest/walk_forward_service.py`
   - `domain/backtest/strategy_registry.py`（從 `strategies.py` 收斂）
2. `format_backtest_for_llm`、`format_wfa_for_llm` 移出 domain engine：
   - 放 `interface/semantic_context_formatter_service.py`（只做展示字串）。

驗收：

1. domain backtest 模組不再產生 LLM narrative 文案。
2. `backtester.py` 舊路徑完全移除。

## P5: Infrastructure 收斂 + 刪除 legacy `data/`

範圍：

1. `semantic_layer.py` -> `infrastructure/llm/technical_interpretation_provider.py`。
2. `ohlcv.py`, `market.py` -> `infrastructure/market_data/*provider.py`。
3. 刪除 `src/agents/technical/data/` package（不保留 compatibility）。

驗收：

1. `src/agents/technical/data` 目錄移除。
2. `application/domain/interface` 不含 `technical.data` import。

## 6. 測試與品質閘道

每個切片固定執行：

1. `ruff check`（technical + 受影響測試）
2. `pytest` targeted：
   - `finance-agent-core/tests/test_technical_application_use_cases.py`
   - `finance-agent-core/tests/test_technical_analysis.py`
   - `finance-agent-core/tests/test_error_handling_technical.py`
   - `finance-agent-core/tests/test_technical_interface_serializers.py`
   - `finance-agent-core/tests/test_technical_preview_layers.py`
3. import hygiene：
   - 禁止 `application/*` import `technical.data.*`
   - 禁止 `domain/*` import `application/interface/infrastructure`

## 7. 風險與控制

1. 風險：大切片搬遷造成 call-site 遺漏。
   - 控制：每切片完成後跑全量 technical targeted tests + `rg` legacy import 掃描。
2. 風險：為切片速度引入過度抽象。
   - 控制：只抽有明確 owner 的模組，不為未來假設建立額外抽象層。
3. 風險：語義字串與控制流耦合回流。
   - 控制：control flow 只用 typed fields，文案僅用於展示。

## 8. 完成定義（Definition of Done）

1. technical 收斂到 `domain/application/interface/infrastructure`，無 `data` legacy package。
2. concrete `*Port` 命名全部清除（repository/provider/service 命名語義一致）。
3. application 僅依賴 ports，不依賴 concrete adapters。
4. orchestrator 為薄層，use-case owner 清晰。
5. 回測/fracdiff owner 模組可獨立測試、可定位責任邊界。
6. 測試與 lint 全綠，且無 legacy compatibility shim。

## 9. 2026-03-03 Focused Hardening Plan（本輪）

目標：在既有完成狀態上做高價值硬化，不新增不必要抽象。

### T-P0：修復 async 阻塞尾巴（backtest/WFA）

背景：
1. technical 主流程多數 async 邊界已完成，但 semantic backtest context 內仍有同步重計算調用。

實作切片：
1. 將 backtest 與 WFA 執行從 event loop 邊界 offload（`asyncio.to_thread(...)` 或等價 executor）。
2. 維持既有 degraded fallback 行為與 error contract。
3. 加入 bounded concurrency（避免同時過量 CPU 任務堆疊）。

驗收：
1. async use-case 內無直接同步重計算阻塞點。
2. 功能輸出不變，延遲抖動下降。
3. 相關測試（成功/降級）全綠。

### T-P1：精簡過細 Service 顆粒（避免過度設計）

策略：
1. 合併薄透傳 runtime/service owner（不影響邊界清晰度前提下）。
2. 保留有獨立語義的 capability owner（fracdiff/backtest/signal policy）。

實作切片：
1. 盤點 `application/*runtime*` 與 `semantic_*` 的薄 wrapper。
2. 只對「無獨立責任、僅透傳」做收斂；避免建立新的抽象層。
3. 補齊 import hygiene 測試，防止碎片回流。

驗收：
1. call chain 更短、檔案責任更明確。
2. 無新增 generic module 或抽象層膨脹。

### T-P2：WFA 性能基線與回歸閘道

實作切片：
1. 建立固定資料窗口（train/test window）與固定輸入的 WFA 基線。
2. 記錄基線指標（總耗時、每階段耗時、樣本數）。
3. 加入性能回歸閾值 gate（先以相對退化比率為主）。

驗收：
1. WFA 性能可重現、可比較。
2. 後續重構若性能退化超閾值可被快速攔截。
