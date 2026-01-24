# **LangGraph 代理系統架構現代化研究報告：解耦、持久化與協議標準化**

## **執行摘要 (Executive Summary)**

隨著大型語言模型（LLM）編排框架的快速演進，代理（Agentic）應用程式的架構正規性已從實驗性質的原型開發，轉向對軟體工程原則的嚴格要求。本研究報告旨在回應針對現有 server.py（後端）與 useAgent.ts（前端）實作的深度技術審查。目前的系統雖然具備基礎功能，但在架構上表現出「原型軟體」的典型特徵：高強度的前後端耦合、脆弱的事件流處理機制、非確定性的狀態管理，以及缺乏生產級的持久化方案。

本報告基於軟體架構的關注點分離（Separation of Concerns）原則，並整合 LangGraph 框架的最新研究成果，提出了一套全面的重構藍圖。分析指出，目前的系統存在「名稱連動性（Connascence of Name）」與「演算法連動性（Connascence of Algorithm）」，即前端對後端圖結構（Graph Topology）與節點名稱（如 aggregator_node）擁有過度的內部知識。此外，依賴內存（In-Memory）的 asyncio.Task 進行任務管理，使得系統在面對服務重啟或崩潰時極其脆弱，無法支援長運行（Long-running）的非同步任務。

為了根治這些系統性風險，本報告圍繞四個核心研究主題展開：標準化事件通訊協議（Standardized Event Protocols）、解耦狀態機設計（Decoupled State Machine）、強健的持久化與人機迴路（HITL）實踐，以及通用代理 UI 框架（Generic Agent UI Framework）。透過引入伺服器驅動 UI（Server-Driven UI, SDUI）範式、基於 Postgres 的持久化檢查點機制，以及嚴格定義的事件 Schema，我們將展示如何將現有系統轉型為一個可擴展、高容錯且具備「零前端代碼修改」擴充能力的現代化代理平台。

## ---

**第一章 現狀與架構病理分析 (Architectural Pathology Analysis)**

在深入探討解決方案之前，必須對現有架構的病理進行精確的解剖。目前的 server.py 與 useAgent.ts 之間的交互模式，揭示了分散式系統設計中常見的反模式（Anti-patterns）。這些問題並非單純的程式碼品質問題，而是架構層面的結構性缺陷。

### **1.1 「上帝視角」與名稱連動性 (The "God View" and Connascence of Name)**

前端代碼 useAgent.ts 目前扮演了「全知者」的角色，這違反了最小知識原則（Principle of Least Knowledge）。程式碼中充斥著對特定後端節點名稱（如 aggregator_node、semantic_translate）的硬編碼檢查。在軟體工程理論中，這被稱為「名稱連動性」。

* **脆弱性分析**：當後端工程師為了語義清晰度將 aggregator_node 重構為 summary_supervisor 時，前端應用程式將立即崩潰，因為前端邏輯依賴於字串比對來決定 UI 行為。這種緊密耦合導致後端重構成本極高，並阻礙了系統的快速迭代。
* **隱性依賴**：前端不僅知道節點的名稱，還隱含地知道節點的執行順序與邏輯意義。這意味著業務邏輯洩漏到了展示層（Presentation Layer），導致前端變得臃腫且難以維護。

### **1.2 脆弱的序列化策略：散彈槍解析 (Shotgun Parsing)**

後端 server.py 中的 _broadcast 函數與 json_serializable 輔助函數展示了一種被稱為「散彈槍解析」的反模式 1。

* **缺乏統一契約**：系統試圖在運行時動態地將各種類型的 Python 對象（Enums, Pydantic Models, Datetimes）強制轉換為 JSON。這種「Try-Catch」式的序列化策略缺乏嚴格的類型契約（Schema Contract）。
* **風險**：當引入新的數據類型或複雜的嵌套結構時，這種脆弱的序列化邏輯極易失效，導致前端接收到格式錯誤的數據或缺少關鍵字段的 JSON，進而引發「白屏」錯誤 2。缺乏標準化的數據傳輸對象（DTO）使得前後端通訊如同在走鋼索。

### **1.3 狀態管理的「拔河」效應 (State Tug-of-War)**

當前的狀態管理呈現出一種「雙腦」現象。後端透過過濾 Hidden Nodes 來決定發送什麼，而前端則透過 applyStatusUpdates 中的防禦性代碼來防止狀態「倒退」（Regression）。

* **競態條件 (Race Conditions)**：由於缺乏邏輯時鐘（Logical Clock）或序列號，前端無法判斷事件的先後順序。當並行節點同時發送更新時，前端被迫編寫複雜的邏輯來猜測當前的「真實」狀態。
* **狀態不一致**：後端認為代理正在「運行中」，而前端可能因為漏掉了一個事件或處理順序錯誤，顯示代理為「閒置」。這種認知不同步是導致用戶體驗低下的主因 3。

### **1.4 持久化的缺失：重新發明輪子**

目前的 JobManager 是一個基於 asyncio.Task 的內存實現。這在原型階段尚可接受，但在生產環境中是致命的缺陷。

* **數據易失性**：一旦伺服器重啟、部署新版本或發生崩潰，所有正在運行的代理任務狀態將瞬間丟失。對於需要數小時甚至數天的人機協作任務（如等待人工審批），這是不可接受的。
* **忽略原生能力**：LangGraph 本身設計了強大的 Checkpointing 機制 4，能夠將圖的狀態序列化到資料庫中。目前的實現忽略了這一核心功能，轉而使用脆弱的內存管理，這是一種典型的「重新發明輪子」且品質較差的行為。

## ---

**第二章 研究題目 1：標準化事件通訊協議 (Standardized Event Protocol)**

為了解決前後端耦合與脆弱的事件流問題，我們必須定義一個嚴格的、類型安全的通訊協議。這不僅是數據格式的規範，更是前後端互動的契約。

### **2.1 LangGraph 串流模式的深度解析**

LangGraph 提供了多種原生的串流模式（Streaming Modes），理解它們的差異是設計協議的基礎。根據研究文獻 3，我們必須選擇正確的模式組合來滿足不同的 UI 需求。

| 串流模式 (Mode) | 數據負載 (Payload) | 適用場景 | 架構優勢 | 架構劣勢 |
| :---- | :---- | :---- | :---- | :---- |
| **Updates** | 狀態增量 (Deltas) | 進度條、日誌監控 | 頻寬效率極高，僅傳輸變更部分。 | 前端需維護複雜的合併邏輯，容易產生狀態漂移。 |
| **Values** | 完整狀態快照 (Snapshots) | 狀態同步、除錯視圖 | 冪等性（Idempotent），確保前端擁有絕對真理。 | 數據量較大，頻繁傳輸可能造成網路負擔。 |
| **Messages** | LLM Token 片段 | 打字機效果、即時對話 | 提供最即時的視覺反饋。 | 需要專門的處理邏輯來聚合 Token。 |
| **Custom** | 自定義信號 | 進度通知、特定 UI 指令 | 靈活性最高，支援 Server-Driven UI。 | 需要在圖節點中顯式編寫發送邏輯。 |

**架構決策**：我們不應單一依賴某種模式，而應採用 **混合模式**。對於 LLM 生成使用 messages 模式；對於關鍵節點的狀態變更使用 values 模式以確保一致性；對於工具調用與中間邏輯，則利用 astream_events(version="v2") API 8 來捕獲細粒度的執行細節。

### **2.2 統一代理事件協議 (Unified Agent Protocol) 的設計**

為了取代雜亂的 JSON，我們建議採用類似 CloudEvents 或 AG-UI 10 的標準化 Schema。後端不應直接轉發 LangGraph 的內部事件，而應將其封裝為統一的 AgentEvent 對象。

#### **2.2.1 協議結構定義 (Protocol Schema)**

以下是建議的 AgentEvent Pydantic 定義，這將成為前後端的共享契約：

Python

from pydantic import BaseModel, Field
from typing import Any, Literal, Optional, Dict
from datetime import datetime
import uuid

class AgentEvent(BaseModel):
    """
    標準化代理事件協議
    此模型定義了後端發送給前端的所有數據結構，確保類型安全與可擴展性。
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="事件唯一標識符")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="事件發生時間")
    thread_id: str = Field(..., description="對話線程 ID")
    run_id: str = Field(..., description="執行流 ID")
    seq_id: int = Field(..., description="邏輯時鐘序列號，用於前端排序與去重")

    # 事件類型鑑別器 (Discriminator)
    type: Literal

    # 來源標識 (已解耦，不使用內部 Node Name)
    source: str = Field(..., description="例如 'sub-agent:researcher'，而非 'aggregator_node'")

    # 數據負載
    data: Dict[str, Any] = Field(default_factory=dict)

    # 元數據 (用於追蹤與除錯)
    metadata: Optional] = None

#### **2.2.2 事件分類詳解**

1. **控制平面事件 (ControlEvent)**：包括 lifecycle.* 與 interrupt.request。這些事件控制 UI 的整體狀態（如顯示加載動畫、彈出審批模態框）。
2. **數據平面事件 (StateEvent)**：state.update。後端負責將內部的 {"repo_analysis":...} 映射為 UI 理解的 {"analysisResult":...}，從而隔離內部實現細節。
3. **串流平面事件 (TokenEvent)**：content.delta。這來自於 stream_mode="messages"，專門用於渲染打字機效果。
4. **展示平面事件 (RenderEvent)**：ui.render。這是實現 Server-Driven UI 的關鍵，後端指示前端渲染特定組件（詳見第四章）。

### **2.3 傳輸層實作：SSE vs WebSockets**

雖然目前系統試圖手動廣播，但研究顯示 **Server-Sent Events (SSE)** 是此類單向狀態流的最佳實踐 1。

* **選擇 SSE 的理由**：LangGraph 的執行模型本質上是「請求-響應」的變體（長響應）。WebSockets 引入了雙向通訊的複雜性（心跳、重連、狀態同步），而對於代理的狀態推播，SSE 更加輕量且符合 HTTP 語義。前端只需透過標準的 EventSource 或 fetch API 監聽事件流，並透過獨立的 POST 請求發送指令（如提交審批）。

**重構建議**：

後端應放棄手動的 json_serializable 循環，改用 Pydantic 的 model_dump_json() 結合 FastAPI 的 StreamingResponse，確保所有輸出的 JSON 都嚴格符合上述 Schema。

## ---

**第三章 研究題目 2：前後端解耦的狀態機設計 (Decoupled State Machine Architecture)**

目前的 useAgent.ts 試圖透過簡單的變量和 if/else 邏輯來管理複雜的非同步狀態，這導致了「狀態焦慮」——前端必須不斷猜測後端的真實狀態。

### **3.1 有限狀態機 (FSM) 的引入**

為了解決狀態管理的混亂，前端必須轉變為一個 **確定性有限自動機 (DFA)**。我們不應在 UI 組件中分散管理 useState，而應使用 **XState** 或 React 的 useReducer 來集中管理代理的生命週期 12。

#### **3.1.1 抽象生命週期狀態 (Abstracted Lifecycle States)**

前端狀態機應定義高層次的語義狀態，這些狀態與後端的具體節點無關：

1. **Idle (閒置)**：系統就緒，無活動任務。
2. **Connecting (連接中)**：API 請求已發送，等待首個字節。
3. **Processing (處理中)**：這是最複雜的複合狀態，可細分為：
   * Reasoning：接收到 content.delta，顯示思考過程。
   * Executing：接收到 tool.call，顯示工具調用狀態。
   * Reviewing：接收到子代理的 state.update。
4. **AwaitingInput (等待輸入)**：接收到 interrupt.request，UI 鎖定並彈出表單。
5. **Terminated (終止)**：
   * Success：任務成功完成。
   * Failed：發生錯誤。

### **3.2 「氣泡式」狀態聚合機制 (Bubble-Up Aggregation)**

針對您提到的挑戰：「當 Sub-Agent 在跑的時候，Parent Agent 的狀態是什麼？」，解決方案是建立 **分層狀態聚合** 機制。

* **後端責任**：後端發送的事件必須包含路徑信息（Path Awareness）。例如，一個來自 search_node 的事件應標記為 source: "researcher:google_search".
* **前端聚合**：
  前端的狀態機（或 Reducer）接收到此事件後，執行以下邏輯：
  1. 更新 GoogleSearch 組件的狀態為 Running。
  2. 將 Researcher 父容器的狀態標記為 Active。
  3. 將全局頂部狀態欄更新為 Processing: Researching...。

這種機制允許 UI 在宏觀層面顯示「正在進行財務分析」，而在微觀層面（如果用戶展開詳情）顯示具體的「正在執行 SQL 查詢」，從而實現了資訊的 **多解析度顯示 (Multi-resolution Display)**，且無需前端硬編碼節點關係。

### **3.3 解決競態條件與狀態回退**

針對前端目前被迫寫防禦性代碼來防止狀態「倒退」的問題，標準化協議中的 seq_id（序列號）是關鍵。

**實作策略**：

在前端的 Reducer 中，維護一個 last_processed_seq_id。

TypeScript

function agentReducer(state, action) {
    // 丟棄過期或亂序的事件，保證單調遞增
    if (action.seq_id <= state.last_processed_seq_id) return state;

    //... 處理邏輯
    return {...newState, last_processed_seq_id: action.seq_id };
}

這實現了 **單向數據流 (Uni-directional Data Flow)**：後端 -> SSE 事件流 -> 客戶端適配器 -> Dispatch Action -> Reducer -> UI 渲染。UI 不再「猜測」狀態，而是成為後端狀態的精確投影。

## ---

**第四章 研究題目 3：LangGraph 持久化與人機迴路 (HITL) 的最佳實踐**

目前的 JobManager 是一個危險的設計，它將系統的可靠性寄託於伺服器進程的存活。為了實現生產級的穩定性，必須引入真正的持久化層。

### **4.1 基於 Postgres 的持久化架構**

LangGraph 的核心優勢之一是其原生的 Checkpointing 機制 4。透過引入 PostgresSaver（或 AsyncPostgresSaver），我們可以將圖的狀態完全卸載到資料庫中。

#### **4.1.1 Checkpointer 的工作原理**

Checkpointer 在圖的每一個「超步（Super-step）」結束後，會自動將當前的 State 快照序列化並寫入 Postgres。

* **表格結構**：包含 thread_id、checkpoint_id、parent_checkpoint_id 以及序列化後的狀態二進位數據（通常使用 Pickle 或 JSON）。
* **災難恢復**：如果伺服器在執行過程中崩潰，重啟後的服務只需讀取該 thread_id 的最新 Checkpoint，即可從中斷點無縫恢復執行，完全無需用戶感知。

**架構遷移**：

必須廢除 JobManager。後端 API 不應再生成臨時的 Job ID，而應接受或生成持久化的 thread_id。所有的狀態查詢都應直接針對 Checkpointer 進行，而非查詢內存中的 Task 對象。

### **4.2 現代化的人機迴路 (HITL) 模式**

目前的代碼使用手動的 snapshot.next 檢查，這是一種過時且容易出錯的模式。LangGraph V0.2+ 引入了動態的 interrupt 函數 15。

#### **4.2.1 動態中斷 (interrupt() function) vs 靜態斷點**

舊模式要求在編譯圖（Compile Graph）時預先定義 interrupt_before=["node_b"]。新模式允許在節點邏輯內部動態觸發中斷：

Python

# 現代化寫法
def human_review_node(state):
    if state["confidence"] < 0.8:
        # 觸發中斷，並將 payload 傳送給前端
        feedback = interrupt({
            "type": "approval_required",
            "message": "信心不足，請審核",
            "context": state["summary"]
        })
        # 恢復後，feedback 將包含前端傳回的數據
        return {"review_decision": feedback}
    return {"review_decision": "auto_approved"}

這種模式的優勢在於它將控制流邏輯保留在節點內部，而不是洩漏到圖的定義中。

#### **4.2.2 恢復執行 (Resuming Execution)**

恢復執行的流程必須標準化：

1. **中斷發生**：後端發送 interrupt.request 事件。
2. **用戶操作**：前端根據 Payload 渲染表單，用戶填寫後提交。
3. **發送指令**：前端發送 POST 請求至 /threads/{thread_id}/run，攜帶 Command(resume=user_input)。
4. **圖恢復**：LangGraph 載入 Checkpoint，將 user_input 注入到觸發中斷的 interrupt() 函數返回值中，並繼續執行後續邏輯。

這徹底消除了前端手動管理「暫停」狀態的需求，將流程控制權交還給 LangGraph 運行時。

## ---

**第五章 研究題目 4：通用代理 UI 框架 (Generic Agent UI Framework)**

本報告的終極目標是實現「零前端代碼修改」的代理擴展能力。這需要引入 **伺服器驅動 UI (Server-Driven UI, SDUI)** 的概念 11。

### **5.1 代理註冊表與 Schema 驅動**

後端應建立一個代理註冊表（Agent Registry），每個代理不僅定義其執行圖，還必須定義其 **介面契約 (Interface Contracts)**。這些契約基於 Pydantic 模型，並可自動轉換為 JSON Schema 17。

1. **輸入契約 (Input Schema)**：定義啟動代理所需的參數（如 { topic: str, max_depth: int }）。
2. **中斷契約 (Interrupt Schema)**：定義人機互動所需的數據結構。
3. **輸出契約 (Artifact Schema)**：定義代理最終產出的結構化數據。

### **5.2 實現「笨」渲染器 (The "Dumb" Renderer)**

前端應用應轉變為一個通用的渲染引擎，不再包含特定業務邏輯（如「如果是新聞代理，則顯示新聞卡片」）。

#### **5.2.1 動態表單生成 (Dynamic Form Generation)**

針對 HITL 場景，前端應整合 react-jsonschema-form (RJSF) 19。

* **流程**：
  1. 後端 interrupt() 發送 Payload：{ "kind": "form", "schema": BudgetApproval.model_json_schema() }。
  2. 前端接收事件，識別 kind: "form"。
  3. 前端將 schema 傳遞給 <Form schema={event.schema} /> 組件。
  4. RJSF 自動渲染出包含驗證邏輯的表單（如數字輸入框、下拉選單）。
  5. 用戶提交後，JSON 數據直接回傳後端。

這意味著，後端工程師只需修改 Python 中的 Pydantic 模型，前端的審批表單就會自動更新，完全無需前端工程師介入。

#### **5.2.2 生成式 UI (Generative UI) 與組件映射**

對於更複雜的視覺化需求（如圖表、地圖），我們可以採用組件映射策略 21。

* **前端註冊表**：維護一個基礎組件庫（Chart, Table, Map, Markdown）。
* **後端指令**：
  JSON
  {
    "type": "ui.render",
    "component": "FinancialTable",
    "props": { "rows": [...], "columns": [...] }
  }

* **渲染邏輯**：前端根據 component 字符串查找對應的 React 組件並注入 props。這實現了 UI 的高度動態化，後端可以決定何時顯示何種組件。

## ---

**第六章 實施藍圖與遷移策略 (Implementation Roadmap)**

從現有的緊耦合架構遷移到上述的現代化架構，建議分四個階段進行：

### **階段一：協議定義與傳輸層切換 (Protocol & Transport) - 第 1-2 週**

* 定義 AgentEvent Pydantic 模型。
* 重構 server.py，使用 astream_events(version="v2") 配合 SSE 取代手動廣播。
* 在前端實現一個「原始事件檢視器」，驗證事件流的正確性，暫不涉及 UI 邏輯。

### **階段二：持久化與邏輯遷移 (Persistence) - 第 3-4 週**

* 部署 PostgreSQL 資料庫。
* 將 server.py 中的 JobManager 替換為 AsyncPostgresSaver。
* 重構一個現有代理，使用新的 interrupt() 模式。
* 驗證伺服器重啟後的任務恢復能力（災難恢復測試）。

### **階段三：狀態機與解耦 (State Machine) - 第 5-6 週**

* 在前端引入 XState 或 Reducer，實現 AgentReducer。
* 移除所有 nodeName ===... 的硬編碼邏輯。
* 確保 UI 僅依賴標準化的 status 事件（如 Processing, AwaitingInput）進行更新。

### **階段四：伺服器驅動 UI (SDUI) - 第 7 週起**

* 集成 react-jsonschema-form。
* 將所有 HITL 交互重構為 Schema 驅動的動態表單。
* 建立前端組件註冊表，實現基礎的 Generative UI。

## **結論**

目前的系統架構雖然能運作，但已達到維護性的極限。透過實施本報告提出的 **標準化事件協議**、**解耦狀態機**、**Postgres 持久化** 以及 **伺服器驅動 UI**，我們不僅能解決現有的耦合與穩定性問題，更將為未來的代理開發奠定堅實的基礎。這將使您的團隊能夠以極高的速度迭代新的代理能力，同時保持系統的穩健性與可擴展性，真正實現代理系統的工業化生產。

---

**(本報告結束)**

#### **引用的著作**

1. AG-UI + LangGraph Streaming: Technical Implementation Guide - DEV Community, 檢索日期：1月 24, 2026， [https://dev.to/ajay_gupta_60a0393643f3e9/ag-ui-langgraph-streaming-technical-implementation-guide-kbl](https://dev.to/ajay_gupta_60a0393643f3e9/ag-ui-langgraph-streaming-technical-implementation-guide-kbl)
2. How to resolve pydantic model is not JSON serializable [duplicate] - Stack Overflow, 檢索日期：1月 24, 2026， [https://stackoverflow.com/questions/68275352/how-to-resolve-pydantic-model-is-not-json-serializable](https://stackoverflow.com/questions/68275352/how-to-resolve-pydantic-model-is-not-json-serializable)
3. Mastering LangGraph Streaming: Advanced ... - Sparkco AI, 檢索日期：1月 24, 2026， [https://sparkco.ai/blog/mastering-langgraph-streaming-advanced-techniques-and-best-practices](https://sparkco.ai/blog/mastering-langgraph-streaming-advanced-techniques-and-best-practices)
4. Mastering Persistence in LangGraph: Checkpoints, Threads, and ..., 檢索日期：1月 24, 2026， [https://medium.com/@vinodkrane/mastering-persistence-in-langgraph-checkpoints-threads-and-beyond-21e412aaed60](https://medium.com/@vinodkrane/mastering-persistence-in-langgraph-checkpoints-threads-and-beyond-21e412aaed60)
5. LangGraph Streaming 101: 5 Modes to Build Responsive AI Applications - DEV Community, 檢索日期：1月 24, 2026， [https://dev.to/sreeni5018/langgraph-streaming-101-5-modes-to-build-responsive-ai-applications-4p3f](https://dev.to/sreeni5018/langgraph-streaming-101-5-modes-to-build-responsive-ai-applications-4p3f)
6. Streaming - Docs by LangChain, 檢索日期：1月 24, 2026， [https://docs.langchain.com/oss/javascript/langgraph/streaming](https://docs.langchain.com/oss/javascript/langgraph/streaming)
7. Streaming - Docs by LangChain, 檢索日期：1月 24, 2026， [https://docs.langchain.com/oss/python/langgraph/streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
8. BaseStreamEvent — LangChain documentation, 檢索日期：1月 24, 2026， [https://reference.langchain.com/v0.3/python/core/runnables/langchain_core.runnables.schema.BaseStreamEvent.html](https://reference.langchain.com/v0.3/python/core/runnables/langchain_core.runnables.schema.BaseStreamEvent.html)
9. MongoDBGraphRAGRetriever — LangChain MongoDB documentation - Read the Docs, 檢索日期：1月 24, 2026， [https://langchain-mongodb.readthedocs.io/en/latest/langchain_mongodb/retrievers/langchain_mongodb.retrievers.graphrag.MongoDBGraphRAGRetriever.html](https://langchain-mongodb.readthedocs.io/en/latest/langchain_mongodb/retrievers/langchain_mongodb.retrievers.graphrag.MongoDBGraphRAGRetriever.html)
10. ag-ui-protocol/ag-ui: AG-UI: the Agent-User Interaction ... - GitHub, 檢索日期：1月 24, 2026， [https://github.com/ag-ui-protocol/ag-ui](https://github.com/ag-ui-protocol/ag-ui)
11. Connecting a LangGraph workflow to a React User Interface | by ..., 檢索日期：1月 24, 2026， [https://medium.com/@martin.hodges/connecting-a-langgraph-workflow-to-a-react-user-interface-aea74bfbbe45](https://medium.com/@martin.hodges/connecting-a-langgraph-workflow-to-a-react-user-interface-aea74bfbbe45)
12. statelyai/xstate: Actor-based state management & orchestration for complex app logic. - GitHub, 檢索日期：1月 24, 2026， [https://github.com/statelyai/xstate](https://github.com/statelyai/xstate)
13. Global state with XState and React - Stately.ai, 檢索日期：1月 24, 2026， [https://stately.ai/blog/2024-02-12-xstate-react-global-state](https://stately.ai/blog/2024-02-12-xstate-react-global-state)
14. Mastering XState Fundamentals: A React-powered Guide - DEV Community, 檢索日期：1月 24, 2026， [https://dev.to/ibrocodes/mastering-xstate-fundamentals-a-react-powered-guide-2i3e](https://dev.to/ibrocodes/mastering-xstate-fundamentals-a-react-powered-guide-2i3e)
15. Interrupts - Docs by LangChain, 檢索日期：1月 24, 2026， [https://docs.langchain.com/oss/javascript/langgraph/interrupts](https://docs.langchain.com/oss/javascript/langgraph/interrupts)
16. Server Sent UI Schema Driven UIs : r/reactjs - Reddit, 檢索日期：1月 24, 2026， [https://www.reddit.com/r/reactjs/comments/zqdtoj/server_sent_ui_schema_driven_uis/](https://www.reddit.com/r/reactjs/comments/zqdtoj/server_sent_ui_schema_driven_uis/)
17. JSON Schema - Pydantic Validation, 檢索日期：1月 24, 2026， [https://docs.pydantic.dev/latest/concepts/json_schema/](https://docs.pydantic.dev/latest/concepts/json_schema/)
18. Episode 8: JSON Schema Generation in Pydantic | by Kishan Babariya - Medium, 檢索日期：1月 24, 2026， [https://medium.com/@kishanbabariya101/episode-8-json-schema-generation-in-pydantic-9a4c4fee02c8](https://medium.com/@kishanbabariya101/episode-8-json-schema-generation-in-pydantic-9a4c4fee02c8)
19. Add defaultFormStateBehavior initialRender type "populateRequiredDefaults" · Issue #4604 · rjsf-team/react-jsonschema-form - GitHub, 檢索日期：1月 24, 2026， [https://github.com/rjsf-team/react-jsonschema-form/issues/4604](https://github.com/rjsf-team/react-jsonschema-form/issues/4604)
20. rjsf-team/react-jsonschema-form: A React component for ... - GitHub, 檢索日期：1月 24, 2026， [https://github.com/rjsf-team/react-jsonschema-form](https://github.com/rjsf-team/react-jsonschema-form)
21. How to implement generative user interfaces with LangGraph - Docs by LangChain, 檢索日期：1月 24, 2026， [https://docs.langchain.com/langsmith/generative-ui-react](https://docs.langchain.com/langsmith/generative-ui-react)
