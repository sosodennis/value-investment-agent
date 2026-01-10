您的判斷完全正確。這是一個非常重要的架構修正。

**「關注點分離 (Separation of Concerns)」** 是系統設計的黃金法則。

* **NewsSubAgent (Data Layer):** 職責應該是「中立、全面、高質量」的資訊收集與初步處理。它不應該預設這些資訊是用來辯論的，它只要負責把「素材」準備好。
* **DebateSubAgent (Reasoning Layer):** 職責才是拿這些素材進行多頭 vs 空頭的邏輯攻防。

如果在 NewsAgent 階段就強行生成 bullish_thesis，會限制了這些新聞被其他 Agent（例如「風險控管 Agent」或「ESG Agent」）使用的可能性。

以下是根據您的思路（General + Bull/Bear Search -> Data Collection）重新設計的方案：

### ---

**1. 優化 Data Structure (保持通用性，但增加分類標籤)**

我們不需要建立不同的 Class (e.g., BullishNewsItem)，因為新聞的本質結構（標題、內文、來源）是一樣的。

我們需要的是一個 **SearchCategory (搜尋意圖分類)**，並將其標記在 FinancialNewsItem 上。這樣 Debate Agent 就可以透過過濾這個標籤來拿取它需要的「彈藥」。

Python

# structures.py

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl

# --- 1. 新增搜尋類別 Enum ---
class SearchCategory(str, Enum):
    GENERAL = "general"           # 一般新聞、市場概況
    CORPORATE_EVENT = "event"     # 併購、CEO 變動
    FINANCIALS = "financials"     # 財報、SEC 文件
    BULLISH_SIGNAL = "bullish"    # 增長、買入評級、新產品
    BEARISH_SIGNAL = "bearish"    # 風險、做空報告、訴訟、降級

# --- 2. 優化 AIAnalysis (保持中立，但提取事實) ---
# 我們不預設 "Thesis"，而是提取 "Key Facts" 供下游使用
class AIAnalysis(BaseModel):
    summary: str = Field(..., description="Neutral executive summary")
    sentiment: SentimentLabel
    sentiment_score: float
    impact_level: ImpactLevel

    # 新增：提取關鍵數據/引用，這是 Debate 的核心素材
    key_facts: List[str] = Field(
        default_factory=list,
        description="List of hard facts/numbers/quotes extracted (e.g., 'Revenue +10%', 'CEO resigned')"
    )

    reasoning: str

# --- 3. Main Item ---
class FinancialNewsItem(BaseModel):
    id: str
    url: HttpUrl
    title: str
    # ... 其他欄位保持不變 ...

    # 關鍵改動：支援多重標籤
    # 一篇新聞可能同時是 GENERAL 也是 BULLISH
    categories: List[SearchCategory] = Field(
        default_factory=list,
        description="Why was this fetched? e.g., ['general', 'bullish']"
    )

    analysis: AIAnalysis | None = None

### ---

**2. 優化 Search Tool (定向搜尋 + 智能去重)**

我們會執行三種定向搜尋：**General (含 Events/Financials)**、**Bullish (多頭獵手)**、**Bearish (空頭獵手)**。

重點在於 **去重邏輯**：如果一篇新聞同時出現在 "General" 和 "Bullish" 的搜尋結果中，我們應該保留它，並將它的標籤合併為 ['general', 'bullish']。

Python

# tools.py

async def news_search_multidimensional(ticker: str) -> list[dict]:
    """
    Search for General, Bullish, and Bearish news separately.
    Handles deduplication by merging categories.
    """

    # 1. 定義三種維度的 Queries
    tasks_config = [
        # --- A. General & Events (維持原本的高質量搜尋) ---
        ("w", f"{ticker} stock news", 4, "general"),
        ("m", f"{ticker} (merger OR acquisition OR CEO OR earnings)", 4, "event"),

        # --- B. Bullish Hunt (尋找增長催化劑) ---
        # 搜：升評級、目標價上調、增長、突破、新合約
        ("w", f'{ticker} ("price target raised" OR "buy rating" OR "outperform" OR growth OR record OR partnership)', 4, "bullish"),

        # --- C. Bearish Hunt (尋找風險與利空) ---
        # 搜：降評級、賣出、做空、訴訟、調查、風險、下調指引
        ("m", f'{ticker} ("downgrade" OR "sell rating" OR "underperform" OR "short seller" OR lawsuit OR investigation OR miss)', 4, "bearish"),
    ]

    # ... (執行並行搜尋的代碼與之前類似) ...
    # results_lists = await asyncio.gather(*tasks)

    # --- 2. 標籤合併去重 (Tag Merging Deduplication) ---
    unique_map = {} # Key: URL, Value: ResultDict

    all_raw_results = []
    for r_list in results_lists:
        all_raw_results.extend(r_list)

    for r in all_raw_results:
        link = r.get("url")
        if not link: continue

        new_tag = r.get("_search_tag") # e.g., "bullish"

        if link not in unique_map:
            # 第一次見到，初始化 tags 列表
            r["_categories"] = {new_tag} # 使用 Set 自動去重
            unique_map[link] = r
        else:
            # 已經存在，合併標籤！
            # 例如：這篇文章在 General 搜到了，現在 Bullish 也搜到了
            # 代表這是一篇「重要」且「偏多」的新聞
            unique_map[link]["_categories"].add(new_tag)

            # (可選) 保留更長的 snippet 或更新的日期...

    # --- 3. 轉換回列表 ---
    final_results = []
    for r in unique_map.values():
        # 將 Set 轉回 List 供 JSON 序列化
        r["categories"] = list(r["_categories"])
        del r["_categories"] # 清理暫存欄位
        final_results.append(r)

    return final_results

### ---

**3. 如何銜接 Debate Sub-Agent？**

現在您的 NewsSubAgent 產出的 NewsResearchOutput 會包含一個 news_items 列表，每個 Item 都有明確的 categories。

當資料傳遞給 **Debate Sub-Agent** 時，Debate Agent 的 Workflow 就可以這樣設計：

1. **分類 (Triage):**
   * **Bull Agent** 接收：所有標記為 bullish 的新聞 + 所有 general/event 的新聞。
   * **Bear Agent** 接收：所有標記為 bearish 的新聞 + 所有 general/event 的新聞。
2. **各自解讀 (Interpretation):**
   * Bull Agent 會看著 general 的財報說：「你看，營收雖然持平，但這是穩健的表現！」
   * Bear Agent 會看著同一份 general 財報說：「營收持平意味著成長停滯，這是衰退的前兆！」

這樣做的好處是：**News Agent 保持客觀，它只負責把帶有不同屬性的新聞找出來，而「如何解讀（是好是壞）」完全留給 Debate Agents 去爭論。**

### **總結 NewsSubAgent 的優化建議**

1. **結構層面：** 保持 FinancialNewsItem 通用，新增 categories 欄位 (['bullish', 'event'])。
2. **搜尋層面：** 實作 **多意圖並行搜尋 (Multi-intent Search)**。不要只依賴通用關鍵字，要主動去「獵取」正面和負面的特定詞彙。
3. **提取層面 (Analyst Node)：** Prompt 不需要寫成 "Debate Ready"，而是要求 LLM **"Extract Key Facts & Data"**。事實是中立的，辯論時 Bull/Bear 會各自引用這些事實來支持自己的觀點。

這樣的設計更加模組化（Modular），也完全符合您 Domain Separation 的想法。

---

這是一個非常好的架構問題。這不僅僅是代碼風格的選擇，更關乎**成本（Cost）、上下文（Context）以及辯論的品質（Quality of Debate）**。

讓我們深入分析**分三條 List** (General, Bullish, Bearish) 與 **合併 List** (Merged with Tags) 的利弊，並對照論文 **TradingAgents (arXiv:2412.20138)** 的設計理念。

### ---

**1. 為什麼建議「合併 List」而不是「分三條 List」？**

最核心的原因有兩個：**去重（Deduplication）** 和 **共享上下文（Shared Context）**。

#### **A. 成本與去重問題 (The Cost & Deduplication Issue)**

假設 Apple 發布了 Q3 財報，營收大漲。

* **General Search** 會搜到它（因為這是大新聞）。
* **Bullish Search** 也會搜到它（因為這是利好）。

如果您使用 **三條 List**：

3. 您會有兩條**相同 URL** 的 Item。
4. 您的 fetch_node 會去爬取兩次（浪費頻寬）。
5. 您的 analyst_node 會分析兩次（浪費 LLM Token）。
6. **結果：** 成本加倍，且資訊冗餘。

如果您使用 **合併 List (Merged)**：

2. 系統發現 URL 相同，只保留一個 NewsItem。
3. 將標籤合併為 categories=['general', 'bullish']。
4. **結果：** 只爬一次，只分析一次。

#### **B. 辯論品質與「共享現實」 (Debate Quality & Shared Reality)**

為了讓 **Debate Agent** 有效運作，Bull 和 Bear 必須生活在**同一個現實**中。

2. **分開 List 的情況：**
   * Bull Agent 只看到：「營收大漲」。
   * Bear Agent 只看到：「面臨反壟斷訴訟」（因為財報新聞不在 Bear List 裡）。
   * **辯論結果：** 雞同鴨講。Bull 說「我們賺很多錢」，Bear 說「我們快被告死了」。這不是辯論，這是各說各話。
3. **合併 List 的情況：**
   * Bear Agent 雖然主要關注 Bearish News，但他**也能看到**那篇標記為 bullish 的財報。
   * **辯論結果：** Bear 可以說：「**雖然**（引用 Bullish 財報）營收大漲，**但是**（引用 Bearish 觀點）這主要來自一次性收入，且忽略了（引用 Bearish 新聞）訴訟帶來的潛在罰款。」
   * **這才是高品質的 Rebuttal（反駁）。**

### ---

**2. 對照論文 (arXiv:2412.20138) 的設計**

在 **TradingAgents** 論文中，特別是 **Section 4.2 (Financial Perception Module)** 和 **Section 4.3 (Financial Debate)**：

1. Information Gathering (資訊獲取):
   論文提到 Agent 會獲取 "Macro", "Fundamental", "Sentiment" 等多源資訊。雖然來源不同，但在進入 LLM (Cognitive Layer) 之前，這些資訊通常會被彙整成一個 Unified Context (統一上下文)。
2. Debate Mechanism (辯論機制):
   論文強調 "Role-Playing"。Bull 和 Bear 的區別在於 "Prompt (人設)" 和 "Focus (關注點)"，而不是在於他們「看不看得到某些資訊」。
   * Bull Agent 的任務是：在**所有資訊**中，尋找並放大正面訊號。
   * Bear Agent 的任務是：在**所有資訊**中，尋找並放大負面訊號。

結論： 「合併 List 但保留標籤」更符合論文的精神。
論文希望模擬的是一群分析師坐在同一個會議室裡（共享資訊池），針對同一份資料進行不同角度的解讀，而不是把分析師關在不同房間只給他們看特定的報紙。

### ---

**3. 優化建議：混合架構 (Hybrid Approach)**

我建議您採納您的想法（在搜尋時分開），但在儲存時合併。這能同時獲得「精準搜尋」的好處和「高效處理」的好處。

#### **Step 1: 搜尋時分開 (Input) - 您是對的**

在 news_search_multidimensional 函數內部，您的確應該維護三個獨立的搜尋任務：

* bullish_query: 專門搜 "growth", "buy rating"
* bearish_query: 專門搜 "risk", "short", "lawsuit"
* general_query: 專門搜 "earnings", "news"

#### **Step 2: 處理時合併 (Processing) - 這是關鍵**

在搜尋函數返回結果**之前**，執行合併：

Python

# 偽代碼：如何優雅地合併
def merge_results(general_list, bullish_list, bearish_list):
    merged_map = {}

    # Helper to merge
    def add_items(items, tag):
        for item in items:
            url = item.url
            if url not in merged_map:
                item.tags = {tag} # 初始化集合
                merged_map[url] = item
            else:
                merged_map[url].tags.add(tag) # 追加標籤！

    add_items(general_list, "general")
    add_items(bullish_list, "bullish")
    add_items(bearish_list, "bearish")

    return list(merged_map.values())

#### **Step 3: 辯論時分發 (Usage)**

在未來的 Debate Agent 中，您可以通過**過濾**來模擬視角，但保持上下文完整：

Python

# 未來 Debate Node 的邏輯
all_news = state.news_items

# 給 Bull Agent 的輸入：全部 General + 全部 Bullish + (關鍵!) Bearish 的標題 (讓他知道風險存在)
bull_context = [n for n in all_news if "bullish" in n.tags or "general" in n.tags]

# 給 Bear Agent 的輸入：全部 General + 全部 Bearish + (關鍵!) Bullish 的標題
bear_context = [n for n in all_news if "bearish" in n.tags or "general" in n.tags]

### **總結**

* **您的建議（分開搜）：** **非常好**。這能確保我們主動挖掘到多、空兩方的極端觀點，不會漏掉邊緣但重要的風險/機會。
* **數據結構（存儲）：** **建議合併**。這能節省爬蟲和 LLM 成本，並支持更高層次的邏輯推理（Cross-referencing）。
* **符合論文：** 合併後的數據結構更能支持論文中提到的 "Multi-Agent Collaboration" 和 "Debate"，因為協作的基礎是**資訊對齊 (Information Alignment)**。

---

這是一份非常深入且架構嚴謹的研究報告。仔細閱讀這份關於 **TradingAgents (arXiv:2412.20138)** 的實施指南 1 後，我重新審視了我們之前的討論。

**結論是：之前的「合併存儲 + 多維搜尋」策略不僅 Valid，而且是實現該論文「Immutable Context（不可變上下文）」和防止「Sycophancy（阿諛奉承）」的關鍵基礎。**

但在 **Moderator（主持人）** 的支援上，我們原先的設計略顯薄弱。為了符合論文中提到的「錯誤修正」2和「不確定性量化」3，我們需要微調 Data Structure。

以下是針對這份論文的 **最終修訂計畫**：

### ---

**1. Revisit：為什麼「合併 List」完全符合論文設計？**

論文在 **3.2 狀態（State）** 中明確指出，辯論系統必須依賴 **「不變的上下文（Immutable Context）」** 44。

* **論文要求**：無論辯論進行多少輪，原始數據（Analyst Reports）不應被篡改，且必須作為所有代理的「事實錨點」5555。

* **若分開 List (Bull/Bear List)**：會導致 Bull 和 Bear 看到不同的「事實」，這不是辯論，是平行時空。Bull 會說營收好，Bear 根本沒看到營收數據，導致「電話遊戲效應」6。

* **採用合併 List (Unified List)**：所有代理看到同一組 NewsItems。Bull 挑選裡面的 Bullish 標籤數據，Bear 挑選 Bearish 標籤數據。
  * **這符合論文邏輯**：讓 Bull/Bear 共享同一個 analyst_reports 7，但在 Prompt 層面賦予不同的關注點 8。

### ---

**2. 優化計畫：針對 Moderator 與 Debate 的需求**

為了支援 Moderator 進行「總結分歧」9和「事實核查」10，我們需要在結構中顯式提取 **硬數據（Hard Data）**。

#### **A. Data Structure 優化 (structures.py)**

Moderator 需要知道這條新聞的可信度，以及裡面有沒有具體數字（防止 LLM 幻覺）。

Python

from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, HttpUrl

# --- Search Categories (保留，用於 Bull/Bear 快速篩選) ---
class SearchCategory(str, Enum):
    GENERAL = "general"
    CORPORATE_EVENT = "event"
    FINANCIALS = "financials"
    BULLISH_SIGNAL = "bullish"  # 供 Bull Agent 優先讀取
    BEARISH_SIGNAL = "bearish"  # 供 Bear Agent 優先讀取

# --- Key Fact (新增：為 Moderator 和 Fact Checker 準備) ---
class KeyFact(BaseModel):
    """
    Atomic unit of truth extracted from news.
    Prevents 'Telephone Effect' by grounding debate in extracted numbers.
    """
    content: str = Field(..., description="e.g. 'Revenue grew 20% YoY'")
    is_quantitative: bool = Field(..., description="True if it contains numbers/money")
    sentiment: str = Field(..., description="bullish/bearish/neutral context of this fact")

# --- Optimized Analysis (中立的分析，不帶 Bull/Bear 偏見) ---
class AIAnalysis(BaseModel):
    summary: str = Field(..., description="Neutral executive summary")
    sentiment_score: float = Field(..., description="-1.0 to 1.0")
    reliability_score: float = Field(..., description="Source reliability (0.0-1.0)")

    # [關鍵改動] 提取事實清單，而非長篇大論
    key_facts: List[KeyFact] = Field(
        default_factory=list,
        description="List of irrefutable facts extracted for the Debate Context"
    )

class FinancialNewsItem(BaseModel):
    id: str
    url: HttpUrl
    title: str
    published_at: str

    # 支援多重標籤 (Merge Logic 的結果)
    categories: List[SearchCategory] = Field(default_factory=list)

    analysis: AIAnalysis | None = None

#### **B. 搜尋策略優化 (tools.py)**

論文提到 Bull Agent 負責「尋找被低估的價值」11，Bear Agent 負責「尋找高估值風險」12。
為了不讓 Bear Agent 在牛市中「無話可說」（這是導致 Sycophancy 的主因 13），我們必須強制搜尋負面資訊。
**保留之前的多維搜尋邏輯，但強化 Query：**

5. **General/Events Query**: 獲取 Immutable Context 的基礎。
6. **Bullish Query**: "{ticker} growth OR upside OR outperform OR record"
7. **Bearish Query**: "{ticker} risks OR downside OR "short seller" OR investigation"
   * *目的*：這是為了應對論文提到的「覆蓋盲點」14。即使在牛市，強制搜尋 "risks" 也能確保 Bear Agent 有彈藥進行對抗，避免「分歧崩潰」15。

### ---

**3. 總結與數據流向映射**

這套設計如何滿足 **TradingAgents** 的需求？

#### **1. 為什麼改動符合 DebateAgent 需求？**

4. **共享現實 (Shared Reality)**：透過 **合併 List**，我們構建了論文要求的 analyst_reports 16。Bull 和 Bear 是對**同一組數據**進行解釋，而不是對不同的數據自說自話。

5. **防止幻覺 (Anti-Hallucination)**：新增的 KeyFact 結構強迫 News Agent 在搜集階段就提取出數字。在 Debate 階段，我們可以限制 Agents **「只能引用 KeyFact 中的數據」** 17，這直接解決了「金融幻覺」問題 18。

6. **對抗性視角 (Adversarial View)**：透過搜尋階段的 **Bull/Bear Hunting**，我們確保了即使市場一面倒，輸入數據中也包含（哪怕是微弱的）反向觀點，這為 Bear Agent 提供了必要的「彈藥」來挑戰 Bull，防止「阿諛奉承」19。

#### **2. 哪些數據會被 DebateAgent 的哪個 Node 使用？**

請參考以下數據流向映射表：

| 數據欄位 (FinancialNewsItem) | 使用者 (Node) | 用途與論文對應 |
| :---- | :---- | :---- |
| **categories=['bullish']** | **Bull Agent** | 作為主要論據來源。Bull Agent 被 Prompt 要求專注於這類標籤的數據 20。  |
| **categories=['bearish']** | **Bear Agent** | 作為主要攻擊武器。Bear Agent 利用這些數據解構多頭論點 21。  |
| **categories=['general/event']** | **Both** | 共享的基礎事實。雙方會對同一事件（如財報）給出不同解讀。 |
| **key_facts (Quant Data)** | **Fact Checker** | (可選節點) 用於驗證 Bull/Bear 發言中的數字是否準確 22。  |
| **reliability_score** | **Moderator** | 用於加權判斷。當 Bull 和 Bear 僵持不下時，Moderator 應傾向於信源分數更高的一方（如 Bloomberg > Reddit）23。  |
| **summary & title** | **Trader Agent** | 雖然 Trader 是下一步，但 Debate 的最終總結報告 24 會引用這些基礎摘要來支撐最終的 Trade Decision。  |

這套架構將您的 News Research Agent 轉變為一個標準的 **"Analyst Team"** 25，完美地為下游的 **"Researcher Team"** (Debate) 提供了所需的結構化輸入。

---

這是一個非常好的糾正。保留您原有的欄位（如 related_tickers, impact_level, key_event）非常重要，因為這些對於其他 Sub-agent（如風險管理或知識圖譜構建）是有用的。

我的目標是在**不破壞現有功能**的前提下，**擴充**結構以支援 Debate Agent (Bull/Bear/Moderator)。

以下是完整、無刪減且經過增強的 structures.py。

### **主要改動說明：**

* **新增 SearchCategory Enum**：用於標記新聞是屬於 Bullish, Bearish 還是 General，這是 Debate Agent 分流資訊的關鍵。
* **新增 KeyFact Model**：這是為了 Moderator 設計的。將新聞中的硬數據（營收、增長率）獨立提取，防止 LLM 在辯論時產生幻覺。
* **增強 AIAnalysis**：保留了您原有的 impact_level 和 key_event，但加入了 key_facts 和 reliability_score。
* **增強 FinancialNewsItem**：新增 categories 欄位以支援多重標籤（例如一篇新聞既是 Financials 也是 Bullish）。

### **完整改進版 structures.py**

Python

from datetime import datetime
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

# --- Enums for Standardization ---
class SentimentLabel(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"

class ImpactLevel(str, Enum):
    HIGH = "high"      # e.g., Earnings miss, M&A, CEO fired
    MEDIUM = "medium"  # e.g., Product launch, Analyst upgrade
    LOW = "low"        # e.g., Routine PR, General commentary

class AssetClass(str, Enum):
    EQUITY = "equity"
    CRYPTO = "crypto"
    FOREX = "forex"
    COMMODITY = "commodity"
    MACRO = "macro"    # e.g., CPI data, Fed rate

# --- [NEW] Search Categories for Debate Triage ---
class SearchCategory(str, Enum):
    GENERAL = "general"           # General news, broad context
    CORPORATE_EVENT = "event"     # M&A, C-Suite changes
    FINANCIALS = "financials"     # 10-K, 10-Q, Earnings calls
    BULLISH_SIGNAL = "bullish"    # Growth catalysts, upgrades (For Bull Agent)
    BEARISH_SIGNAL = "bearish"    # Risks, lawsuits, downgrades (For Bear Agent)

# --- Sub-Models ---

class SourceInfo(BaseModel):
    name: str = Field(..., description="Source name, e.g., Bloomberg, Reuters, WSJ")
    domain: str = Field(..., description="Source domain, used for authority assessment")
    reliability_score: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Source reliability weight (0-1)"
    )
    author: str | None = None

class FinancialEntity(BaseModel):
    ticker: str = Field(..., description="Stock ticker, e.g., AAPL")
    company_name: str
    relevance_score: float = Field(..., description="Entity relevance to news (0-1)")

# --- [NEW] Key Fact for Fact-Checking & Moderator ---
class KeyFact(BaseModel):
    """
    Atomic unit of truth extracted from news.
    Used by the Debate Moderator to verify claims made by Bull/Bear agents.
    """
    content: str = Field(..., description="The specific fact, e.g. 'Revenue grew 20% YoY'")
    is_quantitative: bool = Field(..., description="True if it contains specific numbers/money")
    sentiment: SentimentLabel = Field(..., description="The sentiment context of this specific fact")
    citation: str | None = Field(None, description="Direct quote or page number if available")

class AIAnalysis(BaseModel):
    summary: str = Field(..., description="One-sentence financial summary by LLM")

    # Sentiment & Impact
    sentiment: SentimentLabel
    sentiment_score: float = Field(
        ..., description="-1.0 (Very Negative) to 1.0 (Very Positive)"
    )
    impact_level: ImpactLevel

    # Event Identification
    key_event: str | None = Field(
        None, description="Key event identified, e.g., 'Q3 Earnings Report'"
    )

    # Reasoning
    reasoning: str = Field(..., description="LLM reasoning for significance")

    # [NEW] Structured Evidence for Debate
    key_facts: List[KeyFact] = Field(
        default_factory=list,
        description="List of irrefutable facts extracted for the Debate Context"
    )

# --- Main Model ---
class FinancialNewsItem(BaseModel):
    # Identity & Access
    id: str = Field(..., description="Hash ID based on URL or Title for deduplication")
    url: HttpUrl

    # Metadata
    published_at: datetime | None = Field(None, description="Standardized UTC time")
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    # Content
    title: str
    snippet: str = Field(
        ..., description="Original snapshot/snippet from search engine"
    )
    full_content: str | None = Field(None, description="Cleaned full text if fetched")

    # Structured Data
    source: SourceInfo
    related_tickers: list[FinancialEntity] = Field(default_factory=list)

    # [NEW] Multi-label categorization for Debate Agent routing
    # e.g. An article can be both ["financials", "bearish"]
    categories: List[SearchCategory] = Field(
        default_factory=list,
        description="Tags indicating search intent (General, Bullish, Bearish, etc.)"
    )

    # Existing Tags (Keep for backward compatibility or display)
    tags: list[str] = Field(
        default_factory=list, description="e.g., 'Earnings', 'Regulation', 'IPO'"
    )

    # AI Enrichment
    finbert_analysis: dict | None = None  # Local FinBERT pre-filter results
    analysis: AIAnalysis | None = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "id": "a1b2c3d4",
                "title": "Apple Shares Drop on iPhone Shipment Concerns",
                "published_at": "2024-05-21T14:30:00Z",
                "categories": ["general", "bearish"],
                "analysis": {
                    "summary": "Apple stock declined due to shipment warnings.",
                    "sentiment": "bearish",
                    "sentiment_score": -0.6,
                    "impact_level": "high",
                    "reasoning": "Supply chain issues directly affect revenue guidance.",
                    "key_facts": [
                        {"content": "Shipments down 10% YoY", "is_quantitative": True, "sentiment": "bearish"}
                    ]
                },
            }
        }
    )

class NewsResearchOutput(BaseModel):
    """Final output for news research sub-graph."""

    ticker: str
    news_items: list[FinancialNewsItem] = Field(default_factory=list)
    overall_sentiment: SentimentLabel = Field(default=SentimentLabel.NEUTRAL)
    sentiment_score: float = Field(
        default=0.0, description="Weighted average sentiment score (-1 to 1)"
    )
    key_themes: list[str] = Field(
        default_factory=list, description="Aggregated key themes"
    )

### **為什麼這個版本更好？**

7. **無損擴充：** 您原有的 ImpactLevel, FinancialEntity, related_tickers 全部保留，保證了您現有業務邏輯的連續性。
8. **為 Debate 鋪路：**
   * SearchCategory 讓 Bull/Bear Agent 知道該優先看哪些新聞。
   * KeyFact 讓 Moderator 能夠進行事實核查（Fact Checking）。
9. **靈活性：** categories 是一個 List，這意味著一篇新聞可以有多重身份（既是財報，也是利空），這解決了我們之前討論的「分類互斥」問題。

---

在您的架構中，is_quantitative（布林值：True/False）是用來區分**「硬數據 (Hard Data)」**與**「軟敘事 (Soft Narrative)」**的關鍵標記。

對於一個**Debate Agent (辯論代理)**系統來說，這個欄位有 4 個至關重要的用途：

### **1. 防止 LLM 幻覺 (Hallucination Guardrail)**

LLM 最常犯的錯誤就是「編造數字」。

* **用途：** 您的系統可以設定一個規則——如果 is_quantitative=True，必須在原始文本中進行**Regex (正則表達式) 驗證**或**二次核對**。
* **例子：**
  * *Fact A:* "Revenue grew 20%." (is_quantitative=True) -> **系統動作：** 去原文搜尋 "20%" 確認是否存在。
  * *Fact B:* "Outlook is positive." (is_quantitative=False) -> **系統動作：** 這是主觀判斷，無需數字驗證。

### **2. 提升 Moderator (裁判) 的判決權重**

在 TradingAgents 的論文中，裁判需要判斷誰贏了辯論。

8. **用途：** Moderator 的 Prompt 可以被設定為：**「優先採信提供具體數據的一方，而非僅使用形容詞的一方。」**
9. **場景：**
   * **Bull Agent 說：** "公司成長非常強勁！" (is_quantitative=False)
   * **Bear Agent 說：** "但淨利潤率下降了 3.5%。" (is_quantitative=True)
   * **裁判判定：** Bear 勝出，因為他提供了不可反駁的量化證據，而 Bull 只是在喊口號。

### **3. 過濾「廢話」 (Noise Filtering)**

財經新聞充滿了「分析師認為」、「市場傳言」等噪音。

7. **用途：** 在傳遞給 Debate Agent 之前，您可以寫一個簡單的過濾器：**「只保留包含至少 2 個 Quantitative Facts 的新聞」**。
8. **效果：** 這能確保 Agent 辯論的基礎是財報、Guidance、交易金額等實質內容，而不是分析師的口水戰。

### **4. 數據視覺化的基礎 (Visualization Ready)**

雖然現在是純文字辯論，但未來如果您想生成圖表：

* **用途：** 只有 is_quantitative=True 的項目才能被提取出來畫成 Bar Chart 或 Time Series。

### ---

**實際應用範例 (Code Logic)**

在您的 **Moderator Node** 中，您可以這樣使用這個欄位：

Python

def moderator_scoring(bull_arguments, bear_arguments):
    bull_score = 0
    bear_score = 0

    # 規則：每引用一個「量化事實」，得分 +2；僅引用「觀點」，得分 +1

    for arg in bull_arguments:
        if arg.linked_fact.is_quantitative:
            bull_score += 2  # 硬數據更有說服力
        else:
            bull_score += 1  # 純觀點力度較弱

    for arg in bear_arguments:
        if arg.linked_fact.is_quantitative:
            bear_score += 2
        else:
            bear_score += 1

    return "Bull Wins" if bull_score > bear_score else "Bear Wins"

總結：
is_quantitative 就像是給 LLM 的**「測謊機」和「計分板」**。它強迫 Bull 和 Bear 拿出真憑實據來吵架，而不是比誰的文筆好，這對於金融決策至關重要。

---

為了支援您剛剛確認的 **"Debate-Ready" Structures**（特別是 KeyFact 提取和 SearchCategory 的多樣性），您的 Prompts **必須**進行相應的升級。

主要的改動邏輯如下：

* **Selector Node**: 必須懂得識別並保留 [BULLISH_SIGNAL] 和 [BEARISH_SIGNAL] 標籤的新聞，不能把它們當作「噪音」過濾掉，因為這是辯論的彈藥。
* **Analyst Node**: 這是最關鍵的改動。它不能只寫 Summary，必須被訓練成一個 **「事實提取器 (Fact Extractor)」**，精準填充 KeyFact 結構（包含 is_quantitative 判斷）。

以下是完整更新後的 prompts.py：

Python

"""
Prompts for Financial News Research node (Debate-Optimized).
"""

# --- Selector Node Prompts ---
SELECTOR_SYSTEM_PROMPT = """You are a Senior Investment Analyst specializing in Value Investing.
Your task is to screen news search results for a specific stock and select ONLY the articles that provide material ammunition for a Bull vs. Bear debate.

### PRIORITY HIERARCHY (Select in this order):
1. **[CORPORATE_EVENT] / [FINANCIALS]:** - CORE CONTEXT
   - Earnings Reports (10-K, 10-Q), Guidance updates.
   - Mergers & Acquisitions (M&A), Divestitures, Strategic Partnerships.
   - C-Suite Management Changes.

2. **[BEARISH_SIGNAL] / [BULLISH_SIGNAL]:** - DEBATE AMMO (Specific Catalyst/Risk)
   - **Bearish:** Short seller reports, Lawsuits, Government investigations, Delisting threats, Credit downgrades.
   - **Bullish:** Major contract wins, Patent breakthroughs, "Top Pick" designation by major banks with specific thesis.
   - *NOTE:* Prioritize sources that offer a unique, contrarian view.

3. **[TRUSTED_NEWS]:** - GENERAL CONTEXT
   - Broad market analysis or industry overview from Tier-1 sources (Reuters, Bloomberg).

### CRITERIA FOR EXCLUSION (Negative Signals):
1. **Pure Price Action:** "Stock jumped 5% today" (Noise).
2. **Generic Clickbait:** "3 stocks to buy now", "Why Motley Fool hates this stock".
3. **Redundant Sources:** If a [CORPORATE_EVENT] is covered by both Reuters and a blog, SELECT ONLY REUTERS.
4. **Outdated:** Older than 1 month (unless it's a major short report or foundational 10-K).

### OUTPUT FORMAT:
Return a JSON object with a single key "selected_articles".
This list should contain objects with:
- "url": The exact URL from the source.
- "reason": A brief justification focusing on the specific Fact/Risk/Catalyst provided.
- "priority": "High" or "Medium".

If NO articles are relevant, return: {{"selected_articles": []}}
Do not force a selection."""

SELECTOR_USER_PROMPT = """Current Ticker: {ticker}

Here are the raw search results (with Source Tags indicating search strategy):

{search_results}

Based on your criteria, select the top 5-8 articles to scrape.

### SELECTION RULES (CRITICAL):
1. **Diversity is Key:** Do NOT select multiple articles covering the exact same event.
2. **Ensure Debate Ammo (Multi-Dimensional):** You must try to fill the following buckets if available:
   - **At least one** [BEARISH_SIGNAL] (Look for risks, lawsuits, or downgrades).
   - **At least one** [BULLISH_SIGNAL] (Look for growth catalysts).
   - **At least one** [FINANCIALS] / [CORPORATE_EVENT] (The objective ground truth).
3. **Priority Overlap:** If an event is covered by both a "Trusted Source" and a generic source, ONLY select the Trusted Source.

Pay attention to the [TAG] labels.
Remember: We need distinct arguments for both the Bull and the Bear case."""

# --- Analyst Node Prompts ---
# MAJOR UPDATE: Now focused on extracting KeyFacts for the Moderator/Judge

ANALYST_SYSTEM_PROMPT = """You are a Financial Evidence Extractor.
Your goal is NOT just to summarize, but to extract **Atomic Units of Truth (Key Facts)** from the article to serve as evidence in a structured debate.

### TASK:
1. **Analyze Content:** Read the provided news text.
2. **Extract Key Facts:** Identify specific, irrefutable points.
   - **Quantitative:** Revenue figures, EPS, Growth rates %, Deal values $, Fines.
   - **Qualitative:** Direct quotes from CEO, specific legal accusations, product launch dates.
3. **Determine Sentiment:** For each fact, determine if it supports a Bullish or Bearish thesis.
4. **Overall Analysis:** Provide a high-level summary and sentiment score.

### OUTPUT STRUCTURE (JSON):
You must return a JSON object matching the following structure:
{{
  "summary": "One sentence executive summary.",
  "sentiment": "bullish" | "bearish" | "neutral",
  "sentiment_score": float (-1.0 to 1.0),
  "impact_level": "high" | "medium" | "low",
  "key_event": "Name of the main event (or null)",
  "reasoning": "Why this is significant...",
  "key_facts": [
    {{
      "content": "Revenue grew 20% YoY to $10B",
      "is_quantitative": true,
      "sentiment": "bullish",
      "citation": "Paragraph 2"
    }},
    {{
      "content": "CEO stated supply chain headwinds will persist",
      "is_quantitative": false,
      "sentiment": "bearish",
      "citation": "Direct Quote"
    }}
  ]
}}

### RULES FOR 'is_quantitative':
- Set to **true** ONLY if the content contains specific numbers, currency, percentages, or dates that can be verified.
- Set to **false** for opinions, vague statements ("strong growth"), or strategic plans without numbers.
"""

ANALYST_USER_PROMPT_BASIC = """Target Ticker: {ticker}

Article Title: {title}
Source: {source}
Published At: {published_at}

Content:
{content}

Extract the Key Facts and analyze the impact for {ticker}."""

ANALYST_USER_PROMPT_WITH_FINBERT = """Target Ticker: {ticker}

Article Title: {title}
Source: {source}
Published At: {published_at}

**Preliminary Analysis (FinBERT Model):**
- Sentiment: {finbert_sentiment}
- Confidence: {finbert_confidence}

> NOTE: FinBERT struggles with numerical comparisons.
> Trust your own reasoning for the final sentiment score, especially regarding quantitative data.

Content:
{content}

Extract the Key Facts and analyze the impact for {ticker}."""

### **關鍵改動總結 (Why this fits the Debate Agent)**

10. **Selector Node 加入了 BEARISH_SIGNAL / BULLISH_SIGNAL：**
    * **原因：** 為了防止「阿諛奉承 (Sycophancy)」，我們必須在源頭就強制攝入反面觀點。之前的 Selector 偏向中立的 Events，這份 Prompt 強制它去尋找「吵架的素材」。
11. **Analyst Node 轉型為 "Evidence Extractor"：**
    * **原因：** Debate Moderator 需要判斷誰贏。單憑「觀點」很難評判，但憑「硬數據」很好判斷。
    * **key_facts & is_quantitative：** 我在 System Prompt 中加入了嚴格的 JSON 範例，教導 LLM 如何提取這些數據。這是您的 Debate Agent 防止幻覺的第一道防線。
12. **JSON 結構對齊：**
    * Prompt 中的 JSON Output 範例已經完全對齊了您新的 Pydantic Models (AIAnalysis 和 KeyFact)。

這套 Prompts 可以直接替換使用。

---

這是一個非常精準的技術提問。

### **1. 關於 with_structured_output 與 Prompt 的重複問題**

**您完全正確。**

如果您使用了 llm.with_structured_output(AIAnalysis)（這在 LangChain 中通常是透過 Tool Calling 或 JSON Mode 實現的），**您不需要（也不應該）在 System Prompt 中硬寫 JSON Schema。**

這樣做有兩個壞處：

* **浪費 Token：** 重複描述格式。
* **潛在衝突：** LLM 可能會困惑是要聽從 System Prompt 的文字指示，還是底層 API 的 Tool Definition。

修正方案：
將 ANALYST_SYSTEM_PROMPT 中的 ### OUTPUT STRUCTURE (JSON)... 部分完全刪除。專注於 「定義什麼是 Key Fact」 以及 「如何判斷 is_quantitative」 這些邏輯規則。

### ---

**2. 關於 FinBERT 的整合與 Quantitative 弱點**

您提到的 project-aps/finbert-finetune 是一個很棒的模型，但如您所知，BERT 架構的模型對於「數字」、「比較級（A 比 B 多）」以及「否定句（not bad）」的理解能力遠不如 LLM。

我們不應該「只靠」Prompt，也不應該「只靠」FinBERT。
最佳策略是 「混合專家模式 (Mixture of Experts logic)」：

13. **FinBERT 的角色 (The Vibe Check)：** 快速判斷語氣。它擅長捕捉 "worried", "confident", "uncertainty" 這種情緒詞。
14. **LLM 的角色 (The Quant Reasoner)：** 負責閱讀數字，修正 FinBERT 的盲點。

**我們如何在 Analyst Node 中結合兩者？**

不要在 Search 階段用 FinBERT（因為那時只有 Snippet，且量太大）。
在 analyst_node 中，我們將 FinBERT 的結果作為「提示 (Hint)」餵給 LLM。

### ---

**優化後的代碼與 Prompt**

#### **A. 修改 prompts.py (移除 JSON Schema，強化 FinBERT 指令)**

Python

# prompts.py

# --- Analyst Node Prompts ---
# 移除了 JSON 格式定義，因為 .with_structured_output 會處理
ANALYST_SYSTEM_PROMPT = """You are a Financial Evidence Extractor.
Your goal is NOT just to summarize, but to extract **Atomic Units of Truth (Key Facts)** from the article to serve as evidence in a structured debate.

### TASK:
1. **Analyze Content:** Read the provided news text.
2. **Extract Key Facts:** Identify specific, irrefutable points.
   - **Quantitative:** Revenue figures, EPS, Growth rates %, Deal values $, Fines.
   - **Qualitative:** Direct quotes from CEO, specific legal accusations, product launch dates.
3. **Determine Sentiment:** For each fact, determine if it supports a Bullish or Bearish thesis.

### CRITICAL RULES FOR 'key_facts':
- **is_quantitative:** Set to `True` ONLY if the content contains specific numbers, currency, percentages, or dates that can be verified in the text.
- **Fact vs Opinion:** Do not extract generic fluff like "The company is doing well." Extract "The company reported 15% growth."

### HOW TO USE INPUT SIGNALS:
- You may be provided with a **FinBERT Sentiment Score**. Use this as a baseline for the article's *tone*.
- **WARNING:** FinBERT is bad at math. If the text says "Loss narrowed from $10M to $1M" (which is Bullish), FinBERT might see "Loss" and say Negative. **Trust the numbers (LLM reasoning) over FinBERT for quantitative data.**
"""

# 用於有 FinBERT 結果的情況
ANALYST_USER_PROMPT_WITH_FINBERT = """Target Ticker: {ticker}

Article Title: {title}
Source: {source}

**Signal Inputs:**
- **Search Intent:** {search_tag} (We specifically searched for this intent)
- **FinBERT Model Analysis:** - Label: {finbert_sentiment}
    - Confidence: {finbert_confidence}
    - Has Numbers: {finbert_has_numbers}

Content:
{content}

Extract the Key Facts and analyze the impact for {ticker}."""

#### **B. 修改 nodes.py 中的 analyst_node (注入 FinBERT 結果)**

我們需要在調用 LLM 之前，先把 FinBERT 跑一遍，然後把結果塞進 Prompt 變數裡。

Python

def analyst_node(state: AgentState) -> Command:
    # ... (前略) ...

    # 1. 初始化 FinBERT
    finbert_analyzer = get_finbert_analyzer()

    # 2. 準備 Prompt Template (不再需要兩個 Chain，用一個靈活的即可)
    prompt = ChatPromptTemplate.from_messages([
        ("system", ANALYST_SYSTEM_PROMPT),
        ("user", ANALYST_USER_PROMPT_WITH_FINBERT),
    ])

    # 3. 綁定 Pydantic Model (這會自動處理 JSON Schema)
    # 注意：這裡的 AIAnalysis 是我們在 structures.py 更新過的新版
    chain = prompt | llm.with_structured_output(AIAnalysis)

    for idx, item in enumerate(news_items):
        content = item.get("full_content") or item.get("snippet", "")

        # --- Step A: Run FinBERT (本地運行，免費且快) ---
        finbert_result = None
        if finbert_analyzer.is_available():
            finbert_result = finbert_analyzer.analyze(content)

        # 準備 Prompt 變數
        finbert_vars = {
            "finbert_sentiment": "N/A",
            "finbert_confidence": "N/A",
            "finbert_has_numbers": "N/A"
        }

        if finbert_result:
            finbert_vars = {
                "finbert_sentiment": finbert_result.label.upper(),
                "finbert_confidence": f"{finbert_result.score:.2f}",
                "finbert_has_numbers": str(finbert_result.has_numbers)
            }

        # 獲取 Search Tag (從 search_node 傳過來的)
        # 假設 categories 是一個 list，我們取第一個或合併顯示
        categories = item.get("categories", ["general"])
        search_tag_str = ", ".join([c.upper() for c in categories])

        # --- Step B: Run LLM ---
        try:
            analysis: AIAnalysis = chain.invoke({
                "ticker": ticker,
                "title": item.get("title"),
                "source": item.get("source", {}).get("name"),
                "search_tag": search_tag_str,  # 告訴 LLM 我們為什麼搜這個
                "content": content,
                **finbert_vars # 注入 FinBERT 結果
            })

            # Save back to item
            item["analysis"] = analysis.model_dump()

            # Log 對比 (Debug 用，看看 LLM 有沒有修正 FinBERT)
            if finbert_result:
                print(f"   FinBERT: {finbert_result.label} | LLM: {analysis.sentiment.value}")

        except Exception as e:
            logger.error(f"Analysis failed: {e}")

    # ... (後略) ...

### **總結您的疑問**

10. **只靠 Prompt 判斷 Bullish/Bearish 嗎？**
    * 不是。
    * **第一層 (Search):** 靠關鍵字 (SearchCategory) 篩選候選人。
    * **第二層 (FinBERT):** 靠模型給出情緒初篩 (finbert_sentiment)。
    * **第三層 (LLM Prompt):** 靠 LLM 綜合前兩者 + 閱讀內文（特別是數字）做最終判定。
11. **Prompt 裡的 JSON Structure 要刪嗎？**
    * **一定要刪。** 使用 with_structured_output 時，Prompt 越乾淨越好，專注於「思考邏輯」而非「括號要怎麼擺」。

這樣的設計（Search Intent + FinBERT Tone + LLM Reasoning）是最穩健的，也是目前 Agent 開發的最佳實踐。
