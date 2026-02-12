# Monorepo Frontend-Backend Contract Risk Report
Date: 2026-02-12
Scope: `/finance-agent-core` + `/frontend`

## 1. Executive Summary

結論先講：**在你目前這個 monorepo 架構下，前後端同時改動時「漏改」風險是中高（Medium-High）**，尤其是：

1. 事件協議（SSE payload）欄位變更
2. interrupt schema（RJSF schema）變更
3. agent output preview/reference 欄位新增或型別改變

雖然最近重構已經把系統拉回「有 canonical shape」的方向，但目前仍缺少企業級最關鍵的一層：**跨語言單一真相來源（SSOT）+ 自動化 contract gate（CI）**。
所以現在仍依賴工程師自律與 code review，這在多人並行開發下會漏。

## 2. Current-State Evidence (Code-Based)

### 2.1 Positive Controls Already in Place

1. Backend 已有 canonical artifact container（`summary/preview/reference`）：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/schemas.py`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/common/types.py`
2. Backend adapter 對 `on_chain_end` 已做型別收斂，避免隱式 duck typing：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/adapters.py`
3. Frontend 已轉向 `StandardAgentOutput`，不再依賴舊版 `artifact.*` fallback：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/index.ts`
   - `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgentReducer.ts`

### 2.2 Gaps That Still Cause Missed Integration

1. **Contract duplicated in two languages**（Python + TypeScript 各自維護），未自動同步。
2. **FastAPI endpoint 缺少 `response_model` 作為硬邊界**，例如 `/thread/{thread_id}` 與 `/thread/{thread_id}/agents` 回傳 raw dict：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py`
3. **SSE event 的 `data` 在 backend 是寬型別 `dict[str, object]`**，前端以 union 假設，但無 schema-level 強驗證：
   - Backend: `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/protocol.py`
   - Frontend: `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/protocol.ts`
4. **Interrupt schema 有漂移風險**：backend 仍產生 `enumNames`；frontend 已朝 `oneOf` 對齊：
   - Backend: `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/adapters.py`
   - Frontend: `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgentReducer.ts`
5. **沒有 monorepo CI workflow 檔案**（目前只看到 PR template，沒有自動 gate）：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/.github/pull_request_template.md`
6. **Frontend 缺少獨立 `tsc --noEmit` script gate**，僅 lint/test，型別錯誤可能到 build 階段才爆。

## 3. Risk Assessment (Enterprise Lens)

### P1 (High)

1. 協議欄位 drift（新增/改名/nullable 變化）導致 runtime break，但 PR 可過。
2. 單一 agent payload 變更未更新對應 UI parser，造成空白卡片或 error fallback。

### P2 (Medium)

1. Interrupt schema 在 RJSF 行為上的差異（`enumNames` vs `oneOf`）造成 UI 行為不一致。
2. Frontend `isAgentEvent` 屬淺層驗證，event-specific data mismatch 不一定被攔截。

### P3 (Low-Medium)

1. 透過人工 checklist 管控，隨人數成長會退化。

## 4. Enterprise-Grade Target Standard

## A. Single Source of Truth Contract

1. Backend 用 Pydantic 定義完整 API + SSE 協議（含 event-specific `data` models）。
2. 對外 REST endpoint 全部加 `response_model`。
3. 由 OpenAPI/JSON Schema 自動產生 frontend types（禁止手寫鏡像型別）。

## B. Protocol Versioning

1. 事件 envelope 增加 `protocol_version`（例如 `v1`）。
2. 任何 breaking change 必須 bump version，並提供明確 migration window（你目前可設 0 相容策略，但版本要有）。

## C. Consumer-Driven Contract Tests

1. Backend 產生 golden event fixtures（含 `state.update`, `interrupt.request`, `agent.status`）。
2. Frontend 在 CI 中對 fixtures 做 decode + render smoke test。
3. 任何 fixture 破壞即 fail PR。

## D. CI as Gatekeeper (Must-Have)

Monorepo PR 至少要有以下 mandatory jobs：

1. `backend-lint-test`: ruff + pytest contract suites
2. `frontend-lint-type-test`: eslint + `tsc --noEmit` + vitest
3. `contract-check`: schema/codegen diff must be clean（若 backend contract 變更但 frontend types 未更新則 fail）

## E. Ownership Model

1. 指定 `Contract Owner`（可由 backend lead 擔任）。
2. 所有 `protocol/schema` 改動必須有前端 reviewer。
3. PR template 增加「contract changed? yes/no」+ 證據欄（fixtures / codegen diff）。

## 5. Recommended Rollout Plan

### Phase 1 (1 week): Stabilize

1. 補 `response_model` 到關鍵 endpoint（`/thread/*`, `/history/*`, `/stream` 啟動回應）。
2. frontend 新增 `typecheck` script 並納入必跑流程。
3. interrupt schema 統一為 `oneOf`（backend/frontend 同步）。

### Phase 2 (1-2 weeks): Contract Automation

1. 導出 OpenAPI 並建立 frontend codegen pipeline。
2. 新增 contract fixtures + frontend decode tests。
3. PR gate 導入 `contract-check`。

### Phase 3 (2-4 weeks): Enterprise Hardening

1. 事件版本化（`protocol_version`）。
2. 上線後加入 observability：schema validation failure metrics + alert。
3. 建立 breaking-change policy（RFC/ADR 模板）。

## 6. Definition of Done (Enterprise)

以下全部滿足才算「前後端對接達到企業級」：

1. Frontend types 100% 由 backend contract 自動產生（或共享 schema package）。
2. PR 中任一 contract 變更都會自動觸發 codegen + contract tests。
3. CI 無法在 schema drift 狀態下合併。
4. `Any`/duck-typing 不進核心層，邊界層有顯式 normalize/validate。
5. 新 agent/新欄位有固定 onboarding checklist（backend schema -> codegen -> UI adapter -> tests -> docs）。

## 7. Direct Answer to Your Question

「後端新增新東西，前端要顯示，現在容易漏掉嗎？」
**是，仍然容易漏，尤其在多人並行、快節奏迭代下。**

原因不是 monorepo 本身，而是目前仍缺：

1. 機器可驗證的共享 contract
2. 自動化 cross-stack gate
3. 強制版本與相容性策略

你已經完成了「程式碼層重構」的 60-70%；要到企業級，下一步是把它升級成「流程與平台層保證」。
