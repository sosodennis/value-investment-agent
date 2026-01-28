# Fundamental Analysis Agent 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**Agent 位置**: `src/workflow/nodes/fundamental_analysis/`

**核心職責**: 從 SEC EDGAR 獲取財務數據，生成財務健康報告，選擇估值模型。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `graph.py` | 16.6KB | Subgraph 構建 + 節點邏輯 |
| `adapter.py` | 2.9KB | 父圖適配器 |
| `extraction.py` | 7.5KB | SEC 數據提取 |
| `factories.py` | 19KB | 財務報表工廠 |
| `financial_models.py` | 9.6KB | 財務模型定義 |
| `subgraph_state.py` | 1.9KB | 子圖狀態 |
| `structures.py` | 2.6KB | 數據結構 |
| `schemas.py` | 645B | Pydantic schemas |

### 違規問題清單

#### ❌ 1. State 類型違規 (約章 §3.1)
- **問題**: `FundamentalAnalysisState` 使用 `Pydantic BaseModel`
- **位置**: [subgraph_state.py](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/fundamental_analysis/subgraph_state.py)

#### ❌ 2. 重型數據存入 State (約章 §3.2, §3.4)
- **問題**: `financial_reports: list[dict]` 直接存入 State，未使用 Artifact Store
- **位置**: [state.py:118-122](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/state.py#L118-L122)
- **影響**: Checkpoint 巨大，違反「重型數據存 DB」原則

#### ❌ 3. Protocol 違規 (約章 §4.1)
- **問題**: 使用 `data` 字段推送完整財務報表
- **位置**: `graph.py` 中的 `financial_health_node` 返回大量數據
- **影響**: WebSocket 推送過大數據，前端卡頓

#### ❌ 4. 缺少 Mapper 層 (約章 §4.2)
- **問題**: 無 `summarize_fundamental_for_preview()` 函數
- **影響**: 視圖轉換邏輯硬編碼在 Node 中

#### ❌ 5. Adapter 透傳 (約章 §4.3)
- **問題**: `output_adapter` 直接透傳 `fundamental_analysis` context
- **位置**: [adapter.py:44-91](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/fundamental_analysis/adapter.py#L44-L91)

---

## ✅ 重構 TODO 清單

### Phase 1: Artifact Store 整合

- [ ] **1.1** 修改 `financial_health_node`：將財務報表存入 Artifact Store
  ```python
  async def financial_health_node(state):
      # 1. Fetch raw data
      reports = await fetch_sec_data(state["ticker"])

      # 2. Clean data
      clean_data = map_sec_to_clean_json(reports)

      # 3. Store in DB (NOT in State)
      artifact_id = await save_artifact(
          data=clean_data,
          type="financial_report",
          key_prefix=f"fa_{state['ticker']}"
      )

      # 4. State only stores reference + key metrics
      return Command(update={
          "fundamental_analysis": {
              "status": "success",
              "valuation_score": calculate_score(clean_data),  # L2: Preview 源
              "latest_report_id": artifact_id                   # L3: Reference
          }
      })
  ```

- [ ] **1.2** 從 `FundamentalAnalysisContext` 移除 `financial_reports` 字段，改用 `latest_report_id`

### Phase 2: State 重構

- [ ] **2.1** 將 `FundamentalAnalysisState` 從 `BaseModel` 轉換為 `TypedDict`

- [ ] **2.2** 精簡 `FundamentalAnalysisContext`：
  ```python
  class FundamentalAnalysisContext(TypedDict):
      status: str | None
      valuation_score: float | None      # L2 源
      model_type: str | None
      latest_report_id: str | None       # L3 指針
      # 移除: financial_reports, extraction_output, audit_output, calculation_output
  ```

### Phase 3: Protocol 重構

- [ ] **3.1** 新增 Preview schema
  ```python
  class FundamentalPreview(BaseModel):
      ticker: str
      status_label: str              # "分析完成", "處理中"
      valuation_score_display: str   # "85.5" or "N/A"
      model_type_display: str        # "SaaS DCF", "Bank DDM"
  ```

### Phase 4: Mapper 建立

- [ ] **4.1** 建立 `mappers.py`
  ```python
  def summarize_fundamental_for_preview(ctx: dict) -> dict:
      score = ctx.get("valuation_score")
      return {
          "ticker": ctx.get("ticker"),
          "status_label": "完成" if ctx.get("status") == "success" else "處理中",
          "valuation_score_display": f"{score:.1f}" if score else "N/A",
          "model_type_display": _format_model_type(ctx.get("model_type"))
      }
  ```

### Phase 5: Adapter 重構

- [ ] **5.1** 修改 `output_adapter`
  ```python
  def output_adapter(sub_output: dict) -> dict:
      ctx = sub_output.get("fundamental_analysis", {})
      report_id = ctx.get("latest_report_id")

      preview = summarize_fundamental_for_preview(ctx)
      reference = None
      if report_id:
          reference = ArtifactReference(
              artifact_id=report_id,
              download_url=f"/api/artifacts/{report_id}",
              type="financial_report"
          )

      return {
          "fundamental_analysis": ctx,
          "artifact": AgentOutputArtifact(
              summary="財務分析完成",
              preview=preview,
              reference=reference
          ),
          ...
      }
  ```

---

## 📁 檔案變更摘要

| 操作 | 檔案 | 說明 |
|------|------|------|
| MODIFY | `graph.py` | 整合 Artifact Store，移除重型數據存儲 |
| MODIFY | `subgraph_state.py` | BaseModel → TypedDict |
| MODIFY | `adapter.py` | 整合 Mapper，生成 Preview/Reference |
| NEW | `mappers.py` | 新增 Preview 映射函數 |
| MODIFY | `schemas.py` | 新增 FundamentalPreview |
| MODIFY | `../state.py` | 精簡 FundamentalAnalysisContext |

---

## ⚠️ 關鍵注意事項

1. **財務報表體積大**：這是最需要 Artifact Store 的 Agent，報表可達數 MB
2. **SEC 數據格式**：`map_sec_to_clean_json` 需負責將 EDGAR 原始數據轉為前端友好的 JSON
3. **父圖依賴**：Debate Agent 需從此 Agent 獲取 `model_type`，確保介面兼容
4. **不改變 factories.py**：財務報表生成邏輯保持不變，僅改變存儲位置
