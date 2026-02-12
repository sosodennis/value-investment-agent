# Monorepo Contract Upgrade Progress
Date: 2026-02-12

## Status Summary

Overall: `IN_PROGRESS`
Current phase: `Phase 4 - Monorepo CI Baseline`

## Progress Log

### 2026-02-12

Completed:
1. 建立升級計劃文檔：`/Users/denniswong/Desktop/Project/value-investment-agent/docs/monorepo-contract-upgrade-plan.md`
2. 建立本 progress 文檔
3. Backend 關鍵端點加入 `response_model` 並加強型別 normalize：
   - `/history/{thread_id}`
   - `/thread/{thread_id}`
   - `/thread/{thread_id}/agents`
   - `/stream`
4. `/thread/{thread_id}` 新增 `last_seq_id` 回傳
5. Backend `interrupt` schema 對齊 `oneOf(const/title)`（移除 `enumNames`）
6. Frontend 新增 `typecheck` script（`tsc --noEmit`）
7. 新增 monorepo CI workflow：
   - `/Users/denniswong/Desktop/Project/value-investment-agent/.github/workflows/monorepo-contract-gates.yml`
8. PR template 補上 frontend/typecheck/contract gate checklist

In Progress:
1. 收尾：更新 phase 狀態、準備下一輪（OpenAPI codegen / event versioning）

Pending:
1. OpenAPI -> frontend types 自動 codegen
2. SSE protocol versioning
3. Consumer-driven contract fixtures pipeline

Validation results:
1. Backend targeted ruff passed:
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run ruff check api/server.py src/interface/adapters.py src/workflow/interrupts.py tests/test_protocol.py tests/test_interrupts.py`
2. Backend contract tests passed:
   - `UV_CACHE_DIR=/tmp/.uv-cache uv run pytest tests/test_protocol.py tests/test_mappers.py tests/test_news_mapper.py tests/test_debate_mapper.py tests/test_interrupts.py -q`
   - Result: `25 passed`
3. Frontend checks passed:
   - `npm run lint`
   - `npm run typecheck`
   - `npm run test -- --run`

## Checklist by Phase

Phase 0:
1. [x] 計劃文檔建立
2. [x] progress 文檔建立

Phase 1:
1. [x] `/history/{thread_id}` response_model
2. [x] `/thread/{thread_id}` response_model
3. [x] `/thread/{thread_id}/agents` response_model
4. [x] `/stream` response_model
5. [x] `last_seq_id` 回傳與驗證

Phase 2:
1. [x] Backend `interrupt` schema 統一 `oneOf`
2. [x] 相關測試更新

Phase 3:
1. [x] Frontend `typecheck` script
2. [x] 前端 lint/typecheck/test 全通過

Phase 4:
1. [x] CI workflow 建立
2. [x] backend/frontend/contract gate 規則落地（PR 執行）

## Risks / Notes

1. `response_model` 會讓歷史資料或異常 payload 提前暴露為 500；需要同步補 normalize 邏輯。
2. Next.js build 在離線環境會因 Google Fonts 失敗，與 contract 升級無關。
3. `uv run ruff check src api tests` 目前會在既有未改動檔案（如 `tests/calculations/test_core.py`）報 import-sort 歷史問題；本輪已針對改動範圍做通過驗證。
