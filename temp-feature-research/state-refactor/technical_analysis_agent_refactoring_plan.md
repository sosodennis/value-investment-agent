# Technical Analysis Agent 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**Agent 位置**: `src/workflow/nodes/technical_analysis/`

**核心職責**: 獲取歷史價格數據，計算 FracDiff 轉換、Z-Score，生成技術分析語義標籤。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `graph.py` | 14.3KB | Subgraph 構建 + 節點邏輯 |
| `adapter.py` | 1.9KB | 父圖適配器 |
| `subgraph_state.py` | 2.6KB | 子圖狀態 |
| `tools.py` | 18.7KB | 技術指標計算 |
| `backtester.py` | 20.2KB | 回測引擎 |
| `semantic_layer.py` | 12.8KB | 語義翻譯 |
| `structures.py` | 3.3KB | 數據結構 |
| `strategies.py` | 8.4KB | 交易策略 |

### 違規問題清單

#### ❌ 1. State 類型違規 (約章 §3.1)
- **問題**: `TechnicalAnalysisState` 使用 `Pydantic BaseModel`
- **位置**: [subgraph_state.py](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/technical_analysis/subgraph_state.py)

#### ❌ 2. 時間序列數據存入 State (約章 §3.2)
- **問題**: `price_series`, `volume_series`, `fracdiff_series`, `z_score_series` 等完整序列存入 State
- **位置**: [subgraph_state.py:61-80](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/technical_analysis/subgraph_state.py#L61-L80)
- **影響**: 每個序列可包含 250+ 天的數據點，State 膨脹嚴重

#### ❌ 3. Protocol 違規 (約章 §4.1)
- **問題**: 使用 `data` 字段推送完整圖表數據
- **位置**: `graph.py` 中 `semantic_translate_node` 返回大量序列數據

#### ❌ 4. 缺少 Mapper 層 (約章 §4.2)
- **問題**: 無 `summarize_ta_for_preview()` 函數

#### ❌ 5. Adapter 透傳 (約章 §4.3)
- **問題**: `output_adapter` 直接透傳 `technical_analysis` context
- **位置**: [adapter.py:25-58](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/technical_analysis/adapter.py#L25-L58)

---

## ✅ 重構 TODO 清單

### Phase 1: Artifact Store 整合

- [ ] **1.1** 修改 `data_fetch_node`：將原始價格序列存入 Artifact Store
  ```python
  async def data_fetch_node(state):
      ohlcv = await fetch_daily_ohlcv(state["ticker"])

      # 存入 Artifact Store
      price_artifact_id = await save_artifact(
          data={"prices": ohlcv.to_dict()},
          type="price_series",
          key_prefix=f"ta_price_{state['ticker']}"
      )

      # State 只存最新指標
      return Command(update={
          "technical_analysis": {
              "latest_price": ohlcv[-1],
              "price_artifact_id": price_artifact_id
          },
          "_private": {"price_df": ohlcv}  # 傳遞給下一節點
      })
  ```

- [ ] **1.2** 修改 `fracdiff_compute_node`：將 FracDiff 結果存入 Artifact Store
  ```python
  async def fracdiff_compute_node(state):
      fracdiff_result = compute_fracdiff(state["_private"]["price_df"])

      chart_artifact_id = await save_artifact(
          data={
              "fracdiff_series": fracdiff_result["series"],
              "z_score_series": fracdiff_result["z_scores"],
              "indicators": fracdiff_result["indicators"]
          },
          type="ta_chart_data",
          key_prefix=f"ta_chart_{state['ticker']}"
      )

      return Command(update={
          "technical_analysis": {
              "optimal_d": fracdiff_result["optimal_d"],
              "adf_statistic": fracdiff_result["adf_stat"],
              "chart_data_id": chart_artifact_id
          }
      })
  ```

### Phase 2: State 重構

- [ ] **2.1** 將 `TechnicalAnalysisState` 從 `BaseModel` 轉換為 `TypedDict`

- [ ] **2.2** 從 State 移除所有序列字段，改用 ID 指針
  ```python
  class TechnicalAnalysisContext(TypedDict):
      status: str | None
      # L2 關鍵指標 (Preview 源)
      latest_price: float | None
      optimal_d: float | None
      z_score_latest: float | None
      signal: str | None              # "BUY", "SELL", "HOLD"
      statistical_strength: str | None
      # L3 指針
      price_artifact_id: str | None
      chart_data_id: str | None
  ```

### Phase 3: Protocol 重構

- [ ] **3.1** 新增 Preview schema
  ```python
  class TechnicalPreview(BaseModel):
      """UI 關鍵渲染數據"""
      latest_price_display: str    # "$245.67"
      signal_display: str          # "📈 買入信號"
      z_score_display: str         # "Z: +2.1 (極度超買)"
      optimal_d_display: str       # "d=0.42 (中度記憶)"
      strength_display: str        # "統計強度: 高"
  ```

### Phase 4: Mapper 建立

- [ ] **4.1** 建立 `mappers.py`
  ```python
  def summarize_ta_for_preview(ctx: dict) -> dict:
      return {
          "latest_price_display": f"${ctx.get('latest_price', 0):.2f}",
          "signal_display": _format_signal(ctx.get("signal")),
          "z_score_display": _format_z_score(ctx.get("z_score_latest")),
          "optimal_d_display": f"d={ctx.get('optimal_d', 0):.2f}",
          "strength_display": f"統計強度: {ctx.get('statistical_strength', 'N/A')}"
      }
  ```

### Phase 5: Adapter 重構

- [ ] **5.1** 修改 `output_adapter`
  ```python
  def output_adapter(sub_output: dict) -> dict:
      ctx = sub_output.get("technical_analysis", {})
      chart_id = ctx.get("chart_data_id")

      preview = summarize_ta_for_preview(ctx)
      reference = ArtifactReference(
          artifact_id=chart_id,
          download_url=f"/api/artifacts/{chart_id}",
          type="ta_chart_data"
      ) if chart_id else None

      return {
          "technical_analysis": ctx,
          "artifact": AgentOutputArtifact(
              summary=f"技術分析: {preview['signal_display']}",
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
| MODIFY | `graph.py` | 節點邏輯改用 Artifact Store |
| MODIFY | `subgraph_state.py` | BaseModel → TypedDict，移除序列字段 |
| MODIFY | `adapter.py` | 整合 Mapper |
| NEW | `mappers.py` | 新增 Preview 映射函數 |
| MODIFY | `schemas.py` | 新增 TechnicalPreview |
| MODIFY | `../state.py` | 精簡 TechnicalAnalysisContext |

---

## ⚠️ 關鍵注意事項

1. **圖表數據體積**：每個時間序列約 250-500 個數據點，需存入 Artifact Store
2. **前端圖表渲染**：前端需異步拉取 `chart_data_id` 對應的序列數據來渲染圖表
3. **Debate 依賴**：Debate Agent 需讀取 `signal` 和 `z_score_latest` 作為輸入
4. **回測引擎**：`backtester.py` 邏輯不變，僅改變數據存儲位置
