# Frontend Enterprise Contract Hardening Progress (2026-02-12)

Related plan:
- `/Users/denniswong/Desktop/Project/value-investment-agent/docs/frontend-enterprise-contract-hardening-plan-2026-02-12.md`

## Status Overview

- Overall: `IN PROGRESS`
- Current wave: `Wave 3 (P1) Governance and Gates`

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

## Risks / Notes

1. 目前已採 zero-compat parser；後端只要 payload 漂移，前端會直接 fail-fast。
2. 規則目前鎖定 runtime 關鍵路徑；若未來新增 runtime folder，需同步擴充 ESLint `files` 範圍。
