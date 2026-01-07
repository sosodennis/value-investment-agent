針對 Financial News Research Agent 的搜尋結果（Search Result）設計數據結構時，關鍵在於\*\*「這條新聞對投資決策的價值」\*\*。

普通的 Google Search 結果（標題、連結、摘要）對於金融 Agent 來說是不夠的。你需要設計一個結構，能讓 LLM 進行**去重（Deduplication）**、**實體識別（NER）**、**情感分析（Sentiment）** 以及 **可信度權重（Credibility Weighting）**。

這是一個適合企業級 Python/LangGraph/FastAPI 環境的 Pydantic Model 設計建議：

### ---

**1\. 核心結構設計思路 (The Layered Approach)**

我建議將數據模型分為三個層次：

1. **Metadata Layer (元數據)**：來源、時間、唯一標識（用於去重）。
2. **Content Layer (內容層)**：標題、摘要、全文（如有）。
3. **Financial Context Layer (金融語境層)**：這是最關鍵的，包含 Tickers、相關性、情感、影響力。

### ---

**2\. Python Pydantic Model 實現代碼**

這可以直接用作你 Agent 的 State 或 Tool Output Schema：

Python

from pydantic import BaseModel, Field, HttpUrl
from typing import List, Optional
from datetime import datetime
from enum import Enum

\# \--- Enums for Standardization \---
class SentimentLabel(str, Enum):
    BULLISH \= "bullish"
    BEARISH \= "bearish"
    NEUTRAL \= "neutral"

class ImpactLevel(str, Enum):
    HIGH \= "high"      \# e.g., Earnings miss, M\&A, CEO fired
    MEDIUM \= "medium"  \# e.g., Product launch, Analyst upgrade
    LOW \= "low"        \# e.g., Routine PR, General commentary

class AssetClass(str, Enum):
    EQUITY \= "equity"
    CRYPTO \= "crypto"
    FOREX \= "forex"
    COMMODITY \= "commodity"
    MACRO \= "macro"    \# e.g., CPI data, Fed rate

\# \--- Sub-Models \---
class SourceInfo(BaseModel):
    name: str \= Field(..., description="來源名稱, e.g., Bloomberg, Reuters, WSJ")
    domain: str \= Field(..., description="來源域名, 用於判斷權威性")
    reliability\_score: float \= Field(default=0.5, ge=0.0, le=1.0, description="來源可信度權重 (0-1)")
    author: Optional\[str\] \= None

class FinancialEntity(BaseModel):
    ticker: str \= Field(..., description="股票代碼, e.g., AAPL")
    company\_name: str
    relevance\_score: float \= Field(..., description="該實體與新聞的關聯度 (0-1)")

class AIAnalysis(BaseModel):
    summary: str \= Field(..., description="由 LLM 生成的一句話金融摘要")
    sentiment: SentimentLabel
    sentiment\_score: float \= Field(..., description="-1.0 (Very Negative) to 1.0 (Very Positive)")
    impact\_level: ImpactLevel
    key\_event: Optional\[str\] \= Field(None, description="識別的關鍵事件, e.g., 'Q3 Earnings Report'")
    reasoning: str \= Field(..., description="LLM 判斷這條新聞重要的原因")

\# \--- Main Model \---
class FinancialNewsItem(BaseModel):
    \# Identity & Access
    id: str \= Field(..., description="基於 URL 或 Title 的 Hash ID，用於去重")
    url: HttpUrl

    \# Metadata
    published\_at: datetime \= Field(..., description="標準化 UTC 時間")
    fetched\_at: datetime \= Field(default\_factory=datetime.utcnow)

    \# Content
    title: str
    snippet: str \= Field(..., description="搜尋引擎返回的原始摘要")
    full\_content: Optional\[str\] \= Field(None, description="如果有爬蟲二次獲取全文")

    \# Structured Data (Usually extracted by LLM after search)
    source: SourceInfo
    related\_tickers: List\[FinancialEntity\] \= Field(default\_factory=list)
    tags: List\[str\] \= Field(default\_factory=list, description="e.g., 'Earnings', 'Regulation', 'IPO'")

    \# AI Enrichment
    analysis: Optional\[AIAnalysis\] \= None

    class Config:
        json\_schema\_extra \= {
            "example": {
                "id": "a1b2c3d4",
                "title": "Apple Shares Drop on iPhone Shipment Concerns",
                "published\_at": "2024-05-21T14:30:00Z",
                "related\_tickers": \[{"ticker": "AAPL", "company\_name": "Apple Inc.", "relevance\_score": 0.95}\],
                "analysis": {
                    "sentiment": "bearish",
                    "impact\_level": "high",
                    "reasoning": "Supply chain issues directly affect revenue guidance."
                }
            }
        }

### ---

**3\. 設計重點解析 (Why this structure?)**

#### **A. id (Deduplication)**

金融新聞重複率極高（例如 Bloomberg 發了一篇，Yahoo Finance 轉載，Investing.com 又轉載）。

* **做法**：在存入 Database 或傳給下游 Agent 前，建議用 hash(url) 或 hash(title \+ published\_date) 生成 ID。
* **用途**：防止你的 Agent 對同一條新聞重複分析，浪費 Token。

#### **B. reliability\_score (Source Weighting)**

並非所有新聞都是平等的。

* **做法**：你可以維護一個 Config Mapping。
  * *Tier 1 (Score 1.0)*: SEC Filings, Bloomberg, Reuters, WSJ.
  * *Tier 2 (Score 0.7)*: CNBC, TechCrunch, Yahoo Finance.
  * *Tier 3 (Score 0.3)*: Seeking Alpha (User blogs), Reddit, Twitter (X).
* **用途**：計算最終的 "Market Sentiment Score" 時，用這個分數做加權平均。

#### **C. related\_tickers vs. tags**

* **Tickers** 是強關聯，用於將新聞路由到特定的股票分析模組（例如：這條新聞是給 AAPL Agent 看的）。
* **Tags** 是宏觀分類（如 "Inflation", "AI Regulation"），用於宏觀分析。

#### **D. published\_at (Time is Money)**

* **痛點**：搜尋引擎返回的通常是 "2 hours ago"。
* **做法**：必須在 Agent 的 Tool 內部將相對時間轉換為 **UTC ISO 8601** 格式。金融分析非常依賴時間順序，如果是 "昨天的舊聞" 但被當作 "即時新聞" 處理，會導致嚴重的判斷錯誤。

### ---

**4\. 數據流向 (Workflow)**

如果這是用於你的 LangGraph 系統：

1. **Search Node**: 調用 Google/Tavily API，返回原始 JSON。
2. **Parser Node**: 將原始 JSON 轉換為上述 FinancialNewsItem 的基礎版本（只有 title, url, snippet）。
3. **Enrichment Node (LLM)**: 輸入 Snippet，輸出 analysis (Sentiment, Tickers, Impact)。
4. **Filter Node**: 根據 impact\_level 或 reliability\_score 過濾掉噪音。
5. **Database**: 存入 Postgres (JSONB) 或 Vector DB。

### **下一步**

你需要我幫你寫那個 **"Enrichment Node" 的 Prompt** 嗎？（即如何讓 LLM 準確地從新聞標題和摘要中提取 Ticker 和判斷情感分數）。

這是一個非常好的問題。簡單回答：**是的，這是目前的業界主流做法，但「直接讓 LLM 給一個數字」不是企業級做法。**

在 2024-2026 年的金融科技（FinTech）和量化領域，利用 LLM 進行非結構化數據（新聞、財報會議記錄）的量化分析已經是標準配置（Standard Practice）。

然而，要把這件事做到 **"Enterprise Grade"（企業級可靠性）**，不能只是寫一個 Prompt 說「請打分 1-10」，而是需要一套嚴謹的 **Pipeline** 和 **Guardrails**。

以下我為你分析業界目前的層次與做法：

### ---

**1\. 為什麼業界轉向 LLM 打分？（vs 傳統 NLP）**

在 LLM 出現之前（如 2020 年前），業界主要用 **FinBERT** 或 **Loughran-McDonald Dictionary** 進行詞頻統計。

4. **傳統做法的缺陷**：
   * 無法理解語境。例如：「*Competitor X's factory burned down*」（競爭對手工廠燒毀）。
   * 傳統模型看到 "Burned down" (負面詞) $\\rightarrow$ 判斷為負面。
   * **LLM** 理解語境 $\\rightarrow$ 對 Competitor X 是負面，但對你的標的（作為競爭對手）可能是 **利好 (Bullish)**。
   * LLM 能處理「雖然營收低於預期，但指引（Guidance）大幅上調」這種複雜邏輯。

### ---

**2\. 怎樣才算「企業級」的 LLM 打分？**

企業級與玩具級（Toy Project）的區別在於：**可解釋性（Explainability）、一致性（Consistency）與 容錯率（Robustness）。**

如果你要在企業級環境實現，必須遵循以下四大原則：

#### **A. 強制推理 (Reasoning First, Score Later)**

**絕對不要**讓 LLM 直接輸出分數。

* ❌ **錯誤做法**：Score this news from \-1 to 1\.
* ✅ **企業級做法 (Chain of Thought)**：要求 LLM 先生成一段簡短的分析邏輯，再給出分數。
  * 這樣做有兩個好處：
    * LLM 的推理過程會提升分數的準確性（CoT 效應）。
    * 這段 reasoning 是給人類（分析師/合規部門）看的 Audit Trail（審計軌跡）。

#### **B. 結構化輸出驗證 (Structured Output & Schema Validation)**

不能依賴 Regex 去抓分數。必須使用 OpenAI 的 **Function Calling / JSON Mode** 或 LangChain 的 PydanticOutputParser。

* 如果 LLM 輸出的格式不對，系統應自動重試或報錯，而不是讓整個 Pipeline 崩潰。這就是為什麼我在上一個回答中強烈建議使用 Pydantic Model。

#### **C. 確定性護欄 (Deterministic Guardrails)**

LLM 是概率模型，存在幻覺風險。企業級系統會加上一層「規則過濾」：

6. **關鍵詞觸發**：如果新聞標題包含 "Chapter 11" (破產保護) 或 "Investigation" (調查)，直接由 Python 代碼強制覆蓋分數為 \-1.0 (極度負面)，而不經過 LLM 判斷，或者作為 LLM 的強提示。
7. **分數區間約束**：強制分數必須在 \[-1.0, 1.0\] 之間，不能出現 1.5。

#### **D. 混合評分機制 (Ensemble / Self-Consistency)**

對於極其重要的決策（例如直接影響交易信號），不會只問一次。

* **做法**：讓 LLM 用不同的 Persona（例如：風險控管官、激進投資者、宏觀經濟學家）分別打分，然後取 **加權平均** 或 **中位數**。這能顯著降低 LLM 偶爾「發瘋」的機率。

### ---

**3\. 企業級實現架構圖**

這是一個典型的 Financial NLP Pipeline：

程式碼片段

graph TD
    A\[原始新聞 Raw News\] \--\> B(預處理 & 去重)
    B \--\> C{是否包含敏感關鍵詞?}

    C \-- 是 (e.g., Bankruptcy) \--\> D\[規則引擎直接打分: \-1.0\]
    C \-- 否 \--\> E\[LLM Agent\]

    subgraph LLM Scoring Process
    E \--\> F\[Prompt: Role \+ Context \+ Output Schema\]
    F \--\> G\[生成 Reasoning (解釋原因)\]
    G \--\> H\[生成 Score (數值化)\]
    end

    H \--\> I\[Pydantic Validation\]
    I \-- 格式錯誤 \--\> E
    I \-- 成功 \--\> J\[存入數據庫\]
    D \--\> J

    J \--\> K\[下游應用: 儀表板 / 交易信號\]

### ---

**4\. 實際案例參考**

* **BloombergGPT**: Bloomberg 專門訓練了自己的模型來做這件事，主要就是為了更準確的 Sentiment Analysis 和 Named Entity Recognition (NER)。
* **Hedge Funds (對沖基金)**: 許多基金現在使用 LLM 來消化每日數萬條新聞，生成一個 "Sentiment Signal"，然後這個 Signal 只是他們多因子模型（Multi-factor Model）中的**其中一個因子**（Feature），而不是唯一的決策依據。

### **5\. 給你的建議 (Action Plan)**

既然你想做「企業級」的應用，建議你在設計 Prompt 時採用 **"Few-Shot Prompting" (少樣本提示)** 的策略。

不要只給定義，要給範例（Examples）：

**System Prompt 範例概念：**

你是一個華爾街資深分析師。請分析以下新聞對 \[TICKER\] 的影響。

規則：

1. 先寫分析原因。
2. 分數範圍 \-1.0 (極負面) 到 1.0 (極正面)。
3. 0.0 代表中性或無關。

Example 1:
News: "Apple beats earnings estimates by 5%, but warns of slower growth in China."
Output:
{
"reasoning": "雖然盈利超出預期是利好，但中國市場是核心增長點，增長放緩的指引對未來現金流預期有重大負面影響。市場通常更看重指引而非當期業績。",
"score": \-0.3
}
Example 2:
News: "Apple launches new iPhone with AI features."
Output:
{
"reasoning": "產品發布符合預期，市場已定價（Priced in），短期無重大驚喜。",
"score": 0.1
}

總結：
讓 LLM 打分是絕對正確且先進的方向。只要你加上 Pydantic 結構化驗證、推理過程保留 以及 必要的規則護欄，這就是一個標準的企業級解決方案。

這是一個非常切中痛點的問題。在企業級應用中，直接把所有搜尋結果的全文（Full Text）餵給 LLM 是**絕對的反模式（Anti-pattern）**。

這不僅僅是 **Token 費用** 的問題，更重要的是 **「信噪比」（Signal-to-Noise Ratio）** 和 **延遲（Latency）**。

如果 DuckDuckGo 返回 10 條結果，每條新聞全文平均 1,000 字（約 1,500 tokens），直接丟進去就是 15,000 tokens。這會導致：

5. **太貴**：每次查詢成本飆升。
6. **太慢**：用戶要等幾十秒。
7. **變笨**：LLM 有 "Lost in the Middle" 現象，過多無關資訊會干擾它對關鍵信息的提取。

### **企業級解決方案：漏斗式篩選（The Funnel Architecture）**

建議採用 **「兩階段篩選 \+ 按需獲取」** 的架構。這在 LangGraph 中非常容易實現。

### ---

**階段一：Snippet 級別的快速篩選 (The Selector)**

DuckDuckGo 搜尋結果會返回 Title, Link, 和 Snippet (簡短摘要)。這些加起來通常只有幾百個 Token。

做法：
先用一個便宜、快速的模型（如 gpt-4o-mini 或 Claude-3-Haiku）看這些 Snippets，決定哪些值得「點進去看」。
**Prompt 邏輯**：

"這裡有 10 條關於 \[TICKER\] 的新聞摘要。請選出 **最相關且最新的 3 條** 來源。忽略重複內容或廣告。"

**代碼概念 (Python)**：

Python

\# 假設 search\_results 是 DuckDuckGo 返回的 List\[dict\]
\# 這裡不需要全文，只需要 snippet

class SelectedNews(BaseModel):
    selected\_ids: List\[int\] \= Field(..., description="值得深入閱讀的新聞 ID 列表")
    reasoning: str

\# 用便宜的模型做決策
selector\_llm \= ChatOpenAI(model="gpt-4o-mini")
selection \= selector\_llm.with\_structured\_output(SelectedNews).invoke(prompt)

\# 結果：只剩下 3 個 URL 需要處理

### ---

**階段二：全文獲取與清洗 (Fetch & Clean)**

對於被選中的這 3 條 URL，你需要用 Python 爬蟲去獲取內容。

關鍵點：不要餵 HTML！
網頁 HTML 充滿了 JavaScript、導航欄、廣告代碼，這些全是 Token 垃圾。
工具推薦：
在 Python 企業級開發中，建議使用 trafilatura 或 newspaper3k，而不是單純的 BeautifulSoup。這些庫專門設計用來提取「文章正文」，會自動去掉廣告和側邊欄。

Python

import trafilatura

def fetch\_clean\_text(url: str):
    downloaded \= trafilatura.fetch\_url(url)
    \# extract 函數會只留下核心文章內容，省去大量 Token
    text \= trafilatura.extract(downloaded, include\_comments=False, include\_tables=False)
    if not text:
        return None
    \# 進一步截斷：有些新聞極長，通常前 2000 個字符包含 80% 的信息
    return text\[:4000\] \# 視情況截斷

### ---

**階段三：核心分析 (The Analysis)**

現在你手上有 3 篇清洗過的純文本。這時候才動用**聰明的模型**（如 gpt-4o 或 Claude-3.5-Sonnet）進行深度分析、打分和提取。

### ---

**成本與 Token 對比**

讓我們算一筆帳：

| 步驟 | 策略 A：蠻力法 (全部全文) | 策略 B：漏斗法 (企業級做法) |
| :---- | :---- | :---- |
| **輸入數據** | 10 篇全文 | 10 個 Snippets \+ 3 篇全文 |
| **Token 估算** | 10 × 1,500 \= **15,000 tokens** | (10 × 50\) \+ (3 × 1,000) \= **3,500 tokens** |
| **LLM 模型** | 必須用 Smart Model (處理長文) | Selector 用 Mini (便宜) \+ Analyzer 用 Smart |
| **成本 (估算)** | **高 (約 4-5 倍)** | **低** |
| **準確度** | 低 (噪音太多，容易混淆) | 高 (只專注於高價值內容) |

### **總結架構圖**

在你的 LangGraph 中，這應該是這樣的流程：

程式碼片段

graph TD
    A\[User Query\] \--\> B\[DuckDuckGo Search\]
    B \--\> C\[10 Search Results (Snippets only)\]

    C \--\> D{Selector Agent (Mini Model)}
    D \-- 判斷不相關 \--\> E\[丟棄\]
    D \-- 選中 Top 3 \--\> Fhttps://www.scrapy.org/

    F \--\> G\[Trafilatura Cleaning (去除 HTML)\]
    G \--\> H\[Cleaned Text\]

    H \--\> I{Analyst Agent (Smart Model)}
    I \--\> J\[最終結構化報告\]
