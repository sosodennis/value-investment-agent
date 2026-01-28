# Financial News Agent 重構計劃

> 依據 [refactor-plan.md](file:///Users/denniswong/Desktop/Project/value-investment-agent/temp-feature-research/state-refactor/refactor-plan.md) 工程約章 v3.1

## 📋 概述

**Agent 位置**: `src/workflow/nodes/financial_news_research/`

**核心職責**: 搜索、篩選、爬取和分析金融新聞，生成情緒分析報告。

---

## 🔍 當前狀態分析

### 現有文件結構

| 文件 | 大小 | 用途 |
|------|------|------|
| `graph.py` | 19.6KB | Subgraph 構建 + 所有節點邏輯 |
| `adapter.py` | 2KB | 父圖適配器 |
| `subgraph_state.py` | 2.3KB | 子圖狀態 |
| `structures.py` | 6KB | 數據結構 |
| `schemas.py` | 461B | Pydantic schemas |
| `tools.py` | 15.9KB | 新聞搜索工具 |
| `finbert_service.py` | 4.8KB | FinBERT 情緒分析 |

### 違規問題清單

#### ❌ 1. State 類型違規 (約章 §3.1)
- **問題**: `FinancialNewsState` 使用 `Pydantic BaseModel`
- **位置**: [subgraph_state.py](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/subgraph_state.py)

#### ❌ 2. 中間數據存入 State (約章 §3.4)
- **問題**: `raw_results`, `news_items`, `selected_indices` 等中間處理數據存入 State
- **位置**: [subgraph_state.py:60-73](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/subgraph_state.py#L60-L73)
- **影響**: Checkpoint 包含大量不需要持久化的數據

#### ❌ 3. Protocol 違規 (約章 §4.1)
- **問題**: 使用 `data` 字段推送完整新聞列表和分析結果
- **位置**: `graph.py` 中 `aggregator_node` 返回大量數據

#### ❌ 4. 全文內容存入 State
- **問題**: 爬取的新聞全文 (`fetched_content`) 直接存入 `news_items`
- **位置**: [graph.py:205-298](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/graph.py#L205-L298)
- **影響**: 單篇新聞可能數 KB，多篇累計會導致 State 膨脹

#### ❌ 5. 缺少 Mapper 層 (約章 §4.2)
- **問題**: 無 `summarize_news_for_preview()` 函數

#### ❌ 6. Adapter 透傳 (約章 §4.3)
- **問題**: `output_adapter` 直接透傳 `financial_news_research` context
- **位置**: [adapter.py:25-60](file:///Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/financial_news_research/adapter.py#L25-L60)

---

## ✅ 重構 TODO 清單

### Phase 1: 中間數據隔離

- [ ] **1.1** 將 `raw_results`, `formatted_results`, `selected_indices` 移出 State，改為節點內部變量或使用 `private=True`
  ```python
  # BEFORE: 存入 State
  "raw_results": search_results

  # AFTER: 使用 return 傳遞或存入 private state
  return Command(update={
      "_private": {"raw_results": search_results},  # 不持久化
      ...
  })
  ```

### Phase 2: Artifact Store 整合

- [ ] **2.1** 修改 `fetch_node`：將新聞全文存入 Artifact Store
  ```python
  async def fetch_node(state):
      articles = await fetch_articles(state["selected_urls"])

      # 只存摘要到 State
      summaries = []
      for article in articles:
          artifact_id = await save_artifact(
              data={"full_text": article["content"]},
              type="news_article",
              key_prefix=f"news_{article['url_hash']}"
          )
          summaries.append({
              "title": article["title"],
              "source": article["source"],
              "sentiment": article["sentiment"],
              "content_id": artifact_id  # L3 指針
          })

      return Command(update={"news_items": summaries})
  ```

- [ ] **2.2** 修改 `aggregator_node`：生成最終摘要並存儲完整報告
  ```python
  async def aggregator_node(state):
      report = generate_full_report(state["news_items"])
      report_id = await save_artifact(
          data=report,
          type="news_analysis_report",
          key_prefix=f"news_report_{state['ticker']}"
      )

      return Command(update={
          "financial_news_research": {
              "status": "success",
              "sentiment_summary": calculate_overall_sentiment(report),  # L2
              "article_count": len(state["news_items"]),                 # L2
              "report_id": report_id                                     # L3
          }
      })
  ```

### Phase 3: State 重構

- [ ] **3.1** 將 `FinancialNewsState` 從 `BaseModel` 轉換為 `TypedDict`

- [ ] **3.2** 精簡 `FinancialNewsContext`：
  ```python
  class FinancialNewsContext(TypedDict):
      status: str | None
      sentiment_summary: str | None        # "看漲", "看跌", "中性"
      sentiment_score: float | None        # -1.0 to 1.0
      article_count: int | None            # 分析的文章數量
      report_id: str | None                # Artifact 指針
  ```

### Phase 4: Protocol 重構

- [ ] **4.1** 新增 Preview schema
  ```python
  class NewsPreview(BaseModel):
      status_label: str
      sentiment_display: str       # "📈 看漲 (0.72)"
      article_count_display: str   # "分析了 12 篇新聞"
      top_headlines: list[str]     # 最多 3 條標題
  ```

### Phase 5: Mapper 建立

- [ ] **5.1** 建立 `mappers.py`
  ```python
  def summarize_news_for_preview(ctx: dict, news_items: list) -> dict:
      sentiment = ctx.get("sentiment_score", 0)
      return {
          "status_label": "完成" if ctx.get("status") == "success" else "處理中",
          "sentiment_display": _format_sentiment(sentiment),
          "article_count_display": f"分析了 {ctx.get('article_count', 0)} 篇新聞",
          "top_headlines": [n["title"] for n in news_items[:3]]
      }
  ```

### Phase 6: Adapter 重構

- [ ] **6.1** 修改 `output_adapter`：調用 Mapper 生成 Preview/Reference
  ```python
  def output_adapter(sub_output: dict) -> dict:
      ctx = sub_output.get("financial_news_research", {})
      report_id = ctx.get("report_id")

      preview = summarize_news_for_preview(ctx, sub_output.get("news_items", []))
      reference = ArtifactReference(...) if report_id else None

      return {
          "financial_news_research": ctx,
          "artifact": AgentOutputArtifact(
              summary=f"新聞分析: {preview['sentiment_display']}",
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
| MODIFY | `subgraph_state.py` | BaseModel → TypedDict，移除中間數據 |
| MODIFY | `adapter.py` | 整合 Mapper |
| NEW | `mappers.py` | 新增 Preview 映射函數 |
| MODIFY | `schemas.py` | 新增 NewsPreview |
| MODIFY | `../state.py` | 精簡 FinancialNewsContext |

---

## ⚠️ 關鍵注意事項

1. **新聞內容體積**：單篇新聞全文可達數 KB，多篇累計影響顯著
2. **管線處理**：search → select → fetch → analyze → aggregate 五階段，中間數據不需持久化
3. **FinBERT 服務**：情緒分析結果 (sentiment score) 應存入 State 作為 L2 數據
4. **Debate 依賴**：Debate Agent 需讀取新聞分析結果，確保 `sentiment_summary` 可用
