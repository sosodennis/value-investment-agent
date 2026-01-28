# Executor Agent 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**Agent 位置**: `src/workflow/nodes/executor/`

**核心職責**: 根據選定的估值模型類型，提取估值所需的參數數據（目前為 Mock 數據）。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `node.py` | 2.6KB | 主節點邏輯 |
| `prompts.py` | 2.2KB | LLM 提示詞 (未使用) |
| `schemas.py` | 418B | Pydantic schemas |
| `tools.py` | 1.7KB | Mock 數據生成 |

### 違規問題清單

#### ❌ 1. Protocol 違規 (約章 §4.1)
- **問題**: 使用已廢棄的 `data` 字段
- **位置**: [node.py:53-58](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/executor/node.py#L53-L58)
  ```python
  "artifact": AgentOutputArtifact(
      summary=f"Extracted parameters for {model_type} analysis.",
      data=ExecutorSuccess(params=...).model_dump(),  # ❌ 違規
  )
  ```

#### ❌ 2. 缺少 Mapper 層 (約章 §4.2)
- **問題**: 無獨立的視圖映射函數

#### ❌ 3. 參數直接存入頂層 (約章 §3.1)
- **問題**: `extraction_output` 包含完整參數字典，應精簡
- **位置**: [node.py:52](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/executor/node.py#L52)

---

## ✅ 重構 TODO 清單

### Phase 1: Protocol 重構

- [ ] **1.1** 移除 `data` 字段，改用 `preview`
  ```python
  # node.py
  return Command(
      update={
          "fundamental_analysis": {"extraction_output": output},
          "artifact": AgentOutputArtifact(
              summary=f"Extracted parameters for {model_type} analysis.",
              preview=ExecutorPreview(
                  model_type=model_type,
                  param_count=len(output.params),
                  status="extracted"
              ).model_dump(),
              reference=None  # 無重型數據
          ),
          ...
      }
  )
  ```

### Phase 2: Schema 重構

- [ ] **2.1** 新增 Preview schema
  ```python
  # schemas.py
  class ExecutorPreview(BaseModel):
      """UI 渲染用的輕量摘要"""
      model_type: str          # "saas", "bank"
      param_count: int         # 提取的參數數量
      status: str              # "extracted", "failed"
  ```

### Phase 3: Mapper 建立

- [ ] **3.1** 建立 `mappers.py`（可選，因邏輯簡單）
  ```python
  def summarize_executor_for_preview(extraction_output: dict, model_type: str) -> dict:
      return {
          "model_type": model_type,
          "param_count": len(extraction_output.get("params", {})),
          "status": "extracted"
      }
  ```

---

## 📁 檔案變更摘要

| 操作 | 檔案 | 說明 |
|------|------|------|
| MODIFY | `node.py` | 移除 `data`，使用 `preview` |
| MODIFY | `schemas.py` | 新增 ExecutorPreview |
| NEW (可選) | `mappers.py` | Preview 映射函數 |

---

## ⚠️ 關鍵注意事項

1. **簡單節點**：Executor 是較簡單的節點，主要問題是 Protocol 違規
2. **Mock 數據**：目前使用 Mock 數據，未來可能需要整合真實數據源
3. **依賴關係**：Auditor 和 Calculator 依賴 `extraction_output`
4. **低優先級**：相比其他 Agent，此節點的 State 體積較小，優先級較低
