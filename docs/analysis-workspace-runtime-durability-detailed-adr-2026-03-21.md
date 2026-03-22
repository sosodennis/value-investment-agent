# Analysis Workspace Runtime Durability Detailed ADR

Date: 2026-03-21
Status: Accepted
Owner: Workflow Runtime + Frontend Workspace
Companion To: `/Users/denniswong/Desktop/Project/value-investment-agent/docs/analysis-workspace-runtime-durability-adr-2026-03-21.md`

## Requirement Breakdown

- 目標：一次性把 Analysis Workspace 的 refresh / reconnect / completed-thread restore 治理到企業級可維護水準。
- 成功標準：
  - refresh 期間，active agent、current task、interrupt、recent activity 都能從 durable backend truth 還原
  - completed thread 也能還原 workflow activity，不依賴 process memory
  - SSE reconnect 能從 cursor 恢復，不靠 whole-buffer replay
  - per-agent message/history view 能靠 durable `agent identity` 正確還原
  - frontend 不再猜測 truth，也不再把 `localStorage` 或過期 `node_statuses` 當主來源
  - 舊的 replay-buffer-based restore 已刪除，不保留兼容路徑
- 約束：
  - 不寫長期 compatibility shim
  - 保留現有 LangGraph + FastAPI + Next.js 主拓樸
  - 嚴格 typing
  - 不把 WebSocket 作為本輪前提
  - 不讓 UI 直接耦合 LangGraph raw internal state semantics
- 非目標：
  - 不做 product-facing workflow dashboard
  - 不把整個 runtime 遷移到 LangGraph Platform SDK
  - 不為了短期兼容保留雙 restore path

## External Verification

這份 detailed ADR 依據官方文件再次核實，結論如下：

- LangGraph persistence 把 thread/checkpoint/state history 作為 durable execution 基礎，並可用 `get_state()` / `get_state_history()` 取回 thread 狀態與歷史。
  Source: [LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
- LangGraph streaming 官方推薦明確 stream mode，如 `updates`、`values`、`tasks`、`checkpoints`，而不是把 debug-style raw event 當唯一 UI truth。
  Source: [LangGraph Streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
- LangGraph subgraphs 可以顯式向 parent stream 輸出 subgraph updates，這意味著 subgraph activity 應被明確 surfaced，而不是依賴 incidental bubbling。
  Source: [LangGraph Use Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- LangGraph durable execution 明確要求 deterministic / idempotent。
  Source: [LangGraph Durable Execution](https://docs.langchain.com/oss/javascript/langgraph/durable-execution)
- MDN SSE 明確定義 `event`、`data`、`id`、`retry`、keepalive comments，以及連線中斷後預設會重連。
  Source: [MDN Using server-sent events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)
- MDN EventSource 定義了 `readyState` 與 `.close()`，支援標準連線生命週期管理。
  Source: [MDN EventSource](https://developer.mozilla.org/en-US/docs/Web/API/EventSource)
- LangChain frontend 官方模式是 `thread persistence + reconnectOnMount/joinStream`，而且深代理前端文檔直接把 page reload 後由 thread history/state 重建前端狀態視為目標能力。
  Sources: [LangChain Frontend Overview](https://docs.langchain.com/oss/python/langchain/frontend/overview), [LangChain Frontend Streaming](https://docs.langchain.com/oss/python/langchain/streaming/frontend), [LangGraph Deep Agents Frontend](https://docs.langchain.com/oss/javascript/deepagents/streaming/frontend)
- Mercure 規範明確支援以 query parameter 傳遞 `Last-Event-ID`，這正是原生 `EventSource` 首次 attach 無法自訂 header 時的成熟做法。
  Source: [Mercure Protocol](https://mercure.rocks/spec)
- 成熟 event-sourcing/read-model 系統將 projection 視為 eventually consistent 且可重建的 read model。
  Source: [EventSourcingDB Read Models](https://docs.eventsourcingdb.io/best-practices/designing-read-models/)
- LangGraph / LangSmith 官方提供 thread/checkpoint TTL 配置，說明 retention 屬於設計邊界而不是僅僅運維細節。
  Source: [Configure TTL](https://docs.langchain.com/langsmith/configure-ttl)

採納的結論：

- restore truth 必須來自 durable thread/checkpoint/history 與 durable runtime projection
- stream 應送出 UI 需要的明確 typed deltas，而不是依賴 replay whole history
- reconnect 必須走 event id / cursor
- runtime projection 必須 append-only，且可從同一 thread 下重建 active state
- browser `EventSource` constructor 只接受 URL 與 credentials mode，因此首次 attach 的 cursor 需透過 URL / query parameter 傳遞；後續重連可依賴 SSE event ID
- restore/stream 契約應盡量向 LangChain/LangGraph `thread + run + rejoin stream` 心智模型靠攏
- runtime durability 的 deployment contract 應明確納入 HTTP/2 與 retention/TTL

## Technical Objectives and Strategy

### 核心策略

採用雙平面架構：

- `Durable State Plane`
  - LangGraph thread/checkpoint/history
  - persistent chat history
  - new runtime activity projection
- `Live Event Plane`
  - SSE as delta transport only
  - cursor-based resume

### 對齊成熟項目模式

本方案收斂到三種成熟模式的交集：

- LangChain frontend:
  - persisted thread identity
  - reconnect/join stream semantics
  - page reload 後由 durable backend state 重建前端
- Mercure / SSE:
  - first attach via URL-level cursor
  - reconnect via SSE event ID
- event-sourced read models:
  - projection is derived
  - source of truth remains durable history
  - projection can be rebuilt

### 真相模型

Analysis Workspace 的 restore truth 由三部分組成：

1. `thread snapshot truth`
   - current checkpointed values
   - current interrupt state
   - next executable nodes / graph position
2. `runtime activity truth`
   - agent/node activity transitions
   - active agent
   - recent activity timeline
   - durable sequence cursor
3. `message truth`
   - persisted chat messages with first-class durable agent identity

### 為什麼不保留現有路徑

現有 `event_replay_buffers` 方案不是企業級：

- 只存在於 process memory
- bounded buffer 無法保證 completed-thread history
- reducer dedupe + replay merge 讓 frontend restore state machine 複雜且脆弱
- 對 parallel/subgraph agent activity 的表示不可靠

## Involved Files

### 直接修改

- [server.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py)
- [models.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/infrastructure/models.py)
- [database.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/infrastructure/database.py)
- [history.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/services/history.py)
- [state.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/state.py)
- [useAgent.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgent.ts)
- [useAgentReducer.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgentReducer.ts)
- [protocol.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/protocol.ts)
- [page.tsx](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/app/page.tsx)
- [AgentDetailPanel.tsx](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/components/AgentDetailPanel.tsx)
- [AgentWorkspaceTab.tsx](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/components/agent-detail/AgentWorkspaceTab.tsx)

### 建議新增

- `finance-agent-core/src/runtime/workspace_runtime_projection/domain/contracts.py`
- `finance-agent-core/src/runtime/workspace_runtime_projection/domain/derivation_service.py`
- `finance-agent-core/src/runtime/workspace_runtime_projection/application/ports.py`
- `finance-agent-core/src/runtime/workspace_runtime_projection/application/runtime_projection_service.py`
- `finance-agent-core/src/runtime/workspace_runtime_projection/interface/contracts.py`
- `finance-agent-core/src/runtime/workspace_runtime_projection/infrastructure/repository.py`
- `finance-agent-core/tests/test_workspace_runtime_projection.py`
- `finance-agent-core/tests/test_workspace_runtime_projection_runtime_service.py`
- `finance-agent-core/tests/test_stream_cursor_contract.py`
- `frontend/src/app/page.test.tsx`

## Layer Topology and Shared Kernel Placement

### 新 capability placement

不建議把這塊塞進 `src/infrastructure/shared` 或 `frontend/lib` 的匿名工具堆。

建議新增 agent-agnostic but workspace-owned capability：

- `finance-agent-core/src/runtime/workspace_runtime_projection`

owner placement：

- `domain`
  - projection records semantics
  - active agent derivation
  - timeline coalescing rules
  - cursor semantics
- `application`
  - write/read ports
  - restore snapshot orchestration
- `interface`
  - snapshot DTOs
  - activity row DTOs
  - SSE envelope serialization contract
- `infrastructure`
  - SQLAlchemy repository
  - DB read/write implementation

### 為什麼不拆到每個 agent subdomain

這是 workspace runtime capability，不是某個 domain agent 的業務子域。

- capability boundary：單一 coherent restore/read concern
- dependency boundary：統一依賴 LangGraph runtime + DB
- ownership boundary：屬於 workspace/runtime platform concern

## Detailed Per-File Plan

### [models.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/infrastructure/models.py)

新增 append-only runtime projection table，建議至少包含：

- `WorkspaceRuntimeActivityEvent`
  - `event_id`
  - `thread_id`
  - `seq_id`
  - `run_id`
  - `agent_id`
  - `node`
  - `event_type`
  - `status`
  - `payload`
  - `created_at`
- `WorkspaceRuntimeCursor`
  - `thread_id`
  - `last_seq_id`
  - `updated_at`

同時將 chat history 的 agent identity 升級為 first-class persisted field：

- `ChatMessage.agent_id`
  - nullable for truly unowned system/tool rows
  - indexed by `thread_id + agent_id + created_at`

設計要求：

- `thread_id + seq_id` unique
- append-only，不做 in-place mutation
- 索引支援：
  - `thread_id + seq_id`
  - `thread_id + created_at`
  - `thread_id + agent_id + created_at`

### [database.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/infrastructure/database.py)

- 確保新 projection ORM 註冊進 `init_db()`
- 如有 migration flow，補 migration registration strategy

### [history.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/services/history.py)

- 保持 chat history 為 durable message truth
- 將 `agent_id` 從鬆散 metadata 提升為 first-class durable field
- metadata 中可保留 `agentId/agent_id` 作 transport compatibility source during migration, 但 target state 應以欄位為準
- API 不應在 restore path 臨時猜 agent ownership

### [state.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/state.py)

- 檢查 root state 中哪些欄位是 workspace snapshot contract 真正要用的
- 不再讓 frontend 直接依賴 `node_statuses` 作為唯一 workflow truth
- 若需要，新增明確 parent-visible runtime summary fields

### subgraph state files

- [intent_extraction/subgraph_state.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/intent_extraction/subgraph_state.py)
- [fundamental_analysis/subgraph_state.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/fundamental_analysis/subgraph_state.py)
- [financial_news_research/subgraph_state.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/subgraph_state.py)
- [technical_analysis/subgraph_state.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/technical_analysis/subgraph_state.py)
- [debate/subgraph_state.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/debate/subgraph_state.py)

檢查點：

- 哪些 subgraph updates 需要 surfaced 到 root runtime projection
- 若某 subgraph 現在明確不 share `node_statuses`，不能再指望 frontend 從 root snapshot 猜出它的 live process
- 使用 stream `updates/tasks/checkpoints` 或明確 projection write 來捕捉 subgraph activity

### new runtime projection service

Responsibilities：

- consume runtime events
- append durable projection rows
- derive:
  - `active_agent_id`
  - `current_task`
  - `activity_timeline`
  - `last_seq_id`

不應：

- 直接做 FastAPI response assembly
- 直接操作 frontend concerns

### [server.py](/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py)

重做三塊：

1. `/thread/{thread_id}`
   - 只回 durable snapshot
   - 組合來源：
     - checkpointed state
     - durable projection
     - durable history
2. `/thread/{thread_id}/activity`
   - 若需要獨立 endpoint，回 paginated activity rows
3. `/stream/{thread_id}`
   - 走標準 SSE envelope：
     - `id: <seq>`
     - `event: <name>`
     - `data: <json>`
     - `retry: <ms>` when appropriate
   - 首次 attach 支援 `after_seq` query parameter
   - reconnect 支援 `Last-Event-ID`，並可保留 `after_seq` 作顯式 fallback
   - keepalive comments
   - contract 命名和心智模型應盡量接近 LangChain/LangGraph 的 thread/run/stream restore 語義

要刪掉：

- replay-buffer-based restore ownership
- 以 `event_replay_buffers` 組裝 `status_history`

### [useAgent.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgent.ts)

重寫成：

1. `loadSnapshot(threadId)`
2. `hydrateFromSnapshot(snapshot)`
3. `connectStream(threadId, cursor)`
4. `mergeDelta(event)`

不再：

- fetch history + thread + replay stream 後由 reducer 猜真相

### [useAgentReducer.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgentReducer.ts)

state 應拆清楚：

- `snapshot`
- `activityTimeline`
- `liveCursor`
- `messages`
- `agents`

reducer policy：

- snapshot hydrate 是 one-shot authoritative restore
- stream event 只做 post-cursor incremental merge
- duplicate suppression 基於 cursor，不基於「希望 replay 都是舊事件」

### [protocol.ts](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/protocol.ts)

- 重新定義 durable snapshot DTO parser
- 定義 new SSE envelope parser
- 類型上明確區分：
  - snapshot model
  - activity row
  - stream delta event

### [page.tsx](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/app/page.tsx)

selected agent policy 改成：

1. snapshot active agent
2. latest activity row agent
3. persisted UI preference

不是：

1. persisted UI preference
2. stale roster

### [AgentDetailPanel.tsx](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/components/AgentDetailPanel.tsx)

- 接收已整理好的 active agent context
- 不再自己猜 workflow truth

### [AgentWorkspaceTab.tsx](/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/components/agent-detail/AgentWorkspaceTab.tsx)

- 顯示 snapshot + activity timeline
- 空狀態只在真的沒有 durable activity 時才出現
- `Live Session` badge 應依 durable running state，而不是僅靠 stale agent.status

## Old → New Mapping

舊 restore 主線：

- `/thread` partial snapshot
- `/stream` replay all buffered events
- reducer `seq_id <= lastSeqId` drop duplicates
- `node_statuses` + `activityFeed` 合併猜 active process

新 restore 主線：

- durable thread snapshot API
- durable activity projection API / embedded snapshot rows
- cursorized SSE attach
- reducer 只處理 post-cursor deltas

舊 completed-thread history：

- process memory buffer

新 completed-thread history：

- DB-backed runtime projection

## Cohesion/Facade Plan

外部 import 不應深穿 backend runtime internals。

推薦 facade：

- `workspace_runtime_projection.__init__`

提供：

- snapshot loader
- activity query service
- stream cursor contract

`server.py` 只依賴 facade / interface contracts，不直接 deep import domain derivation internals。

frontend 也應收斂成：

- `useAgentRestoreSession`
- typed snapshot parser
- typed stream parser

不讓 `page.tsx` 和 tab component 各自拼 restore logic。

## Risk/Dependency Assessment

### 功能風險

- projection 若遺漏 interrupt / lifecycle semantics，restore 仍會不完整
- active agent derivation 若規則不穩，UI 仍可能聚焦錯 agent
- subgraph activity 若沒有明確 surfaced，parallel agent process 顯示仍會漂

### runtime 風險

- cursor bug 可能造成 duplicate 或 skip
- sequence ownership若散落多處，會讓 SSE resume 不可預測
- projection writes 若非 append-only，debug/audit 會變難
- checkpoint 與 projection 間若無明確一致性策略，restore truth 可能短暫撕裂

### migration 風險

- phase 3 和 phase 4 是最敏感的 API/transport cutover
- frontend restore rewrite 若與 backend contract 同時漂移，容易卡在 integration
- legacy removal 太晚做，會留下技術債；太早做，會中斷 restore 功能

### consistency stance

本方案不把 projection 和 checkpoint 強行包裝成單一 ACID transaction 前提。

採納的企業級策略是：

- checkpointed thread state 為絕對權威
- runtime projection 為 eventual-consistent read model
- projection append 需 deterministic、idempotent
- 系統需提供 reconcile / rebuild path，可由 durable thread history 重新導出 projection

### deployment stance

本方案將以下項目視為架構的一部分：

- SSE-heavy operator workflows 在正式環境默認要求 HTTP/2
- thread/checkpoint retention 需顯式設定 TTL 或等價保留政策
- runtime projection 需有 retention / archive / cleanup policy
- 若 projection retention 與 thread retention 不一致，需明確定義 rebuild window

### rollback checkpoints

- Phase 1 projection schema 可單獨回退
- Phase 2 projection writes 可暫時關閉，但不應影響主 workflow
- Phase 3 new snapshot API 應在測試完整前不替換主 restore consumer
- Phase 6 才刪 legacy path；一旦完成即不回頭保兼容

## Validation and Rollout Gates

### Phase 1: Projection Foundation

- ORM model tests
- repository round-trip tests
- active agent derivation unit tests
- `ruff` on changed backend paths

### Phase 2: Runtime Writes

- runtime event append tests
- idempotency / duplicate-seq rejection tests
- interrupt and lifecycle coverage tests
- projection reconcile / rebuild tests

### Phase 3: Snapshot API

- API contract tests
- active-run restore tests
- completed-thread restore tests
- per-agent history restore tests
- generated contract sync

### Phase 4: SSE Cursor

- reconnect from cursor tests
- duplicate event suppression tests
- gap handling tests
- keepalive behavior tests
- initial attach via `after_seq` tests

### Phase 5: Frontend Rewrite

- hook restore tests
- page selection tests
- workspace panel rendering tests
- refresh integration tests
- typecheck + changed-path eslint

### Phase 6: Legacy Removal

- import hygiene sweep
- grep for deleted replay restore ownership
- end-to-end refresh/reconnect/completed-thread scenario validation

### 暫時無法完全驗證的項目

- 真實 production 多 tab / 多 browser SSE behavior，需要部署環境驗證
- HTTP/2 實際部署下 SSE 連線上限與代理設定，需要 infra 層確認
- 長時間運行 thread 的 projection volume/retention，需要真實數據觀察

## Assumptions/Open Questions

- 假設你接受新增一個 backend runtime projection capability，而不是強迫所有 restore 資訊都直接從 LangGraph raw state 即時拼裝
- 假設 SSE 仍是你想保留的 transport
- 假設 completed-thread workflow history 是這次治理範圍的一部分，不只解 active-run refresh

仍需在 implementation 前明確拍板的點：

- projection 是否採單表 append-only + derived read，或 event table + cursor table 雙表
- `/thread/{thread_id}` 是否內嵌 recent activity，還是 activity 獨立 endpoint
- cursor 欄位名稱是完全採 SSE `Last-Event-ID`，還是同時支援 `after_seq` 查詢參數
- 是否在本輪順手把 `ChatMessage.created_at` 等 timestamp 一律收斂成 timezone-aware policy
- 是否在 API 命名上更進一步向 LangChain/LangGraph 官方 thread/run/stream 心智模型對齊

## Final Recommendation

若目標是「一次治理好，盡量不留技術債」，本輪應採：

- no-compat migration
- durable runtime projection as first-class capability
- snapshot-first frontend restore
- cursor-based SSE
- same-program legacy deletion

這是複雜度中高的重構，但它是乾淨且可維護的最短路徑。
