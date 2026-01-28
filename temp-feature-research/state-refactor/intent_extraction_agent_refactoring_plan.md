# Intent Extraction Agent 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**Agent 位置**: `src/workflow/nodes/intent_extraction/`

**核心職責**: 解析用戶查詢，提取 ticker、公司名稱等意圖信息，進行搜索驗證並解決歧義。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `graph.py` | 1.5KB | Subgraph 構建 |
| `adapter.py` | 1KB | 父圖適配器 |
| `nodes.py` | 11.8KB | 節點邏輯 |
| `schemas.py` | 569B | Pydantic schemas |
| `subgraph_state.py` | 1.6KB | 子圖狀態 |

### 違規問題清單

#### ❌ 1. State 類型違規 (約章 §3.1)
- **問題**: `IntentExtractionState` 使用 `Pydantic BaseModel` 而非 `TypedDict`
- **位置**: [subgraph_state.py](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/intent_extraction/subgraph_state.py)
- **影響**: 違反約章規定的 Root State 必須使用 TypedDict

#### ❌ 2. Protocol 違規 (約章 §4.1)
- **問題**: 使用已廢棄的 `data` 字段，而非 `preview`/`reference`
- **位置**: Node 返回 `AgentOutputArtifact(summary=..., data=...)`
- **影響**: 前端無法區分熱數據與冷數據

#### ❌ 3. 缺少 Mapper 層 (約章 §4.2)
- **問題**: 無 `summarize_intent_for_preview()` 函數
- **位置**: 應建立 `mappers.py`
- **影響**: 視圖邏輯散落在各處，無法統一管理

#### ❌ 4. Adapter 透傳 (約章 §4.3)
- **問題**: `output_adapter` 直接透傳 `intent_extraction` context
- **位置**: [adapter.py:21-32](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/intent_extraction/adapter.py#L21-L32)
- **影響**: 未調用 Mapper 生成標準化 Preview

---

## ✅ 重構 TODO 清單

### Phase 1: State 重構

- [ ] **1.1** 將 `IntentExtractionState` 從 `BaseModel` 轉換為 `TypedDict`
  ```python
  # BEFORE
  class IntentExtractionState(BaseModel):
      ticker: str | None = None
      ...

  # AFTER
  class IntentExtractionState(TypedDict):
      ticker: str | None
      ...
  ```

- [ ] **1.2** 更新 `IntentExtractionInput` 和 `IntentExtractionOutput` 為 `TypedDict`

- [ ] **1.3** 確保狀態只存儲**業務真理**，移除不必要的嵌套

### Phase 2: Protocol 重構

- [ ] **2.1** 修改 schemas.py，新增符合約章的 Preview schema
  ```python
  class IntentExtractionPreview(BaseModel):
      """UI 立即渲染用的輕量數據 (<1KB)"""
      ticker: str | None
      company_name: str | None
      status_label: str  # "解析中", "搜索中", "已確認"
      confidence_display: str  # e.g., "高", "中", "低"
  ```

- [ ] **2.2** 移除所有 Node 中對 `data` 字段的使用

### Phase 3: Mapper 建立

- [ ] **3.1** 建立 `mappers.py` 文件
  ```python
  def summarize_intent_for_preview(ctx: dict) -> dict:
      """將 IntentExtractionContext 映射為 Preview"""
      return {
          "ticker": ctx.get("resolved_ticker"),
          "company_name": ctx.get("company_profile", {}).get("name"),
          "status_label": _get_status_label(ctx.get("status")),
          "confidence_display": _calculate_confidence(ctx)
      }
  ```

### Phase 4: Adapter 重構

- [ ] **4.1** 修改 `output_adapter`：調用 Mapper 生成 Preview
  ```python
  def output_adapter(sub_output: dict) -> dict:
      ctx = sub_output.get("intent_extraction", {})
      preview = summarize_intent_for_preview(ctx)

      return {
          "intent_extraction": ctx,  # 業務真理
          "artifact": AgentOutputArtifact(
              summary="意圖解析完成",
              preview=preview,       # ✅ 新增
              reference=None         # 無重型數據
          ),
          ...
      }
  ```

---

## 📁 檔案變更摘要

| 操作 | 檔案 | 說明 |
|------|------|------|
| MODIFY | `subgraph_state.py` | BaseModel → TypedDict |
| MODIFY | `adapter.py` | 整合 Mapper，移除透傳 |
| NEW | `mappers.py` | 新增 Preview 映射函數 |
| MODIFY | `schemas.py` | 新增 Preview schema |
| MODIFY | `nodes.py` | 移除 `data` 字段使用 |

---

## ⚠️ 注意事項

1. **不改變執行邏輯**: 本重構僅涉及數據結構和介面，不修改 extraction/searching/deciding 等核心邏輯
2. **向後兼容**: 需確保父圖 `AgentState` 的 `intent_extraction` 字段能正確接收更新後的結構
3. **測試覆蓋**: 重構後需驗證整個 intent extraction flow 仍能正常運作
