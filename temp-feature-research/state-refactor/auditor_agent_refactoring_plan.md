# Auditor Agent 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**Agent 位置**: `src/workflow/nodes/auditor/`

**核心職責**: 驗證 Executor 提取的估值參數，執行業務規則審計。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `node.py` | 3.2KB | 主節點邏輯 |
| `schemas.py` | 386B | Pydantic schemas |

### 違規問題清單

#### ❌ 1. Protocol 違規 (約章 §4.1)
- **問題**: 使用已廢棄的 `data` 字段
- **位置**: [node.py:63-68](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/auditor/node.py#L63-L68)
  ```python
  "artifact": AgentOutputArtifact(
      summary=f"Audit completed...",
      data=AuditorSuccess(passed=...).model_dump(),  # ❌ 違規
  )
  ```

#### ❌ 2. 缺少 Mapper 層 (約章 §4.2)
- **問題**: 無獨立的視圖映射函數

#### ❌ 3. State 直接操作 (約章 §4.3)
- **問題**: 節點直接調用 `state.model_dump()` 和 `state.fundamental_analysis.extraction_output`
- **位置**: [node.py:26-34](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/auditor/node.py#L26-L34)

---

## ✅ 重構 TODO 清單

### Phase 1: Protocol 重構

- [ ] **1.1** 移除 `data` 字段，改用 `preview`
  ```python
  return Command(
      update={
          "fundamental_analysis": {
              "audit_output": AuditOutput(...)
          },
          "artifact": AgentOutputArtifact(
              summary=f"Audit: {'PASSED' if result.passed else 'FAILED'}",
              preview=AuditorPreview(
                  passed=result.passed,
                  finding_count=len(result.messages),
                  status="completed"
              ).model_dump(),
              reference=None
          ),
          ...
      }
  )
  ```

### Phase 2: Schema 重構

- [ ] **2.1** 新增 Preview schema
  ```python
  class AuditorPreview(BaseModel):
      """UI 渲染用的輕量摘要"""
      passed: bool             # 審計是否通過
      finding_count: int       # 發現問題數量
      status: str              # "completed", "failed"
  ```

### Phase 3: Mapper 建立（可選）

- [ ] **3.1** 建立 `mappers.py`
  ```python
  def summarize_audit_for_preview(audit_output: AuditOutput) -> dict:
      return {
          "passed": audit_output.passed,
          "finding_count": len(audit_output.messages),
          "status": "completed"
      }
  ```

---

## 📁 檔案變更摘要

| 操作 | 檔案 | 說明 |
|------|------|------|
| MODIFY | `node.py` | 移除 `data`，使用 `preview` |
| MODIFY | `schemas.py` | 新增 AuditorPreview |
| NEW (可選) | `mappers.py` | Preview 映射函數 |

---

## ⚠️ 關鍵注意事項

1. **簡單節點**：Auditor 是較簡單的驗證節點
2. **依賴關係**：依賴 Executor 的 `extraction_output`
3. **低優先級**：相比其他 Agent，優先級較低
4. **整合考量**：可考慮將 Auditor 與 Executor 整合為一個 Validation Agent
