# Interface Layer 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**位置**: `src/interface/`

**核心職責**: 定義前後端通信協議，橋接 LangGraph State 與前端 UI。

> [!IMPORTANT]
> **此為所有 Agent 重構的前置依賴。** `AgentOutputArtifact` 是共享核心 schema，必須優先完成此層重構。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `schemas.py` | 592B | `AgentOutputArtifact` 定義 |
| `protocol.py` | 1.9KB | `AgentEvent` 事件協議 |
| `adapters.py` | 6.7KB | LangGraph → AgentEvent 轉換 |
| `mappers.py` | 2.9KB | State → UI Payload 映射 |

---

## ❌ 違規問題清單

### 1. `schemas.py` - 核心違規 (約章 §4.1)

**現狀**:
```python
class AgentOutputArtifact(BaseModel):
    summary: str = ...
    data: dict[str, Any] = ...  # ⛔️ 已廢棄的 data 字段
```

**問題**:
- 使用 `data` 字段直接推送完整數據
- 缺少 `preview` (L2 熱數據) 字段
- 缺少 `reference` (L3 冷數據指針) 字段
- 缺少 `ArtifactReference` 類型定義

---

### 2. `protocol.py` - 部分違規

**現狀**:
```python
class AgentEvent(BaseModel):
    data: dict[str, Any] = ...  # Event payload
```

**問題**:
- `AgentEvent.data` 會透傳 `AgentOutputArtifact` 的內容
- 當 `schemas.py` 遷移後，此處需配合調整文檔說明

---

### 3. `mappers.py` - 架構不符 (約章 §4.2)

**現狀**:
- `NodeOutputMapper` 僅負責提取 `artifact`
- 缺少約章規定的 `summarize_..._for_preview()` 函數系列

**問題**:
- 約章要求 Mapper 負責「State → Preview」的轉換邏輯
- 當前架構將此職責分散到各 Agent 的 Adapter 中

---

### 4. `adapters.py` - 依賴更新

**現狀**:
- `adapt_langgraph_event` 正確地使用 `NodeOutputMapper.transform`
- 無直接違規，但依賴 `schemas.py` 的結構

**問題**:
- 當 `AgentOutputArtifact` 遷移到 `preview`/`reference` 後，需確認傳輸邏輯

---

## ✅ 重構 TODO 清單

### Phase 1: Schema 重構 (最高優先級)

- [ ] **1.1** 新增 `ArtifactReference` 類型
  ```python
  # schemas.py
  class ArtifactReference(BaseModel):
      """L3 冷數據指針"""
      artifact_id: str
      download_url: str  # e.g., "/api/v1/artifacts/{id}"
      type: str          # e.g., "financial_report", "news_analysis"
  ```

- [ ] **1.2** 重構 `AgentOutputArtifact`
  ```python
  class AgentOutputArtifact(BaseModel):
      """標準化 Agent 輸出容器"""
      summary: str = Field(..., description="L1: 消息氣泡文本 (<500 chars)")

      # L2: Preview (熱數據) - UI 立即渲染用 (<1KB)
      preview: Optional[Dict[str, Any]] = Field(
          default=None,
          description="UI 關鍵渲染數據，由 Mapper 從 State 生成"
      )

      # L3: Reference (冷數據) - UI 異步加載用
      reference: Optional[ArtifactReference] = Field(
          default=None,
          description="指向 Artifact Store 的指針"
      )

      # ⛔️ DEPRECATED: 移除 data 字段
  ```

- [ ] **1.3** 新增 Agent 專用 Preview Schema（可選，集中管理方式）
  ```python
  # schemas.py (或各 Agent 的 schemas.py)
  class FundamentalPreview(BaseModel):
      ticker: str
      status_label: str
      valuation_score_display: str

  class TechnicalPreview(BaseModel):
      signal_display: str
      z_score_display: str
      ...
  ```

### Phase 2: Mapper 架構決策

- [ ] **2.1** 決定 Mapper 放置策略：

  **選項 A: 集中式** (在 `interface/mappers.py`)
  ```python
  # mappers.py
  def summarize_fundamental_for_preview(ctx: dict) -> dict: ...
  def summarize_ta_for_preview(ctx: dict) -> dict: ...
  def summarize_news_for_preview(ctx: dict) -> dict: ...
  ```

  **選項 B: 分散式** (在各 Agent 目錄下)
  ```
  nodes/fundamental_analysis/mappers.py
  nodes/technical_analysis/mappers.py
  nodes/financial_news_research/mappers.py
  ```

  > **建議**: 選項 B (分散式)，讓 Agent 模組更內聚，便於維護。

- [ ] **2.2** 更新 `NodeOutputMapper` 文檔，說明其與 Agent Mapper 的關係

### Phase 3: Adapter 配合更新

- [ ] **3.1** 確認 `adapt_langgraph_event` 的 `state.update` 事件傳輸邏輯
  ```python
  # adapters.py
  # 確保 ui_payload 現在包含 {summary, preview, reference} 而非 {summary, data}
  ui_payload = NodeOutputMapper.transform(agent_id, output)
  ```

- [ ] **3.2** 更新 `create_interrupt_event` 以符合新協議（如需要）

### Phase 4: Protocol 更新

- [ ] **4.1** 更新 `AgentEvent` 的 `data` 字段文檔說明
  ```python
  data: dict[str, Any] = Field(
      default_factory=dict,
      description="Payload: 對於 state.update 類型，包含 {summary, preview, reference}"
  )
  ```

---

## 📁 檔案變更摘要

| 操作 | 檔案 | 說明 |
|------|------|------|
| MODIFY | `schemas.py` | 移除 `data`，新增 `preview`/`reference`/`ArtifactReference` |
| MODIFY | `mappers.py` | 更新文檔說明 Mapper 架構 |
| MODIFY | `adapters.py` | 配合 schema 調整傳輸邏輯 |
| MODIFY | `protocol.py` | 更新 `AgentEvent.data` 文檔說明 |

---

## 🔗 依賴關係

```
interface/schemas.py (AgentOutputArtifact)
    ↓ 被使用於
├── workflow/state.py (Context 類型)
├── workflow/nodes/*/node.py (Node 返回值)
├── workflow/nodes/*/adapter.py (Output Adapter)
└── interface/adapters.py (Event 轉換)
```

> [!CAUTION]
> **破壞性變更**：移除 `data` 字段後，所有使用 `AgentOutputArtifact` 的代碼都需要更新。建議先完成此層重構，再逐一更新各 Agent。

---

## ⚠️ 關鍵注意事項

1. **前置依賴**：此為所有 Agent 重構的前置條件
2. **破壞性變更**：`data` → `preview`/`reference` 需要同時更新前端
3. **Mapper 策略**：建議採用分散式，讓各 Agent 自行管理 Preview 邏輯
4. **版本控制**：考慮在遷移期間暫時保留 `data` 字段並標記 `deprecated`
