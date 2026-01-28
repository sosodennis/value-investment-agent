# Debate Agent 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**Agent 位置**: `src/workflow/nodes/debate/`

**核心職責**: 執行 Bull/Bear 多輪對抗辯論，聚合分析結果，生成投資結論和倉位建議。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `graph.py` | 2.6KB | Subgraph 構建 |
| `nodes.py` | 16.5KB | 所有辯論節點邏輯 |
| `adapter.py` | 3KB | 父圖適配器 |
| `subgraph_state.py` | 2.5KB | 子圖狀態 |
| `schemas.py` | 3.1KB | 辯論結果 schemas |
| `prompts.py` | 10KB | LLM 提示詞 |
| `utils.py` | 14.6KB | 數據壓縮工具 |
| `market_data.py` | 8.8KB | 市場數據處理 |

### 違規問題清單

#### ❌ 1. State 類型違規 (約章 §3.1)
- **問題**: `DebateState` 使用 `Pydantic BaseModel`
- **位置**: [subgraph_state.py](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/debate/subgraph_state.py)

#### ❌ 2. 對話歷史存入 State (約章 §3.2)
- **問題**: `DebateContext.history` 存儲完整多輪對話（3輪×3方），可能包含大量 LLM 生成內容
- **位置**: [state.py:99-102](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/state.py#L99-L102)
- **影響**: 每輪辯論可能產生數 KB 文本

#### ❌ 3. Protocol 違規 (約章 §4.1)
- **問題**: 使用 `data` 字段推送完整 `DebateConclusion`
- **位置**: `nodes.py` 中 `verdict_node` 返回大量結構化數據

#### ❌ 4. 分析報告嵌套 (約章 §3.4)
- **問題**: `DebateContext.analyst_reports` 包含其他 Agent 的完整數據副本
- **位置**: [state.py:110-112](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/state.py#L110-L112)
- **影響**: 違反「引用傳遞」原則，造成數據重複

#### ❌ 5. 缺少 Mapper 層 (約章 §4.2)
- **問題**: 無 `summarize_debate_for_preview()` 函數

#### ❌ 6. Adapter 透傳 (約章 §4.3)
- **問題**: `output_adapter` 直接透傳 `debate` context
- **位置**: [adapter.py:29-86](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/debate/adapter.py#L29-L86)

---

## ✅ 重構 TODO 清單

### Phase 1: 數據引用重構

- [ ] **1.1** 移除 `analyst_reports` 字段：改為直接讀取其他 Context 的關鍵指標
  ```python
  async def debate_aggregator_node(state: DebateState):
      # BEFORE: 複製完整報告
      analyst_reports = {
          "fundamental": state["fundamental_analysis"]["financial_reports"]
      }

      # AFTER: 引用關鍵指標
      fa_ctx = state["fundamental_analysis"]
      ta_ctx = state["technical_analysis"]
      news_ctx = state["financial_news_research"]

      ground_truth = {
          "valuation_score": fa_ctx.get("valuation_score"),
          "ta_signal": ta_ctx.get("signal"),
          "news_sentiment": news_ctx.get("sentiment_score")
      }
  ```

### Phase 2: Artifact Store 整合

- [ ] **2.1** 修改 `verdict_node`：將辯論歷史存入 Artifact Store
  ```python
  async def verdict_node(state: DebateState):
      # 生成結論
      conclusion = generate_conclusion(state)

      # 存儲完整辯論歷史
      transcript_id = await save_artifact(
          data={
              "history": [msg.dict() for msg in state["debate"]["history"]],
              "rounds_summary": state["debate"]["rounds_summary"]
          },
          type="debate_transcript",
          key_prefix=f"debate_{state['ticker']}"
      )

      return Command(update={
          "debate": {
              "status": "complete",
              "final_verdict": conclusion.final_verdict,
              "kelly_confidence": conclusion.kelly_confidence,
              "winning_thesis": conclusion.winning_thesis,
              "transcript_id": transcript_id  # L3 指針
          }
      })
  ```

### Phase 3: State 重構

- [ ] **3.1** 將 `DebateState` 從 `BaseModel` 轉換為 `TypedDict`

- [ ] **3.2** 精簡 `DebateContext`：
  ```python
  class DebateContext(TypedDict):
      status: str | None
      current_round: int
      # L2 關鍵結論
      final_verdict: str | None         # "LONG", "SHORT", etc.
      kelly_confidence: float | None
      winning_thesis: str | None
      primary_catalyst: str | None
      primary_risk: str | None
      # L3 指針
      transcript_id: str | None
      # 移除: history, bull_thesis, bear_thesis, analyst_reports
  ```

### Phase 4: Protocol 重構

- [ ] **4.1** 新增 Preview schema
  ```python
  class DebatePreview(BaseModel):
      """UI 立即渲染用"""
      verdict_display: str          # "📈 強烈看多 (0.85)"
      thesis_display: str           # 核心論點摘要
      catalyst_display: str         # 主要催化劑
      risk_display: str             # 主要風險
      debate_rounds_display: str    # "完成 3 輪辯論"
  ```

### Phase 5: Mapper 建立

- [ ] **5.1** 建立 `mappers.py`
  ```python
  def summarize_debate_for_preview(ctx: dict) -> dict:
      verdict = ctx.get("final_verdict", "NEUTRAL")
      confidence = ctx.get("kelly_confidence", 0)

      return {
          "verdict_display": _format_verdict(verdict, confidence),
          "thesis_display": ctx.get("winning_thesis", "分析中..."),
          "catalyst_display": ctx.get("primary_catalyst", "-"),
          "risk_display": ctx.get("primary_risk", "-"),
          "debate_rounds_display": f"完成 {ctx.get('current_round', 0)} 輪辯論"
      }
  ```

### Phase 6: Adapter 重構

- [ ] **6.1** 修改 `output_adapter`
  ```python
  def output_adapter(sub_output: dict) -> dict:
      ctx = sub_output.get("debate", {})
      transcript_id = ctx.get("transcript_id")

      preview = summarize_debate_for_preview(ctx)
      reference = ArtifactReference(
          artifact_id=transcript_id,
          download_url=f"/api/artifacts/{transcript_id}",
          type="debate_transcript"
      ) if transcript_id else None

      return {
          "debate": ctx,
          "artifact": AgentOutputArtifact(
              summary=preview["verdict_display"],
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
| MODIFY | `nodes.py` | verdict_node 整合 Artifact Store |
| MODIFY | `subgraph_state.py` | BaseModel → TypedDict |
| MODIFY | `adapter.py` | 整合 Mapper |
| NEW | `mappers.py` | 新增 Preview 映射函數 |
| MODIFY | `schemas.py` | 新增 DebatePreview |
| MODIFY | `../state.py` | 精簡 DebateContext |

---

## ⚠️ 關鍵注意事項

1. **辯論歷史體積**：3輪×3方的完整對話可達 10KB+，必須存入 Artifact Store
2. **引用 vs 複製**：應直接讀取其他 Agent 的 Context，而非在 `analyst_reports` 中複製
3. **Executor 依賴**：Debate 輸出的 `model_type` 會傳遞給 Executor Agent
4. **前端展示**：Preview 應包含足夠信息讓前端渲染「投資結論卡片」
