# 🚀 State Refactor 整體執行計劃

> 依據 [Engineering Charter v3.1](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md)

**目標**: 將系統從「單體大狀態」轉型為「引用傳遞 & 視圖分離」架構

---

## 📊 執行進度總覽

| 階段 | 狀態 | 預計天數 | 負責人 | 完成日期 |
|------|------|----------|--------|----------|
| Phase 0: 基礎建設 | ✅ 完成 | 2 天 | AI | 2026-01-29 |
| Phase 1: Interface Layer | ⬜ 待開始 | 1 天 | | |
| Phase 2: Intent (Pilot) | ⬜ 待開始 | 1 天 | | |
| Phase 3: 核心 Agents | ⬜ 待開始 | 3-4 天 | | |
| Phase 4: 複雜 Agents | ⬜ 待開始 | 2-3 天 | | |
| Phase 5: 前端適配 | ⬜ 待開始 | 2 天 | | |

**狀態圖例**: ⬜ 待開始 | 🔄 進行中 | ✅ 完成 | ⚠️ 阻塞

---

## Phase 0: 基礎建設 (Infrastructure)

> **目的**: 建立 Artifact Store 與相關服務，為後續所有 Agent 重構提供基礎設施

### 待辦事項

- [ ] **0.1** 創建 `artifacts` 資料庫表
  ```sql
  CREATE TABLE artifacts (
      id VARCHAR PRIMARY KEY,
      key VARCHAR,
      thread_id VARCHAR,
      type VARCHAR,
      data JSONB NOT NULL,
      created_at TIMESTAMP DEFAULT NOW()
  );
  CREATE INDEX idx_artifacts_key ON artifacts(key);
  CREATE INDEX idx_artifacts_thread ON artifacts(thread_id);
  ```

- [ ] **0.2** 實作 `src/services/artifact_manager.py`
  - `save_artifact(data, type, key_prefix) -> str`
  - `get_artifact(artifact_id) -> dict | None`

- [ ] **0.3** 新增 API Endpoint `GET /api/artifacts/{artifact_id}`
  - 設置 HTTP 緩存: `Cache-Control: public, max-age=3600`

- [ ] **0.4** 編寫單元測試
  - 驗證能存入 5MB JSON 並正確讀取

### ⚠️ 注意事項

1. **Postgres JSONB 限制**: 單個 JSONB 字段建議 < 255MB，實際應控制在 10MB 以下
2. **Checkpointer 分離**: `artifacts` 表應獨立於 LangGraph 的 `checkpoints` 表

---

## Phase 1: Interface Layer

> **目的**: 修改核心協議，這會導致所有 Agent 編譯失敗（強迫重構）

### 參考文檔

📄 [interface_layer_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/interface_layer_refactoring_plan.md)

### 待辦事項

- [ ] **1.1** 修改 `src/interface/schemas.py`
  - 移除 `data` 字段
  - 新增 `preview: Optional[Dict]`
  - 新增 `reference: Optional[ArtifactReference]`
  - 新增 `ArtifactReference` 類型

- [ ] **1.2** 更新 `src/interface/protocol.py` 文檔說明

- [ ] **1.3** 確認 `src/interface/adapters.py` 傳輸邏輯

### ⚠️ 注意事項

1. **破壞性變更**: 修改後所有使用 `AgentOutputArtifact` 的代碼都會報錯
2. **前端同步**: 需提前通知前端團隊準備適配

### 驗證方式

> ⚠️ **注意**: 由於逐步重構，部分 Agent 可能暫時無法正常運作。每階段完成後，請用戶提供 **server log** 給工程師驗證。

- [ ] 執行 `mypy src/interface/` 無錯誤
- [ ] 所有 Agent 因缺少 `data` 字段而報錯（預期行為）
- [ ] **用戶提供 server log** 確認無其他異常

---

## Phase 2: Intent Extraction (Pilot Agent)

> **目的**: 用最簡單的 Agent 驗證完整流程：TypedDict → Node → Adapter → Preview

### 參考文檔

📄 [intent_extraction_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/intent_extraction_agent_refactoring_plan.md)

### 待辦事項

- [ ] **2.1** State 重構
  - `subgraph_state.py`: BaseModel → TypedDict

- [ ] **2.2** 建立 Mapper
  - 創建 `nodes/intent_extraction/mappers.py`
  - 實作 `summarize_intent_for_preview()`

- [ ] **2.3** 重構 Adapter
  - 調用 Mapper 生成 Preview
  - 移除 `data` 字段使用

- [ ] **2.4** 更新 Node
  - 移除所有 `data=...` 的使用

### 驗證方式

- [ ] **用戶提供 server log** 確認 Intent Extraction 流程執行無錯誤
- [ ] 從 log 驗證 WebSocket 推送的 `state.update` 包含 `preview` 字段
- [ ] 前端能正確渲染 Intent 結果（如前端未適配可先跳過）

---

## Phase 3: 核心 Agents

> **目的**: 重構數據量大、對系統影響最大的 Agent

### 3.1 Financial News Research

📄 [financial_news_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/financial_news_agent_refactoring_plan.md)

- [ ] 選擇中間數據處理策略（方案 A/B/C）
- [ ] 將新聞全文存入 Artifact Store
- [ ] State/Adapter/Mapper 重構
- [ ] **用戶提供 server log** 驗證流程執行

**⚠️ 關鍵**: 不要使用 `_private`（LangGraph 不支持）

---

### 3.2 Fundamental Analysis

📄 [fundamental_analysis_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/fundamental_analysis_agent_refactoring_plan.md)

- [ ] 財務報表存入 Artifact Store
- [ ] State 只存 `valuation_score` + `latest_report_id`
- [ ] 建立 `summarize_fundamental_for_preview()`
- [ ] **用戶提供 server log** 驗證流程執行

**⚠️ 關鍵**: 確保 Preview 包含 5-10 個關鍵財務指標供 UI 摘要顯示

---

### 3.3 Technical Analysis

📄 [technical_analysis_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/technical_analysis_agent_refactoring_plan.md)

- [ ] 價格序列存入 Artifact Store
- [ ] 節點間通過 Artifact ID 傳遞數據（非 `_private`）
- [ ] State/Adapter/Mapper 重構
- [ ] **用戶提供 server log** 驗證流程執行

**⚠️ 關鍵**: API 設置 `Cache-Control` 避免前端重複下載圖表數據

---

## Phase 4: 複雜 Agents

> **目的**: 重構有跨 Agent 依賴或複雜邏輯的 Agent

### 4.1 Debate Agent

📄 [debate_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/debate_agent_refactoring_plan.md)

- [ ] 移除 `analyst_reports` 數據複製，改用引用
- [ ] 辯論歷史存入 Artifact Store
- [ ] State/Adapter/Mapper 重構
- [ ] **用戶提供 server log** 驗證流程執行

**⚠️ 關鍵**: 確保能正確讀取 FA/TA/News 的關鍵指標

---

### 4.2 Executor / Auditor / Calculator

📄 [executor_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/executor_agent_refactoring_plan.md)
📄 [auditor_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/auditor_agent_refactoring_plan.md)
📄 [calculator_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/calculator_agent_refactoring_plan.md)

- [ ] Protocol 修正（移除 `data`）
- [ ] 移除 Calculator 重複存儲
- [ ] **用戶提供 server log** 驗證流程執行

**優先級較低**: 這些節點的 State 體積較小

---

## Phase 5: 前端適配

> **目的**: 更新前端以支持 Preview/Reference 雙速渲染

### 待辦事項

- [ ] **5.1** 建立 `useArtifact` Hook
  ```typescript
  export function useArtifact<T>(artifactId?: string) {
    return useSWR<T>(
      artifactId ? `/api/artifacts/${artifactId}` : null,
      fetcher
    );
  }
  ```

- [ ] **5.2** 更新各 Agent Output 組件
  - 立即渲染 `preview`
  - 異步加載 `reference`

- [ ] **5.3** 更新 TypeScript 類型定義
  - `AgentOutputArtifact` 類型

### 參考

約章 §5: [前端工程規範](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md#5-前端工程規範-frontend-standards)

---

## 🎯 風險管理

| 風險 | 機率 | 影響 | 緩解措施 |
|------|------|------|----------|
| Interface 變更導致前後端不同步 | 高 | 高 | 統一上線時間，準備 Rollback |
| Artifact Store 性能問題 | 中 | 中 | 提前做 5MB 壓力測試 |
| LangGraph `_private` 誤用 | 已發生 | 高 | 已在計劃中修正 |

---

## 📞 Escalation Path

- **技術阻塞**: @TechLead
- **進度延遲**: @ProjectManager
- **前端協調**: @FrontendLead

---

## 變更日誌

| 日期 | 變更內容 | 作者 |
|------|----------|------|
| 2026-01-29 | 初始版本 | AI |
| | | |
