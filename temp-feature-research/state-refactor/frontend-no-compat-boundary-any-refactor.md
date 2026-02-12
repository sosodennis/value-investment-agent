# Frontend Refactor Plan (No-Compatibility + No-Any)

**Date**: 2026-02-12
**Scope**: `frontend/`
**Status**: Planning (implementation deferred)

## 1. 背景與結論

後端已經收斂為 canonical artifact payload（`summary + preview + reference`），但前端仍存在大量相容分支與 `any`，導致每個元件自己猜資料形狀。

這和後端先前 `hasattr(...)` 問題是同一類設計債：
- 沒有單一前端邊界 contract
- 兼容舊格式滲透到 UI 層
- 型別邊界過寬，迫使到處做 defensive fallback

## 2. 本次重構原則

1. **No Compatibility**: 前端只接受 canonical payload，不再兼容舊 shape。
2. **No Any**: 邊界內外都不得使用 `any`（含 `Record<string, any>`、`as any`、索引簽名 `: any`）。
3. **Single Normalization Point**: 所有 JSON 只在 API 邊界做一次 normalization/validation。
4. **Dumb UI Components**: UI 元件只吃已型別化資料，不再 shape-guessing。

## 3. 目前已確認的問題（證據）

### 3.1 協議/資料型別過寬
- `frontend/src/types/protocol.ts:8`
- `frontend/src/types/protocol.ts:33`
- `frontend/src/types/protocol.ts:54`
- `frontend/src/types/agents/index.ts:17`

### 3.2 輸出元件重複 fallback 鏈（核心 smell）
- `frontend/src/components/agent-outputs/FundamentalAnalysisOutput.tsx:21`
- `frontend/src/components/agent-outputs/NewsResearchOutput.tsx:22`
- `frontend/src/components/agent-outputs/DebateOutput.tsx:17`
- `frontend/src/components/agent-outputs/TechnicalAnalysisOutput.tsx:169`

典型模式：
```ts
const reference = (output as any)?.reference || (output as any)?.artifact?.reference;
const preview = (output as any)?.preview || (output as any)?.artifact?.preview || (output as any);
```

### 3.3 Reducer 承擔資料修補與 schema 合成
- `frontend/src/hooks/useAgentReducer.ts:64`
- `frontend/src/hooks/useAgentReducer.ts:131`

### 3.4 Legacy mapping 還在 runtime
- `frontend/src/hooks/useAgent.ts:151`

### 3.5 `any` 密度（掃描基線）
- `frontend/src` 目前約 70 個 `any` 相關用法（`as any` / `: any` / `Record<string, any>` 等）。

## 4. Canonical Contract（前端唯一可接受形狀）

以後端現況為準（`state.update.data` 直接是 artifact payload）：

```ts
type AgentOutputArtifact = {
  summary: string;
  preview: PreviewPayload | null;
  reference: ArtifactReference | null;
  error_logs?: AgentErrorLog[];
};
```

重點：
- 不再接受 `output.artifact.preview`。
- 不再接受 `output` 本身即 preview 的隱式格式。
- 不再做 `ticker_selection -> interrupt_ticker` 類 runtime 舊格式轉換。

## 5. 邊界定義（你之前問的「邊界」）

### Boundary A: Network -> Protocol
位置：`useAgent.ts` / event parser / history loader
責任：`unknown` JSON 進來後，轉成 `AgentEvent` discriminated union。
禁止：在此邊界之外處理 JSON 不確定性。

### Boundary B: Protocol -> Store
位置：`useAgentReducer.ts`
責任：只存 normalized state（`agents[id].output` 永遠是 canonical artifact）。
禁止：在 reducer 內做 legacy schema 拼裝/猜測。

### Boundary C: Store -> View
位置：`agent-outputs/*` + `useFinancialData.ts`
責任：只做 domain-level display mapping（例如數值格式化），不做 shape fallback。
禁止：`output?.artifact?.preview || output?.preview || output` 這類鏈。

## 6. 重構方案（分階段）

## Phase 1: 型別收斂（先建地基）
1. 重寫 `frontend/src/types/protocol.ts`
- `AgentEvent` 改 discriminated union（依 `type` 分 data 結構）。
- `StateUpdateData` 改成 canonical `AgentOutputArtifact`。

2. 重寫 `frontend/src/types/agents/index.ts`
- `StandardAgentOutput` 移除 `preview?: any`，改為 typed preview union。

3. 建立 `frontend/src/types/preview.ts`
- 定義 `IntentPreview | FundamentalPreview | NewsPreview | TechnicalPreview | DebatePreview`。

## Phase 2: 資料流收斂（移除 compatibility）
1. `useAgentReducer.ts`
- `AgentData.output` 改為 `AgentOutputArtifact | null`。
- 移除 `stateData?: any`、`interrupt: any`、`c: any`。
- 移除 legacy interrupt schema 修補分支，改由後端保證 schema。

2. `useAgent.ts`
- `submitCommand(payload: any)` 改為 union payload。
- 刪除 `msg.type as any` 的歷史轉換。

## Phase 3: UI 元件去 fallback + 去 any
1. 四個主要輸出元件改成只讀 canonical：
- `FundamentalAnalysisOutput.tsx`
- `NewsResearchOutput.tsx`
- `DebateOutput.tsx`
- `TechnicalAnalysisOutput.tsx`

2. `useFinancialData.ts` 改為 typed selector
- 只讀 `output.preview`（必要時用 type guard 區分 preview variant）。

3. 清理廣泛 `any`
- `DynamicInterruptForm.tsx`
- `AgentDetailPanel.tsx`
- `AgentOutputTab.tsx`
- `agent-outputs/index.ts`
- `AINewsSummary.tsx`

## 7. Before / After（示意）

### Before
```ts
const reference = (output as any)?.reference || (output as any)?.artifact?.reference;
const preview = (output as any)?.preview || (output as any)?.artifact?.preview || (output as any);
```

### After
```ts
const reference = output?.reference ?? null;
const preview = output?.preview ?? null;
```

### Before
```ts
export interface AgentData {
  status: AgentStatus;
  output: any | null;
}
```

### After
```ts
export interface AgentData {
  status: AgentStatus;
  output: AgentOutputArtifact | null;
}
```

## 8. 驗收標準（Definition of Done）

1. `rg -n "\bany\b|as any|Record<string,\s*any>|\[key:\s*string\]:\s*any" frontend/src` 無結果。
2. `rg -n "\.artifact\?\.preview|\.artifact\?\.reference" frontend/src` 無結果。
3. `npm run lint` 通過。
4. `npm run test` 通過（至少現有測試全綠）。
5. 主要輸出頁在「preview only / reference loading / full artifact」三態可正常渲染。

## 9. 非目標（本輪不做）

1. 不調整 UI 視覺設計語言。
2. 不改後端業務邏輯。
3. 不做舊資料格式兼容。
4. SSE parser/reconnect 強化可獨立成下一輪（本輪以型別與邊界收斂為主）。

## 10. 風險與注意事項

1. 若歷史資料仍是舊 shape，No-Compatibility 會直接暴露資料不一致（預期行為）。
2. 若後端某節點回傳未標準化 payload，前端應 fail-fast 並顯示可追蹤錯誤。
3. Phase 2 前先完成型別收斂，避免 UI 改動期間錯誤放大。
