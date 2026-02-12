# Monorepo Contract Upgrade Plan
Date: 2026-02-12
Owner: Platform / Backend / Frontend shared

## Goal

把目前「依靠人工同步前後端」升級為「以 contract 為中心、可被 CI 機械驗證」的開發模式，降低 fullstack 功能上線時的漏接風險。

## Scope

In scope (本輪實作):
1. Backend API `response_model` contract 強化（關鍵端點）
2. `interrupt` schema 統一（`oneOf`）
3. Frontend 新增 `typecheck` gate
4. Monorepo CI 基礎 gate（backend/frontend/contract policy）
5. Progress 文檔與可追溯變更記錄

Out of scope (下一輪):
1. OpenAPI -> frontend type codegen 全自動化
2. SSE event schema 的版本化 (`protocol_version`)
3. Consumer-driven fixtures pipeline

## Phases

## Phase 0: Planning and Traceability

Tasks:
1. 建立計劃文檔與 progress 文檔
2. 定義本輪 DoD 與驗證命令

Exit Criteria:
1. 計劃已落檔
2. progress 模板可持續更新

## Phase 1: Backend Contract Hardening

Tasks:
1. 為關鍵端點加入 `response_model`：
   - `GET /history/{thread_id}`
   - `GET /thread/{thread_id}`
   - `GET /thread/{thread_id}/agents`
   - `POST /stream`
2. 加入 `last_seq_id` 回傳
3. 對 `node_statuses` 做顯式 normalize/validate（`dict[str, str]`）

Exit Criteria:
1. 關鍵端點有明確 response schema
2. Frontend history rehydrate 可拿到 `last_seq_id`

## Phase 2: Interrupt Schema Alignment

Tasks:
1. Backend `ticker_selection` schema 移除 `enumNames`
2. 統一輸出 `enum + oneOf(const/title)` 結構
3. 補測試覆蓋 schema shape

Exit Criteria:
1. Backend/frontend 對 interrupt option label 的來源一致

## Phase 3: Frontend Type Gates

Tasks:
1. 新增 `npm run typecheck` (`tsc --noEmit`)
2. 將 typecheck 納入標準驗證流程（本地 + CI）

Exit Criteria:
1. 型別錯誤在 build 前被攔截

## Phase 4: Monorepo CI Baseline

Tasks:
1. 新增 GitHub Actions workflow：
   - backend lint + contract tests
   - frontend lint + typecheck + tests
2. 新增 contract policy 檢查（例如禁止 `enumNames` 回流）

Exit Criteria:
1. PR 可自動檢出跨端 contract 破壞

## Definition of Done (This Iteration)

1. 計劃/progress 文檔已建立並有執行記錄
2. Backend 關鍵 API 加上 response_model 並通過測試
3. Interrupt schema 完成 oneOf 對齊
4. Frontend 有獨立 typecheck script 並通過
5. CI workflow 已落地（可在 PR 上執行）

## Validation Commands

Backend:
```bash
cd finance-agent-core
uv run ruff check src api tests
uv run pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py tests/test_interrupts.py -q
```

Frontend:
```bash
cd frontend
npm run lint
npx tsc --noEmit
npm run test -- --run
```
