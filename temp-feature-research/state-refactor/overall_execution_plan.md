# 🚀 State Refactor 整體執行計劃

> 依據 [Engineering Charter v3.1](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md)

**目標**: 將系統從「單體大狀態」轉型為「引用傳遞 & 視圖分離」架構

---

## 📊 執行進度總覽

| 階段 | 狀態 | 預計天數 | 負責人 | 完成日期 |
|------|------|----------|--------|----------|
| Phase 0: 基礎建設 | ✅ 完成 | 2 天 | AI | 2026-01-29 |
| Phase 1: Interface Layer | ✅ 完成 | 1 天 | AI | 2026-01-29 |
| Phase 2: Intent (Pilot) | ✅ 完成 | 1 天 | AI | 2026-01-29 |
| Phase 3: 核心 Agents | ✅ 完成 | 3-4 天 | AI | 2026-01-29 |
| Phase 4: 複雜 Agents | ✅ 完成 | 2-3 天 | AI | 2026-01-29 |
| Phase 5: 前端適配 | ✅ 完成 | 2 天 | AI | 2026-01-29 |

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

- [ ] **2.1** Schema 定義
  - 新增 `IntentExtractionPreview` (必需，非可選)

- [ ] **2.2** State 重構 ⚠️ **關鍵修正**
  - `Input`/`Output`: **保持 Pydantic** (邊界驗證)
  - `State`: BaseModel → TypedDict (內部狀態)
  - **移除** `create_pydantic_reducer` (TypedDict 不需要)

- [ ] **2.3** 建立 Mapper
  - 創建 `nodes/intent_extraction/mappers.py`
  - 實作 `summarize_intent_for_preview()`
  - **強制要求**: 編寫單元測試 `test_intent_mapper.py`

- [ ] **2.4** 重構 Adapter
  - 調用 Mapper 生成 Preview
  - 移除 `data` 字段使用

- [ ] **2.5** 更新 Node
  - 移除所有 `AgentOutputArtifact` 創建
  - Node 只更新業務狀態

### ⚠️ 關鍵注意事項

> [!IMPORTANT]
> **Reducer 使用規則**:
> - `create_pydantic_reducer`: **僅用於 Pydantic 模型**
> - TypedDict: 使用原生 dict update (默認覆蓋)
> - 列表: 使用 `add_messages`
> - 字典: 使用 `merge_dict`

> [!WARNING]
> **Input/Output 必須保持 Pydantic**: 這是邊界驗證層，不可改為 TypedDict

### 驗證方式

- [ ] **單元測試** (強制): `uv run pytest tests/test_intent_mapper.py -v`
- [ ] **用戶提供 server log** 確認 Intent Extraction 流程執行無錯誤
- [ ] 從 log 驗證 WebSocket 推送的 `state.update` 包含 `preview` 字段
- [ ] 前端能正確渲染 Intent 結果（如前端未適配可先跳過)

---

## Phase 3: 核心 Agents

> **目的**: 重構數據量大、對系統影響最大的 Agent

### 3.1 Financial News Research

📄 [financial_news_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/financial_news_agent_refactoring_plan.md)

- [x] 選擇中間數據處理策略（方案 C - 節點內清洗）
- [x] State 重構為 TypedDict（保留中間字段以向後兼容）
- [x] 建立 Mapper 層（`mappers.py`）
- [x] **強制要求**: Mapper 單元測試（7 個測試全部通過）
- [x] 更新 Adapter 使用 Preview/Reference 架構
- [ ] **用戶提供 server log** 驗證流程執行

**⚠️ 關鍵注意事項**:
- ✅ 已修正：使用 TypedDict 而非 Pydantic BaseModel
- ✅ 已修正：Input/Output 保持 Pydantic，State 使用 TypedDict
- ✅ 已修正：移除 `create_pydantic_reducer` from TypedDict fields
- ⚠️ 向後兼容：暫時保留中間狀態字段（raw_results, news_items 等），待 Graph 節點重構後移除
- ⚠️ Artifact Store：Adapter 已準備好 Preview 架構，完整 Artifact Store 整合需在 Graph 節點中實現

**狀態**: ✅ 完成（等待用戶驗證）

---

### 3.2 Fundamental Analysis

📄 [fundamental_analysis_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/fundamental_analysis_agent_refactoring_plan.md)

- [x] 財務報表存入 Artifact Store
- [x] State 只存 `valuation_score` + `latest_report_id`
- [x] 建立 `summarize_fundamental_for_preview()`
- [x] **強制要求**: Mapper 單元測試（通過）
- [ ] **用戶提供 server log** 驗證流程執行

**⚠️ 關鍵注意事項**:
- ✅ 已修正：使用 TypedDict 而非 Pydantic BaseModel
- ✅ 已修正：Input/Output 保持 Pydantic，State 使用 TypedDict
- ✅ 已修正：移除 `create_pydantic_reducer` from TypedDict state

**狀態**: ✅ 完成（等待用戶驗證）

---

### 3.3 Technical Analysis

📄 [technical_analysis_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/technical_analysis_agent_refactoring_plan.md)

- [x] 價格序列存入 Artifact Store
- [x] 節點間通過 Artifact ID 傳遞數據（非 `_private`）
- [x] State/Adapter/Mapper 重構
- [x] **強制要求**: Mapper 單元測試 (通過)
- [ ] **用戶提供 server log** 驗證流程執行

**⚠️ 關鍵注意事項**:
- ✅ 已修正：API 設置 `Cache-Control` 避免前端重複下載圖表數據
- ✅ 已修正：Input/Output 保持 Pydantic，State 使用 TypedDict
- ✅ 已修正：移除 `create_pydantic_reducer` from TypedDict state

**狀態**: ✅ 完成 (等待用戶驗證)

---

## Phase 4: 複雜 Agents

> **目的**: 重構有跨 Agent 依賴或複雜邏輯的 Agent

- [x] 移除 `analyst_reports` 數據複製，改用引用
- [x] 辯論歷史存入 Artifact Store
- [x] State/Adapter/Mapper 重構
- [x] **強制要求**: Mapper 單元測試 (通過)
- [ ] **用戶提供 server log** 驗證流程執行

**⚠️ 關鍵注意事項**:
- ✅ 已修正：確保能正確讀取 FA/TA/News 的關鍵指標
- ✅ 已修正：Input/Output 保持 Pydantic，State 使用 TypedDict
- ✅ 已修正：移除 `create_pydantic_reducer` from TypedDict state

**狀態**: ✅ 完成 (等待用戶驗證)

---

### 4.2 Executor / Auditor / Calculator

📄 [executor_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/executor_agent_refactoring_plan.md)
📄 [auditor_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/auditor_agent_refactoring_plan.md)
📄 [calculator_agent_refactoring_plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/calculator_agent_refactoring_plan.md)

- [x] Protocol 修正（移除 `data`）
- [x] 移除 Calculator 重複存儲
- [x] Schema/Mapper/Adapter 重構 (Preview/Reference)
- [x] **強制要求**: Mapper 單元測試 (通過)
- [ ] **用戶提供 server log** 驗證流程執行

**狀態**: ✅ 完成 (等待用戶驗證)

---

## Phase 5: 前端適配

> **目的**: 更新前端以支持 Preview/Reference 雙速渲染

### 待辦事項

- [x] **5.1** 建立 `useArtifact` Hook (已實作)
- [x] **5.2** 更新各 Agent Output 組件 (已完成，並移除 Legacy Fallbacks)
- [x] **5.3** 更新 TypeScript 類型定義 (已移除 `data`, `summary`)
- [x] **5.4** 移除所有 Legacy 向後兼容邏輯 (全局清理完成)

### 參考

約章 §5: [前端工程規範](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md#5-前端工程規範-frontend-standards)

---

## 📚 技術最佳實踐 (Best Practices)

> 基於 Phase 2 (Intent Extraction) 規劃過程中發現的關鍵技術問題，以下規則適用於**所有後續 Agent 重構**。

### 1️⃣ State 類型規則 (Charter §3.1)

| 組件 | 類型 | 原因 |
|------|------|------|
| **Input Schema** | ✅ Pydantic `BaseModel` | 邊界驗證，確保外部輸入合法 |
| **Output Schema** | ✅ Pydantic `BaseModel` | 邊界驗證，確保輸出契約 |
| **Internal State** | ✅ TypedDict | 性能與靈活性，LangGraph 原生支持 |

**錯誤示例** ❌:
```python
# 錯誤：將 Input/Output 改為 TypedDict 會失去運行時驗證
class IntentExtractionInput(TypedDict):  # ❌ 錯誤
    ticker: str | None
```

**正確示例** ✅:
```python
# Input/Output: 保持 Pydantic
class IntentExtractionInput(BaseModel):  # ✅ 正確
    ticker: str | None = None

# Internal State: 使用 TypedDict
class IntentExtractionState(TypedDict):  # ✅ 正確
    ticker: NotRequired[str | None]
```

---

### 2️⃣ Reducer 使用規則

| Reducer | 適用對象 | 說明 |
|---------|----------|------|
| `create_pydantic_reducer` | **僅 Pydantic 模型** | 用於父圖中的 Context (如 `IntentExtractionContext`) |
| 默認覆蓋 (無 Reducer) | TypedDict 簡單字段 | `ticker`, `user_query`, `current_node` 等 |
| `add_messages` | 列表字段 | LangGraph 內建，用於 `messages` |
| `merge_dict` | 字典字段 | 自定義，用於 `internal_progress`, `node_statuses` |

**關鍵錯誤** ❌:
```python
# 錯誤：在 TypedDict 上使用 create_pydantic_reducer
class IntentExtractionState(TypedDict):
    intent_extraction: Annotated[
        dict,  # 這是 dict，不是 Pydantic
        create_pydantic_reducer(IntentExtractionContext)  # ❌ 運行時錯誤
    ]
```

**正確做法** ✅:
```python
# TypedDict State 中，Context 仍是 Pydantic，可以使用 reducer
class IntentExtractionState(TypedDict):
    intent_extraction: Annotated[
        IntentExtractionContext,  # ✅ Pydantic 模型
        create_pydantic_reducer(IntentExtractionContext)
    ]
    ticker: NotRequired[str | None]  # ✅ 默認覆蓋，無需 reducer
```

---

### 3️⃣ Mapper 測試規則 (Charter §4.2)

**強制要求**: 每個 Agent 的 Mapper 必須有單元測試

**原因**:
- Mapper 是純函數，無需 Mock 或 DB
- 5 分鐘即可完成，風險極低
- 比依賴「查看 Server Log」更可靠

**測試模板**:
```python
# tests/test_{agent}_mapper.py
def test_summarize_{agent}_for_preview():
    ctx = {...}  # 模擬 Context
    preview = summarize_{agent}_for_preview(ctx)

    assert preview["key_field"] == expected_value
    assert len(json.dumps(preview)) < 1024  # Preview < 1KB
```

---

### 4️⃣ Preview Schema 定義規則

**強制要求**: 每個 Agent 必須定義 Preview Schema (非可選)

**位置**: `nodes/{agent}/schemas.py`

**範例**:
```python
class {Agent}Preview(BaseModel):
    """Preview data for {Agent} UI (<1KB)"""
    key_field_1: str | None = Field(None, description="...")
    key_field_2: str = Field(..., description="...")
```

**好處**:
- 前端工程師清楚知道 `artifact.preview` 的結構
- 啟用 Mapper 的類型檢查
- 文檔化 UI 契約

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
| 2026-01-29 | Phase 1 完成，Phase 2 開始 | AI |
| 2026-01-29 | Phase 5 完成，整體架構升級及 Legacy 移除工作全部結束 | AI |
