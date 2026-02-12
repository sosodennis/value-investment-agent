# Frontend Enterprise Contract Hardening Plan (2026-02-12)

Applies to:
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend`
- `/Users/denniswong/Desktop/Project/value-investment-agent/contracts`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core` (API contract source)

## 1. Objective

將目前「generated type + 局部手動轉換」升級為企業級標準：
1. 邊界輸入必須有 runtime validation（不能靠 `as` cast）。
2. UI 層只吃 domain/view model，不直接吃 raw API payload。
3. API contract 破壞可被 CI 機械檢出，避免前後端漏接。

## 2. Current State Snapshot

已完成：
1. OpenAPI 由 backend 導出，frontend 使用 `openapi-typescript` 生成：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/generated/api-contract.ts`
2. protocol 邊界已接 generated type：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/protocol.ts`

主要缺口：
1. `history` / `thread` 回應仍有 `as` cast，缺 runtime decode：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/hooks/useAgent.ts`
2. 邊界轉換規則沒有集中成「可測試 parser 模組（按 agent/domain 拆分）」。
3. UI view-model 仍有 `unknown` 型資料直接流入計算邏輯。

## 3. Target Architecture

資料流必須固定為：

`Generated Contract Types` -> `Boundary Parser (runtime)` -> `Domain Types` -> `View Model Adapter` -> `UI Components`

硬性規則：
1. UI component 不可直接使用 generated types。
2. hook 不可直接 `as ThreadStateResponse` / `as Message[]`。
3. 新增/刪除 API 欄位時，同一 PR 必須更新 parser + tests。
4. Preview parser 採「一個 domain 一個 parser 模組」：
   - `fundamental-preview-parser.ts`
   - `news-preview-parser.ts`
   - `debate-preview-parser.ts`
   - `technical-preview-parser.ts`
5. `preview.ts` 僅保留共用 preview type/type guard，不承載 domain parser 實作。

## 4. Implementation Waves

## Wave 1 (P0): Boundary Runtime Parsing

目標：消除 API 入口 cast，改為 parser。

任務：
1. 在 `protocol.ts` 增加 parser：
   - `parseHistoryResponse(...)`
   - `parseThreadStateResponse(...)`
   - `parseStreamStartResponse(...)`
2. `useAgent.ts` 改為使用 parser，失敗時 fail-fast + 可診斷錯誤。
3. 補充 contract parser tests（vitest）。

驗收：
1. 前端不再有 `as ThreadStateResponse` / `as Message[]`。
2. 測試覆蓋合法與非法 payload。

## Wave 2 (P1): Domain/View Model Hardening

目標：減少 `unknown` 在 UI 計算路徑擴散。

任務：
1. 把 `useFinancialData` 的輸入先經過 adapter 正規化成 typed view model。
2. 把常用 preview 欄位提成顯式 schema guard（ticker, key_metrics, financial_reports, signal_state）。
3. Component props 僅接受 view model，避免重複 defensive check。
4. 將 preview parser 依 domain 拆分成獨立檔案，避免單一檔案膨脹與邊界責任混雜。

驗收：
1. UI 核心渲染路徑無未經正規化的 `unknown`。
2. `any` 為 0；`unknown` 僅存在於 boundary parser。
3. 每個 agent output 都有對應 parser module 與對應測試。

## Wave 3 (P1): Governance and Gates

目標：把流程固化為機械化 gate。

任務：
1. PR checklist 加入 parser/test 必做項。
2. contract 變更必須附 parser diff + 測試證據。
3. CI 保證 codegen drift、typecheck、contract tests 全通過。
4. 新增 lint gate 禁止 runtime 路徑 reintroduce type assertion（`as`）。

驗收：
1. Contract 破壞在 PR 階段可自動攔截。
2. 審計可追溯（文檔 + 測試 + checklist 一致）。
3. runtime 路徑 type assertion 回歸可被機械檢出。

## Wave 4 (P1): Output Adapter/Registry Consolidation

目標：把 output 解析職責從 UI component 移到單一 adapter 邊界層。

任務：
1. 新增 `agentId -> parser` 的 output adapter/registry（typed union view model）。
2. `AgentOutputTab` 成為唯一 output 解析入口（按 agent 產生 view model）。
3. `Fundamental/News/Debate/Technical` output component 改為只接收 parsed preview + reference。
4. `useFinancialData` 改為透過 adapter helper 取 preview，避免直接碰 raw preview。
5. 補齊 adapter 測試（合法/非法 payload）。

驗收：
1. 主要 output component 不再直接 parse `output.preview`。
2. parser/adapter/UI 責任分層清晰，符合 `contract -> parser/adapter -> view model -> UI`。
3. lint/typecheck/test 全部通過。

## Wave 5 (P0): Full Response Standardization

目標：所有前端 response 入口都走 parser-first，消除 runtime 裸 payload 消費。

任務：
1. SSE 事件改為 `parseAgentEvent(...)` 深層解析（含 `state.update`/`interrupt.request` data）。
2. `useArtifact` 改為強制傳入 parser（每個 artifact response 必須經 runtime parse）。
3. 建立 artifact parsers（fundamental/news/debate/technical + generic JSON）。
4. 所有 output component artifact 消費改為 parser-first。
5. 補齊對應測試（SSE parser + artifact parser）。
6. 非 2xx 回應也要 parser-first（`detail: string | ValidationError[]`）。
7. 對 contract 中已存在但暫未接入 UI 的 response（如 `/thread/{thread_id}/agents`）提供獨立 parser 與測試覆蓋。

驗收：
1. `fetch(...).json()` 結果在所有入口都先 parse，再進入狀態或 UI。
2. SSE 協議漂移與 artifact shape 漂移可 fail-fast。
3. lint/typecheck/test 全部通過。

## 5. Breaking Policy (No Compatibility)

本計劃採用「不保留舊版本兼容」：
1. 協議破壞允許，但必須同一 PR 完成 backend + contract + frontend parser + UI 調整。
2. 不允許只改 backend 而延後 frontend。
3. 若改動是 breaking，PR 標題與描述必須明確標示 `BREAKING`.

## 6. Definition of Done

完成條件：
1. `npm run lint`
2. `npm run typecheck`
3. `npm run test -- --run`
4. 無 boundary cast 回歸。
5. 文檔與 PR checklist 已同步更新。
