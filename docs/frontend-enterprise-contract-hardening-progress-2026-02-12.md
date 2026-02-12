# Frontend Enterprise Contract Hardening Progress (2026-02-12)

Related plan:
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/frontend-enterprise-contract-hardening-plan-2026-02-12.md`

## Status Overview

- Overall: `IN PROGRESS`
- Current wave: `Wave 6 (P0) Backend Canonical Artifact Serialization`

## Checklist

1. [x] 建立企業級 hardening plan 文檔
2. [x] `protocol.ts` 新增 REST parser（history/thread/stream start）
3. [x] `useAgent.ts` 改用 parser，移除邊界 cast
4. [x] parser 測試補齊（合法/非法 payload）
5. [x] 跑 frontend lint/typecheck/test
6. [x] 更新 progress 與後續 wave 任務
7. [x] 建立 `fundamental-preview-parser`，以 strict parser 取代 `as FinancialReport[]`
8. [x] `useFinancialData` 改為 parser-first（移除 preview 直接強轉）
9. [x] `FundamentalAnalysisOutput` 改為 parser-first（移除 `reports as FinancialReport[]`）
10. [x] Wave 2 擴展：Technical output 的 view-model parser 化
11. [x] Wave 2 擴展：News output 的 view-model parser 化
12. [x] Wave 2 擴展：Debate output 的 view-model parser 化
13. [x] Preview parser 按 domain 拆分（news/debate/technical）
14. [x] Wave 3 第三批：新增 lint/CI gate，防止 runtime `as` assertion 回歸
15. [x] 新增 output adapter/registry（agentId -> typed preview/view model）
16. [x] `AgentOutputTab` 改為單一解析入口（UI 不直接 parse preview）
17. [x] `Fundamental/News/Debate/Technical` output 改為接收 parsed preview + reference
18. [x] `useFinancialData` 改用 adapter helper 取 preview
19. [x] output adapter 測試補齊
20. [x] `GenericAgentOutput` 改為消費 adapter generic view model（不再依賴 raw output）
21. [x] SSE 入口改為 `parseAgentEvent(...)` 深層解析（取代淺層 guard）
22. [x] `useArtifact` 改為 parser-first（強制傳 parser）
23. [x] 新增 artifact parsers（fundamental/news/debate/technical/generic）
24. [x] 所有 output artifact 消費改為 parser-first
25. [x] 補齊 artifact parser 測試
26. [x] 補齊剩餘 response 邊界：`HTTP error payload` parser + `AgentStatusesResponse` parser + history interrupt data parser
27. [x] Nullability 對齊補漏：修正 backend 可能回 `null` 但 frontend parser 過嚴導致 runtime crash 的欄位
28. [x] 新增 backend canonical serializer 模組（fundamental/technical artifact）
29. [x] fundamental/technical node 存檔前接入 canonical serializer
30. [x] 補 backend serializer 測試（合法/非法 payload）
31. [x] Wave 6 驗證（backend ruff + pytest）完成
32. [x] Wave 6 擴展：news/debate full report 存檔前接入 canonical serializer
33. [x] 新增 `/api/artifacts/{id}` integration tests（contract shape）
34. [x] 修復 `test_error_handling_fundamental.py` async await 問題
35. [x] `canonical_serializers.py` 導入 model-driven 分層（news/debate/technical 轉由 Pydantic models 驅動）
36. [x] 新增 backend canonicalization 全流程文檔（含 pseudo）
37. [x] fundamental canonicalization 遷移至 Pydantic model-driven（含 traceable/report schema）
38. [x] `canonical_serializers.py` 收斂為純 facade（四個 domain 全部委派 `canonical_models`）
39. [x] `canonical_models` 依 domain 拆包（fundamental/news/debate/technical/shared）並移除 monolithic 檔案

## Execution Log

### 2026-02-12

1. 建立計劃文檔與落地範圍。
2. 完成 Wave 1：
   - `protocol.ts` 新增 `parseHistoryResponse`、`parseThreadStateResponse`、`parseStreamStartResponse`
   - `useAgent.ts` 移除 `as Message[]`、`as ThreadStateResponse` cast
   - stream start response 加入 runtime parse + thread id mismatch 保護
3. 測試與品質 gate：
   - `npm run lint` passed
   - `npm run typecheck` passed
   - `npm run test -- --run` passed
4. 已切換 parser policy 為「零兼容（fail-fast）」：
   - 移除未知 message type 的降階處理
   - 移除未知 node status 的降階處理
   - 移除 interrupt 欄位預設補值行為，改為嚴格驗證
5. Wave 2 第一批完成：
   - 新增 `src/types/agents/fundamental-preview-parser.ts`
   - `useFinancialData` 改走 strict parser，移除 `financial_reports as FinancialReport[]`
   - `FundamentalAnalysisOutput` 改走 strict parser，移除 `as FinancialReport[]`
   - 新增 parser tests：`src/types/agents/fundamental-preview-parser.test.ts`
6. Wave 2 第二批完成：
   - `src/types/preview.ts` 新增 strict parser：`parseNewsPreview`、`parseDebatePreview`
   - `NewsResearchOutput`、`DebateOutput` 改為 parser-first
   - 新增 tests：`src/types/preview.test.ts`
7. Wave 2 第三批完成：
   - `src/types/preview.ts` 新增 strict parser：`parseTechnicalPreview`
   - `TechnicalAnalysisOutput` 改為 parser-first
   - 移除多個技術面圖表中的型別斷言（`as number`）
8. Wave 2 完成，切換至 Wave 3（治理流程與 gate 文檔化/模板化）。
9. Wave 3 第一批完成：
   - `.github/pull_request_template.md` 新增 frontend parser-first checklist
   - 明確要求 frontend API 邊界禁止直接 `as` cast
   - 明確要求 preview 消費禁止 raw assertion（如 `as FinancialReport[]`）
10. Wave 3 第二批完成：
   - 清理 runtime 路徑型別斷言（`AINewsSummary`、`DynamicInterruptForm`、`FinancialTable`、`useAgent`、`useFinancialData`、`protocol parser`）
   - `InterruptResumePayload` 改為 strict union，新增 `parseInterruptResumePayload`
   - `fundamental-preview-parser` 移除泛型 `as` 斷言，改為顯式欄位 parser
   - 目前 `rg -n "\\sas\\s" frontend/src` 僅剩 import alias / 註解字樣，無 runtime 型別斷言
11. Wave 2 parser 模組化完成：
   - 將 `parseNewsPreview`、`parseDebatePreview`、`parseTechnicalPreview` 從 `src/types/preview.ts` 拆分至：
     - `src/types/agents/news-preview-parser.ts`
     - `src/types/agents/debate-preview-parser.ts`
     - `src/types/agents/technical-preview-parser.ts`
   - `NewsResearchOutput`、`DebateOutput`、`TechnicalAnalysisOutput` 改為直接引用各自 parser 模組
   - `preview.ts` 回歸單一職責：只保留 preview types/type guards
12. Wave 3 第三批完成：
   - `frontend/eslint.config.mjs` 新增 runtime 路徑規則：禁止 `TSAsExpression`
   - 規則覆蓋 `components/hooks/types(agents/protocol/interrupts)`，測試檔排除
   - 透過既有 CI `frontend-lint-type-test` job 機械化攔截 assertion 回歸
13. Wave 4 完成（Output Adapter/Registry）：
   - 新增 `src/types/agents/output-adapter.ts`，提供：
     - `adaptAgentOutput(...)`（agentId -> typed view model）
     - `parse*PreviewFromOutput(...)` helpers
   - `AgentOutputTab` 改為單一解析入口，`Fundamental/News/Debate/Technical/Generic` 全部只接收 adapter 結果
   - `FundamentalAnalysisOutput` / `NewsResearchOutput` / `DebateOutput` / `TechnicalAnalysisOutput` 移除 component 內 preview parser
   - `useFinancialData` 改用 `parseFundamentalPreviewFromOutput(...)`
   - 新增測試：`src/types/agents/output-adapter.test.ts`
14. Wave 4 驗證結果：
   - `npm run lint` passed
   - `npm run typecheck` passed
   - `npm run test -- --run` passed（`5 files`, `23 tests`）
15. Wave 5 完成（Full Response Standardization）：
   - `protocol.ts` 新增 `parseAgentEvent(...)`，`isAgentEvent(...)` 改為 parser-based guard
   - `useAgent.ts` stream 消費改為 `parseAgentEvent(...)`（payload drift fail-fast）
   - `useArtifact.ts` 改為必須注入 parser：artifact response 不可直接當 typed data 使用
   - 新增 `src/types/agents/artifact-parsers.ts`
   - `Fundamental/News/Debate/Technical/Generic` output 全部改為 artifact parser-first
   - 新增測試：`src/types/agents/artifact-parsers.test.ts`
16. Wave 5 驗證結果：
   - `npm run lint` passed
   - `npm run typecheck` passed
   - `npm run test -- --run` passed（`6 files`, `31 tests`）
17. Wave 5 補漏完成（remaining response coverage）：
   - `protocol.ts` 新增 `parseApiErrorMessage(...)`（支援 `detail: string` 與 `detail: ValidationError[]`）
   - `useAgent.ts` / `useArtifact.ts` non-2xx 路徑改為 parser-first error extraction（含 non-JSON fallback）
   - `protocol.ts` 新增 `parseAgentStatusesResponse(...)`，覆蓋 `/thread/{thread_id}/agents` contract response
   - `parseHistoryResponse(...)` 對 `interrupt.request` message data 改為 strict parse（缺失/錯型直接 fail-fast）
18. 補漏後驗證結果：
   - `npm run lint` passed
   - `npm run typecheck` passed
   - `npm run test -- --run` passed（`6 files`, `36 tests`）
19. Nullability 對齊補漏（同類風險掃描後）：
   - `fundamental preview`: `ticker` 允許 `null`（視為 absent）
   - `technical preview`: `ticker` 允許 `null`（視為 absent）
   - `protocol`: `TickerCandidate.exchange/type` 允許 `null`
   - `protocol`: `IntentExtraction.reasoning` 允許 `null`/缺失
   - `artifact parser`: `debate history.name/role`、`facts.value/units/period`、`technical.llm_interpretation`、`debate optional metrics` 允許 `null`（按 domain type 正規化）
   - `fundamental artifact`: `company_name/sector/industry/reasoning` nullable 值正規化為可渲染預設值
20. Nullability 補漏驗證結果：
   - `npm run lint` passed
   - `npm run typecheck` passed
   - `npm run test -- --run` passed（`6 files`, `42 tests`）
21. Wave 6 完成（Backend Canonical Artifact Serialization）：
   - 新增 `finance-agent-core/src/interface/canonical_serializers.py`
   - `fundamental_analysis/nodes.py`：
     - `financial_health` reports 存檔前走 `normalize_financial_reports(...)`
     - `model_selection` full report 存檔前走 `canonicalize_fundamental_artifact_data(...)`
   - `technical_analysis/nodes.py`：
     - `semantic_translate` full report 存檔前走 `canonicalize_technical_artifact_data(...)`
22. Wave 6 驗證結果：
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run ruff check src/interface/canonical_serializers.py src/workflow/nodes/fundamental_analysis/nodes.py src/workflow/nodes/technical_analysis/nodes.py tests/test_output_contract_serializers.py` passed
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_output_contract_serializers.py -q` passed（`3 passed`）
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py -q` passed（`21 passed`）
23. Wave 6 第二批完成（news/debate + API integration）：
   - `financial_news_research/nodes.py`：
     - final report 存檔前走 `canonicalize_news_artifact_data(...)`
   - `debate/nodes.py`：
     - verdict full report 存檔前走 `canonicalize_debate_artifact_data(...)`
   - `canonical_serializers.py` 擴展至 news/debate：
     - sentiment/impact/category/risk profile/verdict/price implication/source enums 正規化
     - debate `history/facts` 與 provenance JSON 正規化
24. Wave 6 第二批驗證結果：
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run ruff check src/interface/canonical_serializers.py src/workflow/nodes/financial_news_research/nodes.py src/workflow/nodes/debate/nodes.py tests/test_error_handling_fundamental.py tests/test_output_contract_serializers.py tests/test_artifact_api_contract.py` passed
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_error_handling_fundamental.py tests/test_output_contract_serializers.py tests/test_artifact_api_contract.py -q` passed（`10 passed`）
25. 測試修復：
   - `tests/test_error_handling_fundamental.py` 改為 async 測試（await `financial_health_node` / `model_selection_node`），消除 coroutine 未 await 問題。
26. Wave 6 第三批完成（Model-Driven Canonicalization）：
   - 新增 `src/interface/canonical_models.py`：
     - 以 Pydantic models + field validators 處理 news/debate/technical canonical normalization
   - `src/interface/canonical_serializers.py` 重整為 facade：
     - `fundamental` 保留 traceable 專用 normalize
     - `news/debate/technical` 委派 `canonical_models` model validation
   - model dump 統一 `exclude_none=True`（減少 optional null 噪音）
27. Wave 6 第三批驗證結果：
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run ruff check src/interface/canonical_models.py src/interface/canonical_serializers.py` passed
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_output_contract_serializers.py tests/test_artifact_api_contract.py tests/test_error_handling_fundamental.py -q` passed（`10 passed`）
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py tests/test_output_contract_serializers.py tests/test_artifact_api_contract.py tests/test_error_handling_fundamental.py -q` passed（`31 passed`）
28. 文檔新增：
   - `docs/backend-canonicalization-flow.md`
   - 說明 backend canonicalization 端到端流程與標準工作流（含 pseudo）。
29. Wave 6 第四批完成（Fundamental Model-Driven Migration）：
   - `src/interface/canonical_models.py` 新增：
     - `TraceableFieldModel`
     - `FundamentalBaseModel`
     - `Industrial/FinancialServices/RealEstate ExtensionModel`
     - `FinancialReportModel`（含 `industry_type/extension_type` 正規化與 extension type 推導）
     - `FundamentalArtifactModel`
   - `src/interface/canonical_serializers.py`：
     - `normalize_financial_reports(...)` / `canonicalize_fundamental_artifact_data(...)` 改為委派 model parser
     - 檔案收斂為薄 facade，不再承載 domain normalization 規則
30. Wave 6 第四批驗證結果：
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run ruff check src/interface/canonical_models.py src/interface/canonical_serializers.py tests/test_output_contract_serializers.py` passed
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_output_contract_serializers.py -q` passed（`5 passed`）
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py tests/test_output_contract_serializers.py tests/test_artifact_api_contract.py tests/test_error_handling_fundamental.py -q` passed（`31 passed`）
31. Wave 6 第五批完成（Canonical Models Domain Split）：
   - 新增 package：
     - `src/interface/canonical_models/__init__.py`
     - `src/interface/canonical_models/shared.py`
     - `src/interface/canonical_models/fundamental.py`
     - `src/interface/canonical_models/news.py`
     - `src/interface/canonical_models/debate.py`
     - `src/interface/canonical_models/technical.py`
   - 刪除 monolithic：
     - `src/interface/canonical_models.py`
   - `canonical_serializers.py` 透過 package export 使用分檔 parser（無行為變更，僅結構收斂）
32. Wave 6 第五批驗證結果：
   - `uv run --project finance-agent-core python -m ruff check finance-agent-core/src/interface/canonical_models finance-agent-core/src/interface/canonical_serializers.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py` passed
   - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_protocol.py finance-agent-core/tests/test_mappers.py finance-agent-core/tests/test_news_mapper.py finance-agent-core/tests/test_debate_mapper.py finance-agent-core/tests/test_output_contract_serializers.py finance-agent-core/tests/test_artifact_api_contract.py finance-agent-core/tests/test_error_handling_fundamental.py -q` passed（`31 passed`）
   - `uv run --project finance-agent-core python -m pytest finance-agent-core/tests/test_output_contract_serializers.py -q` passed（`5 passed`）
33. Wave 6 第六批完成（Valuation Path Canonical Alignment）：
   - 修復 `model_selection_node` 對 canonical report 的讀取（移除舊 `FinancialReport(**dict)` 依賴）
   - 修復 `param_builder`：
     - canonical report payload 正規化後再進 `FinancialReport.model_validate(...)`
     - 補 `industry_type` 必填映射與 `None` 欄位清理，避免 legacy model 驗證失敗
     - 若 traceable field 缺少 `name`，以欄位語義自動補齊，避免 valuation runtime 驗證中斷
   - `canonical_models/fundamental.py` 增強：
     - `TraceableFieldModel` 保留 `name`
     - report 同步輸出 `industry_type`
     - base/extension 開啟 `extra="allow"`，避免 valuation 所需欄位在 canonicalization 被丟失
   - 新增回歸測試：
     - `tests/test_param_builder_canonical_reports.py`
34. Wave 6 第六批驗證結果：
   - `uv run --project finance-agent-core python -m ruff check src/interface/canonical_models/fundamental.py src/workflow/nodes/fundamental_analysis/tools/valuation/param_builder.py tests/test_param_builder_canonical_reports.py` passed
   - `uv run --project finance-agent-core python -m pytest tests/test_param_builder_canonical_reports.py tests/test_output_contract_serializers.py tests/test_error_handling_fundamental.py -q` passed（`9 passed`）
   - `uv run --project finance-agent-core python -m pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py tests/test_output_contract_serializers.py tests/test_artifact_api_contract.py tests/test_error_handling_fundamental.py tests/test_param_builder_canonical_reports.py -q` passed（`33 passed`）
35. Wave 6 第七批完成（Param Builder Decoupling）：
   - `param_builder.py` 移除對 `sec_xbrl.models.FinancialReport` 的依賴
   - 改為本地 canonical adapter（`FinancialReport`/`BaseFinancialModel`/`*Extension` dataclass + traceable coercion）
   - valuation path 僅依賴 canonical contract，不再依賴舊 report class 的必填欄位假設
36. Wave 6 第七批驗證結果：
   - `uv run --project finance-agent-core python -m ruff check src/workflow/nodes/fundamental_analysis/tools/valuation/param_builder.py tests/test_param_builder_canonical_reports.py` passed
   - `uv run --project finance-agent-core python -m pytest tests/test_param_builder_canonical_reports.py tests/test_error_handling_fundamental.py -q` passed（`4 passed`）
   - `uv run --project finance-agent-core python -m pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py tests/test_output_contract_serializers.py tests/test_artifact_api_contract.py tests/test_error_handling_fundamental.py tests/test_param_builder_canonical_reports.py -q` passed（`33 passed`）
37. Wave 6 第八批完成（Shared Contract Adapter Module）：
   - 新增 `src/workflow/nodes/fundamental_analysis/tools/valuation/report_contract.py`
   - 抽離 canonical report parsing/coercion（traceable/provenance/industry mapping）為可重用模組
   - `param_builder.py` 改為依賴 `report_contract.parse_financial_reports(...)`
38. Wave 6 第八批驗證結果：
   - `uv run --project finance-agent-core python -m ruff check src/workflow/nodes/fundamental_analysis/tools/valuation/report_contract.py src/workflow/nodes/fundamental_analysis/tools/valuation/param_builder.py tests/test_param_builder_canonical_reports.py` passed
   - `uv run --project finance-agent-core python -m pytest tests/test_param_builder_canonical_reports.py tests/test_error_handling_fundamental.py tests/test_output_contract_serializers.py -q` passed（`9 passed`）
   - `uv run --project finance-agent-core python -m pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py tests/test_output_contract_serializers.py tests/test_artifact_api_contract.py tests/test_error_handling_fundamental.py tests/test_param_builder_canonical_reports.py -q` passed（`33 passed`）

## Risks / Notes

1. 目前已採 zero-compat parser；後端只要 payload 漂移，前端會直接 fail-fast。
2. 規則目前鎖定 runtime 關鍵路徑；若未來新增 runtime folder，需同步擴充 ESLint `files` 範圍。
3. 目前 adapter 僅覆蓋核心四個 output agent；若新增 agent，需同步擴充 `output-adapter.ts` 與 adapter tests。
4. 新增 artifact endpoint 或 SSE event type 時，必須同步新增 parser 與測試，否則無法通過 Wave5 標準。
5. 已擴展覆蓋 news/debate；若未來新增 artifact 類型，需同步新增 canonical serializer 與 API integration tests。
6. `canonical_models` 已按 domain 拆包；後續新增 domain 時需同步更新 `canonical_models/__init__.py` export 與 serializer tests，避免 parser registry 漏接。
