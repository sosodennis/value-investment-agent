# Fullstack Clean Architecture Blueprint (Agent Workflow)
Date: 2026-02-12
Status: Historical reference (non-normative)

Authoritative active rules:
1. `/Users/denniswong/Desktop/Project/value-investment-agent/docs/clean-architecture-engineering-guideline.md`
2. `/Users/denniswong/Desktop/Project/value-investment-agent/docs/backend-guideline.md`
3. `/Users/denniswong/Desktop/Project/value-investment-agent/docs/frontend-guideline.md`

Implementation tracking:
1. `/Users/denniswong/Desktop/Project/value-investment-agent/docs/clean-architecture-engineering-guideline.md`
2. `/Users/denniswong/Desktop/Project/value-investment-agent/docs/backend-guideline.md`
3. `/Users/denniswong/Desktop/Project/value-investment-agent/docs/frontend-guideline.md`

## 1. Objective

把目前 monorepo 從「功能可運作但邊界易漂移」升級為「可審計、可維護、可持續演進」的 Clean Architecture 實作。

本文件回答三個核心問題：
1. 前後端如何各自落地 Clean Architecture。
2. `PreviewModel` / `ArtifactModel` 應屬於哪一層。
3. `Agent Workflow` 在架構中的定位與責任邊界。

## 2. Core Definitions

### 2.1 Clean Architecture in this project

我們採用務實版四層：
1. `Domain`：純商業規則與不可變約束（估值、風險、provenance 規則）。
2. `Application`：Use Case / Workflow 編排（LangGraph 節點與流程控制）。
3. `Interface`：對外契約與轉換（API/SSE contract、parser、mapper、adapter）。
4. `Infrastructure`：DB、Artifact Store、外部 API/LLM、檔案/快取。

依賴方向固定為：
`Domain <- Application <- Interface <- Infrastructure`

### 2.2 What PreviewModel and ArtifactModel are

1. `PreviewModel`：Interface 層的「UI 即時投影模型」。
2. `ArtifactModel`：Interface 層的「持久化與跨 Agent 消費契約模型」。
3. 兩者都不是 Domain Entity；它們是 contract DTO。

### 2.3 What Agent Workflow is

1. `Agent Workflow` 是 Application 層（不是 Domain）。
2. 職責是協調步驟、轉移狀態、呼叫 Port，不負責臨時 shape 猜測或跨層修補。

## 3. Backend Layering Blueprint

## 3.1 Target responsibilities

1. Domain
   - Valuation rules, traceable/provenance invariants, financial semantics.
2. Application
   - Agent workflow use cases (`intent -> FA/news/TA -> debate`)。
   - 僅依賴 Domain + Port interfaces。
3. Interface
   - `PreviewModel` / `ArtifactModel` / API response models / SSE event models。
   - Node output adapter, canonical serializer facade。
4. Infrastructure
   - SQLAlchemy models, artifact persistence, external tool wrappers。

## 3.2 Current -> target mapping (incremental)

1. Current `src/workflow/nodes/**`:
   - 保留為 Application 層主體，但要抽離手寫 contract/fallback 到 Interface layer。
2. Current `src/interface/artifacts/artifact_contract_specs.py` + `src/interface/artifacts/artifact_model_shared.py`:
   - 作為 Interface contract core（方向正確）。
3. Current `src/services/artifact_manager.py`:
   - 升級為 typed repository（save/load with contract validation）。

## 4. Frontend Layering Blueprint

## 4.1 Target responsibilities

1. Domain (frontend domain/view model)
   - UI 只處理可渲染 view model，不直接碰 raw response。
2. Application
   - hooks/reducer orchestration (`useAgent`, `useArtifact`, state transitions)。
3. Interface
   - generated API types + runtime parser/adapters (`contract -> parser -> view model`)。
4. Infrastructure
   - fetch/SSE transport, retry/cache policy。

## 4.2 Non-negotiable boundary

`Generated/OpenAPI Types` -> `Parser/Adapter` -> `ViewModel` -> `UI`

UI 層禁止自行判斷 raw shape。

## 5. Contract Model Standard (Recommended)

## 5.1 Agent output envelope (state.update)

```python
class AgentOutputEnvelope(BaseModel):
    kind: str               # e.g. "fundamental_analysis.output"
    version: str            # e.g. "v1"
    summary: str
    preview: dict[str, object] | None
    reference: ArtifactReference | None
```

## 5.2 Artifact envelope (for store + cross-agent)

```python
class ArtifactEnvelope(BaseModel):
    kind: str               # e.g. "fundamental.financial_reports"
    version: str            # e.g. "v1"
    produced_by: str        # agent_id
    created_at: str
    data: dict[str, object] | list[object]
```

## 5.3 Why this matters

1. Agent 間不再用 `if dict/list` + fallback 推測 shape。
2. `/api/artifacts/{id}` 可回傳 discriminated union，而不是 `unknown`。
3. 前端可自動生成更強的 parser/client，手寫邏輯大幅下降。

## 6. Agent-to-Agent Rules

1. 只讀「final canonical artifact kinds」，不讀中間臨時 payload。
2. 消費方必須聲明 `expected kind/version`。
3. `artifact_manager.load(...)` 若 kind/version 不符，立即 fail-fast。
4. 不允許跨 agent 直接讀對方 context 任意欄位作核心決策。

## 7. Engineering Guardrails

1. 禁止在 Application 層做 shape fallback（例如 list/dict 雙分支猜測）。
2. 所有新 artifact kind 必須：
   - 有 Pydantic contract model
   - 有 serializer test
   - 有 API contract test
   - 有 frontend parser test
3. PR 必附：
   - contract diff
   - parser/adapters diff
   - e2e/fixture evidence

## 8. Suggested Refactor Path (Agent-by-Agent)

先採「單 Agent 完整切片」而非大爆炸重寫。

評估維度：
1. 影響面（跨 agent 依賴數量）
2. 漂移風險（目前 fallback/shape guess 程度）
3. 測試可控性（是否已有 contract tests）

推薦順序：
1. `fundamental_analysis`：高價值 + 現有 contract 已有基礎，可先打樣 typed artifact port。
2. `technical_analysis`：輸出 shape 明確，第二波可快速固化。
3. `financial_news_research`：中等複雜度，連動 debate。
4. `debate`：最後做，因為依賴最多，需先有上游 typed contracts。

## 9. Decision Template (for choosing first agent)

```text
Agent:
Current pain:
Current fallback/shape-guess points:
Target contracts (preview/artifact):
Required API/frontend changes:
Test gates:
Risk:
Rollback:
```

## 10. Definition of Done (Architecture Level)

達成以下條件才算「完成一個 Agent 的 Clean 化」：
1. 該 Agent 的 preview/artifact 由單一 contract model 定義。
2. 該 Agent 輸入依賴透過 typed artifact port，而非 context 猜測。
3. API contract、frontend parser、workflow tests 全部綠燈。
4. 無 compatibility/fallback 分支殘留於 Application 層。
