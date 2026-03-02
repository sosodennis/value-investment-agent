# News Research Clean Architecture Refactor Blueprint

Date: 2026-03-02
Scope: `finance-agent-core/src/agents/news`
Status: P1-P7 completed (architecture convergence) + P8 hardening completed
Policy baseline:
1. `finance-agent-core/docs/standards/cross_agent_class_naming_and_layer_responsibility_guideline.md`
2. `finance-agent-core/docs/standards/refactor_lessons_and_cross_agent_playbook.md`
3. `finance-agent-core/docs/backlog/fundamental_valuation_clean_architecture_refactor_blueprint.md`
4. `finance-agent-core/docs/backlog/technical_analysis_clean_architecture_refactor_blueprint.md`

Status update (2026-03-02):
1. P1 started and implemented:
   - introduced `INewsArtifactRepository` in `application/ports.py`
   - moved concrete artifact owner to `infrastructure/artifacts/news_artifact_repository.py`
   - moved workflow composition to `src/agents/news/wiring.py`
   - switched `workflow/nodes/financial_news_research/nodes.py` to wiring-owned runner
   - moved news entity projection owner to `domain/news_item_projection_service.py`
   - removed legacy runtime files:
     - `src/agents/news/data/ports.py`
     - `src/agents/news/data/mappers.py`
2. Validation (P1):
   - `ruff check` passed for changed news/workflow/tests paths
   - targeted news regression batch passed (`35 passed`)
3. Standards/Lessons review for P1: `no_update`
   - reason: this slice is direct execution of existing guardrails (`application depends on ports`, `repository naming/ownership`, `wiring composition root`, `remove compatibility residue`) and did not introduce a new anti-pattern class.
4. P2 started and implemented:
   - decomposed node execution logic into dedicated use-case owners:
     - `application/use_cases/run_search_node_use_case.py`
     - `application/use_cases/run_selector_node_use_case.py`
     - `application/use_cases/run_fetch_node_use_case.py`
     - `application/use_cases/run_analyst_node_use_case.py`
     - `application/use_cases/run_aggregator_node_use_case.py`
   - reduced `application/orchestrator.py` to thin delegation over use-case owners
   - tightened runtime boundary typing in `application`:
     - `state_readers` artifact ids now return `str | None`
     - `application/ports.py` runtime protocols removed avoidable `object` usage on key boundaries
5. Validation (P2):
   - `ruff check` passed for changed news/workflow/tests paths
   - targeted news regression batch passed (`35 passed`)
6. Standards/Lessons review for P2: `no_update`
   - reason: this slice applies existing guardrails (`thin orchestrator`, `run_* use-case ownership`, `runtime boundary type tightening`) and did not reveal a new anti-pattern class.
7. P3 started and implemented:
   - moved external adapters from `data/clients/*` to `infrastructure/*`:
     - `infrastructure/search/ddg_news_search_provider.py`
     - `infrastructure/content_fetch/trafilatura_content_fetch_provider.py`
     - `infrastructure/sentiment/finbert_sentiment_provider.py`
     - `infrastructure/source_reliability/source_reliability_service.py`
     - `infrastructure/ids/news_id_generator_service.py`
   - updated `src/agents/news/wiring.py` to consume infrastructure owners only
   - updated cross-agent FinBERT direction import path in fundamental infrastructure:
     - `fundamental/infrastructure/sec_xbrl/finbert_direction.py`
   - removed legacy data package runtime paths:
     - `src/agents/news/data/clients/*`
     - `src/agents/news/data/__init__.py`
8. Validation (P3):
   - `ruff check` passed for changed news/fundamental/workflow/tests paths
   - targeted regression batch passed (`57 passed`)
9. Standards/Lessons review for P3: `no_update`
   - reason: this slice is direct execution of existing guardrails (`infrastructure adapter ownership`, `remove legacy residue`, `composition via wiring`) and did not reveal a new anti-pattern class.
10. P4 started and implemented:
   - converged generic domain-root modules into capability packages:
     - `domain/aggregation/contracts.py`
     - `domain/aggregation/aggregation_service.py`
     - `domain/aggregation/summary_message_service.py`
     - `domain/search_strategy/contracts.py`
     - `domain/search_strategy/query_policy_service.py`
     - `domain/search_strategy/ranking_policy_service.py`
   - moved prompt spec ownership from domain to interface:
     - `interface/prompt_specs.py`
   - migrated call sites (application/interface/infrastructure/tests) to new owners
   - removed legacy domain-root modules:
     - `domain/models.py`
     - `domain/services.py`
     - `domain/policies.py`
     - `domain/prompt_builder.py`
11. Validation (P4):
   - `ruff check` passed for changed news/fundamental/workflow/tests paths
   - targeted regression batch passed (`57 passed`)
12. Standards/Lessons review for P4: `no_update`
   - reason: this slice directly applies existing guardrails (`no generic domain-root modules`, `prompt spec ownership in interface`, `no compatibility residue`) and did not introduce a new anti-pattern class.
13. P5 started and implemented:
   - moved preview projection owner from `application/view_models.py` to:
     - `interface/preview_projection_service.py`
   - migrated interface/test call sites to interface projection owner:
     - `interface/mappers.py`
     - `tests/test_news_preview_layers.py`
   - removed legacy projection module:
     - `application/view_models.py`
14. Validation (P5):
   - `ruff check` passed for changed news/fundamental/workflow/tests paths
   - targeted regression batch passed (`57 passed`)
15. Standards/Lessons review for P5: `no_update`
   - reason: this slice is direct execution of an existing cross-agent rule (`preview projection belongs to interface`) and did not reveal a new anti-pattern class.
16. P6 started and implemented:
   - tightened remaining avoidable runtime boundary types in application owners:
     - `analysis_service.build_analysis_chains(...)` prompt parameters now use explicit prompt type
     - `fetch_service.parse_published_at(...)` narrowed to `str | None`
     - `state_readers` helper simplified to immediate typed normalization path
   - kept workflow-state entry boundary as `Mapping[str, object]` (LangGraph heterogeneous state contract) and prevented propagation into deeper runtime ports/contracts.
17. Validation (P6):
   - `ruff check` passed for changed news/fundamental/workflow/tests paths
   - targeted regression batch passed (`57 passed`)
18. Standards/Lessons review for P6: `updated`
   - update: clarified cross-agent standard that `Mapping[str, object]` is acceptable only at workflow-state entry boundary; typed normalization must happen immediately in `state_readers` to avoid over-design and boundary leakage.
19. P7 started and implemented:
   - added import/file hygiene guard:
     - `tests/test_news_import_hygiene_guard.py`
   - enforced no regression to removed legacy paths:
     - ban `src.agents.news.data*` imports
     - ban `src.agents.news.domain.models/services/policies/prompt_builder*` imports
     - ban `src.agents.news.application.view_models*` imports
     - assert removed legacy module files remain absent
   - enforced typed artifact repository boundary:
     - guard verifies `INewsArtifactRepository` has no `object`-typed parameter/return annotations.
20. Validation (P7):
   - `ruff check` passed for changed news/fundamental/workflow/tests paths
   - targeted regression batch passed (`61 passed`)
21. Standards/Lessons review for P7: `no_update`
   - reason: this slice is direct enforcement of existing guardrails (`import hygiene`, `legacy file removal`, `typed boundary guard`) and did not reveal a new anti-pattern class.
22. Hardening slice started and implemented (2026-03-02):
   - fixed async LLM blocking in `application/analysis_service.py`:
     - prefer `ainvoke` when available; fallback to `asyncio.to_thread(chain.invoke, ...)`
     - kept per-item sequential execution to avoid concurrency/rate-limit spikes.
   - fixed aggregator false-success path:
     - `run_aggregator_node_use_case` now terminal-errors when `load_news_items_data(...)` fails.
   - fixed fetch all-or-nothing degradation:
     - switched fetch gather to per-item exception handling (`return_exceptions=True`)
     - preserve successful article content while degrading failed items only.
   - fixed selector/analysis chain boundary typing drift:
     - split chain protocols in `application/ports.py` into `SelectorChainLike` and `StructuredChainLike`.
   - fixed missing-url ID collision risk:
     - `generate_news_id(...)` now hashes `url + title` canonical key.
   - fixed selector context-load observability drift:
     - `run_selector_node_use_case` now marks degraded and emits explicit error context when loading selector artifacts fails.
   - unified ticker source for aggregation:
     - `aggregator_ticker_from_state` now prefers `intent_extraction.resolved_ticker` and only falls back to `state["ticker"]`.
   - reduced baseline search latency:
     - tuned search concurrency/jitter (`MAX_CONCURRENT_REQUESTS=4`, `JITTER_SECONDS=(0.8, 1.8)`).
23. Validation (Hardening):
   - `ruff check` passed for changed news/debate/tests paths
   - targeted news regression batch passed (`23 passed`)
24. Standards/Lessons review for Hardening: `updated`
   - update: added cross-agent rule that async use-cases must not run blocking sync network/LLM calls on the event loop; use native async APIs or `asyncio.to_thread(...)`.
25. P8-A started and implemented (2026-03-02):
   - fixed artifact missing semantics in repository context loaders:
     - `load_search_context/load_fetch_context/load_news_items_data` now raise explicit `ArtifactNotFoundError` for missing artifact id/data instead of silently returning empty values.
   - fixed search false-progress path:
     - `run_search_node_use_case` now terminal-errors on search artifact save failure (no `goto=selector_node` with `search_artifact_id=None`).
   - fixed selector context/load save failure semantics:
     - `run_selector_node_use_case` now terminal-errors on context load failure and selection artifact save failure.
     - selector context-load failure no longer invokes LLM.
   - fixed fetch/analyst context-load false-success paths:
     - `run_fetch_node_use_case` now terminal-errors when fetch context cannot be loaded.
     - `run_analyst_node_use_case` now terminal-errors when news-items artifact cannot be loaded/parsed.
   - unified search state-update contract shape:
     - `build_search_node_no_ticker_update` and `build_search_node_empty_update` now include canonical `node_statuses` and `financial_news_research` status fields.
   - fixed aggregator status drift:
     - degraded aggregator completion now writes `status=degraded` and `node_statuses=degraded` (instead of `success/done`), with warning `error_logs`.
26. Validation (P8-A):
   - `ruff check` passed for changed news source/tests paths
   - targeted news regression batch passed (`35 passed`)
27. Standards/Lessons review for P8-A: `updated`
   - update: added cross-agent error-handling rule that artifact not-found/missing-id must be explicit failure semantics and must not be normalized to empty payloads at repository/read-boundary owners.
28. P8-B started and implemented (2026-03-02):
   - fixed selector async blocking risk (`F4`):
     - `run_selector_with_resilience(...)` is now async.
     - selector chain invocation now uses `ainvoke` when available, otherwise `asyncio.to_thread(chain.invoke, ...)`.
     - `run_selector_node_use_case` now awaits selector execution path.
   - fixed per-request HTTP client allocation in fetch provider (`F9`):
     - `trafilatura_content_fetch_provider` now reuses a shared `httpx.AsyncClient` for async fetch calls.
     - introduced explicit lifecycle helpers:
       - `get_shared_async_client()`
       - `close_shared_async_client()`
     - integrated shutdown cleanup in FastAPI lifespan (`api/server.py`) to close shared news fetch client.
   - added regression guards:
     - selector test verifies `ainvoke` is preferred when provided.
     - content-fetch test verifies shared client reuse and close/recreate behavior.
29. Validation (P8-B):
   - `ruff check` passed for changed news/server/tests paths
   - targeted news regression batch passed (`37 passed`)
30. Standards/Lessons review for P8-B: `updated`
   - update: added cross-agent runtime rule that high-frequency async HTTP adapters must reuse client/session objects and expose explicit shutdown close hooks; avoid per-request client construction in hot paths.
31. P8-C started and implemented (2026-03-02):
   - fixed fetch quality observability gap (`F2`) via typed provider result:
     - introduced `FetchContentResult` in application runtime boundary contracts.
     - `fetch_clean_text_async` now returns success/failure result with machine-readable `failure_code`, optional `http_status`, and failure reason.
   - updated fetch pipeline to consume typed results:
     - `run_fetch_node_use_case` now computes `fetch_attempted_count`, `fetch_success_count`, `fetch_fail_count`, `fetch_fail_reason_counts`, and `fetch_status_code_counts`.
     - fail_count > 0 now always marks degraded and emits summary in `error_logs`.
     - degraded summary now explicitly explains quality loss (`x/y failed`, reason and status distribution).
   - updated runtime wiring/dependency signatures (`orchestrator/factory/wiring`) to typed fetch result contract.
   - added/updated regression guards:
     - fetch use-case partial failure test now validates degraded summary presence.
32. Validation (P8-C):
   - `ruff check` passed for changed news/tests paths
   - targeted news regression batch passed (`37 passed`)
33. Standards/Lessons review for P8-C: `updated`
   - update: added cross-agent rule that external provider degraded outcomes must use typed failure payloads (reason/code/metadata), not bare `None`, so use-cases can compute deterministic degraded state and diagnostics.
34. P8-D started and implemented (2026-03-02):
   - removed import-time singleton runner side effect (`F8`):
     - `news.wiring` no longer builds `news_workflow_runner` at import time.
     - added lazy accessor `get_news_workflow_runner()` with cached build-on-first-use semantics.
   - updated node entrypoints to use lazy accessor:
     - `workflow/nodes/financial_news_research/nodes.py` now resolves runner per node call via `get_news_workflow_runner()`.
   - updated affected tests to align with lazy wiring path.
35. Validation (P8-D):
   - `ruff check` passed for changed news/workflow/tests paths
   - targeted news regression batch passed (`37 passed`)
36. Standards/Lessons review for P8-D: `no_update`
   - reason: this slice directly applies existing cross-agent hard rule (`no import-time bootstrap side effects`) and did not reveal a new anti-pattern class.

## 1. Review 結論

`news` 現況不符合目前 cross-agent refactor 目標，且與 FA/TA 重構前的反模式高度一致。你的判斷是正確的：目前存在分層邊界滲漏、命名/責任不一致、能力切分分散與 `object` 邊界過寬等問題，會直接影響可維護性、可讀性、與後續迭代穩定性。

## 2. 現況診斷（P0 Audit）

1. `application/orchestrator.py` 過大（700 LOC），同時承擔節點控制流、artifact I/O、LLM/FinBERT 路由、錯誤處理與輸出組裝。
2. `application` 直接依賴 `data` concrete：
   - `application/orchestrator.py` 直接 import `src.agents.news.data.ports.NewsArtifactPort`
   - `application/factory.py` 直接 import `src.agents.news.data.clients.*` 與 `news_artifact_port` singleton
3. `data/ports.py` 混責任：
   - concrete 類名使用 `*Port`（`NewsArtifactPort`）
   - repository I/O 與 domain projection 混放（`project_news_item_entities`）
   - module-level singleton（`news_artifact_port`）
4. generic domain-root modules 尚未收斂：
   - `domain/models.py`
   - `domain/services.py`
   - `domain/policies.py`
5. prompt owner 位置錯誤：
   - `domain/prompt_builder.py`（prompt spec 應在 `interface`）
6. preview projection owner 漂移：
   - `interface/mappers.py` 反向依賴 `application/view_models.py`
7. runtime/type boundary 過寬：
   - `application/ports.py`、`application/state_readers.py`、`data/ports.py` 多處 `object` 用於 artifact id/source/model type。
8. `news` 總 LOC 約 `3617`，重心集中於少數高耦合檔案（orchestrator、data clients、data ports）。

## 3. 目標架構（無 legacy compatibility）

```text
src/agents/news/
  domain/
    aggregation/
      contracts.py
      aggregation_service.py
      summary_message_service.py
    search_strategy/
      contracts.py
      query_policy_service.py
      ranking_policy_service.py
  application/
    ports.py
    state_readers.py
    state_updates.py
    factory.py
    orchestrator.py
    use_cases/
      run_search_node_use_case.py
      run_selector_node_use_case.py
      run_fetch_node_use_case.py
      run_analyst_node_use_case.py
      run_aggregator_node_use_case.py
    services/
      analysis_chain_service.py
      fetch_item_build_service.py
      selector_resilience_service.py
  interface/
    contracts.py
    types.py
    parsers.py
    serializers.py
    formatters.py
    mappers.py
    prompt_renderers.py
    prompt_specs.py
    preview_projection_service.py
  infrastructure/
    artifacts/
      news_artifact_repository.py
    search/
      ddg_news_search_provider.py
    content_fetch/
      trafilatura_content_fetch_provider.py
    sentiment/
      finbert_sentiment_provider.py
    source_reliability/
      source_reliability_service.py
    ids/
      news_id_generator_service.py
  wiring.py
```

## 4. 大切片執行計畫（加速收斂）

每個切片完成後，必做：
1. `ruff check`
2. news 目標測試批次
3. `Lessons Review Gate`: `updated | no_update` + reason

### P1: Composition Root + Artifact Repository 收斂（大切片）

目標：
1. 建立 `application` 依賴抽象 `INewsArtifactRepository`。
2. concrete artifact owner 移到 `infrastructure/artifacts/news_artifact_repository.py`。
3. 組裝改由 `src/agents/news/wiring.py` 管理，workflow nodes 不再依賴 `application/factory` singleton。

移除（無兼容）：
1. `src/agents/news/data/ports.py`
2. `src/agents/news/data/mappers.py`

驗收：
1. `application/*` 不再 import `src.agents.news.data.*`
2. workflow node 透過 wiring accessor 取得 runner
3. 既有 `news` tests 通過

### P2: Orchestrator 拆分為 use-case owners（大切片）

目標：
1. `run_search/run_selector/run_fetch/run_analyst/run_aggregator` 拆到 `application/use_cases/*`。
2. `application/orchestrator.py` 收斂為薄委派層，去除混合責任。
3. node 流程固定為：`context load -> execution -> completion/error update`。

移除（無兼容）：
1. monolithic node 實作留在 orchestrator 的舊路徑

驗收：
1. 單檔控制流顯著下降（每個 use-case owner 單責任）
2. 行為與現有節點輸出契約一致

### P3: External Adapters 全量遷移到 infrastructure（大切片）

目標：
1. `data/clients/search.py` -> `infrastructure/search/ddg_news_search_provider.py`
2. `data/clients/fetch.py` -> `infrastructure/content_fetch/trafilatura_content_fetch_provider.py`
3. `data/clients/finbert_service.py` -> `infrastructure/sentiment/finbert_sentiment_provider.py`
4. `data/clients/reliability.py` -> `infrastructure/source_reliability/source_reliability_service.py`
5. `data/clients/ids.py` -> `infrastructure/ids/news_id_generator_service.py`
6. `application/factory.py` 改用 typed ports/owners，不再 import `data.clients.*`

移除（無兼容）：
1. `src/agents/news/data/clients/*`
2. `src/agents/news/data/__init__.py`（若已無 runtime owner）

驗收：
1. `src.agents.news.data` 在 runtime import graph 不再被使用
2. all external calls 只在 infrastructure

### P4: Domain capability package 收斂 + Prompt owner 修正（大切片）

目標：
1. `domain/models.py` + `domain/services.py` -> `domain/aggregation/*`
2. `domain/policies.py` -> `domain/search_strategy/*`
3. `domain/prompt_builder.py` -> `interface/prompt_specs.py`

移除（無兼容）：
1. `domain/models.py`
2. `domain/services.py`
3. `domain/policies.py`
4. `domain/prompt_builder.py`

驗收：
1. `domain` 不再承載 prompt concerns
2. 不再有 generic domain-root owner modules

### P5: Interface preview projection 一致化（大切片）

目標：
1. `application/view_models.py` -> `interface/preview_projection_service.py`
2. `interface/mappers.py` 只依賴 interface owners
3. 更新 `test_news_preview_layers.py` 與相關 mapper tests

移除（無兼容）：
1. `application/view_models.py`

驗收：
1. 無 `application/view_models.py` 路徑殘留
2. preview 層次與 FA/TA 命名一致

### P6: Boundary 型別硬化（大切片）

目標：
1. 移除可避免的 `object` 邊界：
   - artifact id 收斂到 `str | None`
   - payload/input 收斂到 `JSONObject` 或對應 typed contracts
2. `state_readers` 維持 tolerant（optional state -> `None`），但輸出型別一致。
3. 修正 `application/ports.py` runtime protocols 的最小型別契約。

驗收：
1. `application/ports.py` 不存在可避免的 `object` 參數/回傳
2. 邊界錯誤仍走既有 error update contract

### P7: Final hardening（收斂切片）

目標：
1. hygiene guards：
   - ban `src.agents.news.data*`
   - ban `src.agents.news.domain.models/services/policies*`
   - ban `src.agents.news.application.view_models*`
2. 擴充 news regression tests，覆蓋 search/selector/fetch/analyst/aggregator 主要路徑。
3. 最終確認不保留 compatibility residue。

驗收：
1. import hygiene tests 通過
2. 目標路徑全部清除

## 5. 驗證基線（每批最少）

1. `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/news finance-agent-core/tests`
2. `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_news_application_use_cases.py finance-agent-core/tests/test_news_interface_boundaries.py finance-agent-core/tests/test_news_preview_layers.py finance-agent-core/tests/test_error_handling_news.py finance-agent-core/tests/test_news_mapper.py -q`

## 6. 風險與控制

1. 風險：search/fetch 為 I/O 密集且具外部不穩定性，重構可能誤改 degrade path。
   - 控制：維持 node error contract 不變；補強 degraded-path 測試。
2. 風險：artifact 邊界收斂時，舊 payload 結構解析差異造成 runtime fail。
   - 控制：先鎖定 parser/serializer contract tests，再搬遷 owner。
3. 風險：一次大切片可能導致回歸面擴大。
   - 控制：每切片固定 `ruff + targeted pytest + hygiene guard` 三重 gate。

## 7. 收斂估算

在「無 compatibility legacy」前提下，P1-P7 已完成；`news` 主線已收斂到與 FA/TA 同級的 clean architecture 目標。
但仍有一批 post-refactor correctness/observability/performance 議題，需要以 P8 完成最後硬化。

## 8. Post-Refactor Review Findings -> P8 Hardening Plan (2026-03-02)

本節對齊最新整體 review，將「架構已收斂但行為語義仍有偏差」的項目轉成可執行重構切片。
目標：不引入 legacy compatibility，直接把錯誤語義、節點狀態語義、與 async/perf 邊界收斂到 standards。

### 8.1 P8-A (P1 Critical) Artifact/State Error Semantics 一次修正

覆蓋問題：F1, F3, F5, F6, F7

F1. Artifact 缺失被靜默轉空資料（偽成功風險）
位置：
1. `src/agents/news/infrastructure/artifacts/news_artifact_repository.py` (`load_search_context/load_fetch_context/load_news_items_data`)
方案：
1. 引入明確語義：artifact 缺失時回傳顯式錯誤（`ArtifactNotFoundError` 或同等 typed failure），不可 silently return empty。
2. use-case 在 context load 失敗時直接走 error/degraded 明確分支，不再把「缺失」視為「空資料」。
3. 將 `INewsArtifactRepository` 的讀取契約改為可區分 `not_found` vs `empty_payload`。
驗收：
1. 缺 artifact id 或 artifact 不存在時，不可進入後續假成功路徑。
2. log/state 中可明確回放 root cause（artifact id + error_code）。

F3. Aggregator 有 degraded 訊號但 state 仍 success/done
位置：
1. `src/agents/news/application/use_cases/run_aggregator_node_use_case.py`
2. `src/agents/news/application/state_updates.py`
方案：
1. `build_aggregator_node_update` 改為根據 `degrade_messages` 設定 `status/node_statuses`：
   - no degrade -> `success/done`
   - degrade present -> `degraded/degraded`
2. 對於不可恢復錯誤（payload build fail / items load fail）維持 terminal error。
驗收：
1. `news_aggregator_degraded` 與 state `node_statuses` 一致。
2. 前端/下游觀測不再出現 log degraded 但狀態 success 的漂移。

F5. Selector context load 失敗仍調 LLM
位置：
1. `src/agents/news/application/use_cases/run_selector_node_use_case.py`
方案：
1. context load 失敗後直接 short-circuit，不再調 LLM。
2. 使用 deterministic fallback（top-N）或直接終止，依 contract 選一種固定策略；不得「失敗後又執行 LLM」。
驗收：
1. context load failed 時無 LLM invoke log。
2. state 明確標示 degraded/error，且 error_logs 含 context_load error_code。

F6. Search artifact save 失敗仍 goto selector
位置：
1. `src/agents/news/application/use_cases/run_search_node_use_case.py`
方案：
1. artifact save 失敗視為 search node failure（或 degraded + END），不得繼續 selector。
2. 若要保留可用結果，需同時滿足：有明確 in-memory handoff contract；否則直接 END。
驗收：
1. `search_artifact_id is None` 時不會 `goto="selector_node"`。
2. 搜尋儲存失敗能在 state 與 logs 被一致標記。

F7. Search 分支 state contract 不一致
位置：
1. `src/agents/news/application/state_updates.py`
方案：
1. 統一所有 search 分支 update 結構（至少含 `current_node`, `internal_progress`, `node_statuses`）。
2. `no_ticker/empty/error/success` 四分支全部對齊相同語義矩陣。
驗收：
1. tests 覆蓋四分支 contract shape；無分支缺欄位或語義矛盾。

### 8.2 P8-B (P2 High) Async/Perf 邊界修正

覆蓋問題：F4, F9

F4. Selector 在 async use-case 內使用 sync invoke（可能阻塞 event loop）
位置：
1. `src/agents/news/application/selection_service.py`
2. `src/agents/news/application/use_cases/run_selector_node_use_case.py`
方案：
1. 對 selector chain 套用與 analyst 相同策略：優先 `ainvoke`，否則 `asyncio.to_thread(invoke, ...)`。
2. 補充 protocol typing（selector 專用 async/sync boundary）。
驗收：
1. selector path 不直接在 event loop 上執行 blocking `invoke`。
2. `ruff + tests` 維持通過，且 selector 測試覆蓋 async fallback 分支。

F9. 每個 URL 新建 `httpx.AsyncClient`（連線成本偏高）
位置：
1. `src/agents/news/infrastructure/content_fetch/trafilatura_content_fetch_provider.py`
方案：
1. 改為 provider-level 可重用 `AsyncClient`（生命週期由 wiring/容器管理）。
2. 保留 timeout/headers，但避免每篇文章建新 client。
驗收：
1. fetch 批次平均 latency 降低或持平，連線建立開銷下降。
2. 無資源泄漏（client close 在應用關閉時有明確處理）。

### 8.3 P8-C (P2 High) Fetch 品質降級語義與可觀測性修正

覆蓋問題：F2

F2. 非 200/空內文未被視為可觀測降級，導致質量下降但狀態健康
位置：
1. `src/agents/news/infrastructure/content_fetch/trafilatura_content_fetch_provider.py`
2. `src/agents/news/application/use_cases/run_fetch_node_use_case.py`
3. `src/agents/news/application/fetch_service.py`
方案：
1. 將 fetch 結果從 `str | None` 擴展為 typed result（成功/失敗類型 + reason + http_status）。
2. 在 fetch use-case 中統計：
   - attempted_count
   - success_count
   - fail_count
   - fail_reasons 分佈（401/403/timeout/extract_empty）
3. fail_count > 0 時必設 degraded；並把摘要寫入 `error_logs`。
驗收：
1. 出現大量 401/403 時，state 必反映 degraded，不再「假健康」。
2. logs 可直接回答「為何只拿到少量全文」。

### 8.4 P8 執行順序（大切片）

1. Slice S1: `F1+F3+F5+F6+F7`（correctness/state contract，一次完成）
2. Slice S2: `F4+F9`（async/perf 邊界，一次完成）
3. Slice S3: `F2`（品質降級語義 + 指標，一次完成）

### 8.5 P8 測試與驗證門檻

每個 slice 必做：
1. `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/agents/news finance-agent-core/tests`
2. `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_news_application_use_cases.py finance-agent-core/tests/test_error_handling_news.py finance-agent-core/tests/test_news_interface_boundaries.py finance-agent-core/tests/test_news_preview_layers.py finance-agent-core/tests/test_news_import_hygiene_guard.py -q`
3. 新增/更新測試覆蓋：
   - artifact missing semantics（not found != empty）
   - search save fail 不得流向 selector
   - selector context fail 不得調用 LLM
   - aggregator degraded 時 state 必為 degraded
   - fetch failure ratio 與 degraded 狀態一致
