# Calculator Agent 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**Agent 位置**: `src/workflow/nodes/calculator/`

**核心職責**: 執行確定性估值計算（DCF、DDM 等），生成最終估值結果。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `node.py` | 2.7KB | 主節點邏輯 |
| `schemas.py` | 422B | Pydantic schemas |

### 違規問題清單

#### ❌ 1. Protocol 違規 (約章 §4.1)
- **問題**: 使用已廢棄的 `data` 字段
- **位置**: [node.py:47-50](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/calculator/node.py#L47-L50)
  ```python
  artifact = AgentOutputArtifact(
      summary=f"Valuation Complete. Model: {model_type}",
      data=CalculatorSuccess(metrics=result, model_type=model_type).model_dump(),  # ❌ 違規
  )
  ```

#### ❌ 2. 重複 Artifact 存儲
- **問題**: 同一個 artifact 存入兩處（頂層和 `fundamental_analysis` 內）
- **位置**: [node.py:53-62](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/calculator/node.py#L53-L62)
  ```python
  return Command(
      update={
          "fundamental_analysis": {
              "calculation_output": ...,
              "artifact": artifact,  # 重複1
          },
          "artifact": artifact,      # 重複2
          ...
      }
  )
  ```

#### ❌ 3. 缺少 Mapper 層 (約章 §4.2)
- **問題**: 無獨立的視圖映射函數

---

## ✅ 重構 TODO 清單

### Phase 1: Protocol 重構

- [ ] **1.1** 移除 `data` 字段，改用 `preview`，並考慮估值結果是否需要 Artifact Store
  ```python
  async def calculation_node(state):
      result = calc_func(params_obj)

      # 如果估值結果很大（含詳細現金流表），存入 Artifact Store
      if len(str(result)) > 1024:
          detail_id = await save_artifact(
              data={"full_valuation": result},
              type="valuation_result",
              key_prefix=f"calc_{model_type}_{state['ticker']}"
          )
      else:
          detail_id = None

      return Command(
          update={
              "fundamental_analysis": {
                  "calculation_output": CalculationOutput(
                      intrinsic_value=result.get("intrinsic_value"),
                      upside_potential=result.get("upside_potential")
                  )
              },
              "artifact": AgentOutputArtifact(
                  summary=f"Valuation: {model_type.upper()}",
                  preview=CalculatorPreview(
                      model_type=model_type,
                      intrinsic_value_display=f"${result.get('intrinsic_value', 0):.2f}",
                      upside_display=f"{result.get('upside_potential', 0):.1%}"
                  ).model_dump(),
                  reference=ArtifactReference(...) if detail_id else None
              ),
              ...
          }
      )
  ```

### Phase 2: 移除重複存儲

- [ ] **2.1** 只在頂層 `artifact` 存儲輸出，移除 `fundamental_analysis.artifact`
  ```python
  return Command(
      update={
          "fundamental_analysis": {
              "calculation_output": CalculationOutput(...)
              # 移除: "artifact": artifact
          },
          "artifact": AgentOutputArtifact(...),  # 只在這裡
          ...
      }
  )
  ```

### Phase 3: Schema 重構

- [ ] **3.1** 新增 Preview schema
  ```python
  class CalculatorPreview(BaseModel):
      """UI 渲染用的輕量摘要"""
      model_type: str                 # "saas", "bank"
      intrinsic_value_display: str    # "$245.50"
      upside_display: str             # "+15.3%"
      confidence_display: str         # "高", "中", "低"
  ```

### Phase 4: Mapper 建立（可選）

- [ ] **4.1** 建立 `mappers.py`
  ```python
  def summarize_calculation_for_preview(result: dict, model_type: str) -> dict:
      iv = result.get("intrinsic_value", 0)
      upside = result.get("upside_potential", 0)
      return {
          "model_type": model_type,
          "intrinsic_value_display": f"${iv:.2f}",
          "upside_display": f"{upside:+.1%}",
          "confidence_display": _assess_confidence(result)
      }
  ```

---

## 📁 檔案變更摘要

| 操作 | 檔案 | 說明 |
|------|------|------|
| MODIFY | `node.py` | 移除 `data`，使用 `preview`，移除重複存儲 |
| MODIFY | `schemas.py` | 新增 CalculatorPreview |
| NEW (可選) | `mappers.py` | Preview 映射函數 |

---

## ⚠️ 關鍵注意事項

1. **估值結果體積**：完整 DCF 模型可能包含 5-10 年現金流預測，可能需要 Artifact Store
2. **重複存儲**：當前代碼的重複存儲應移除
3. **最終節點**：Calculator 是 Fundamental Analysis 流程的最後一步
4. **低優先級**：相比其他 Agent，此節點的 State 體積較小
