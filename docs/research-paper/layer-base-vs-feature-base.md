# LangGraph 企業級架構深度剖析：分層架構 (Layer-based) 與垂直切片架構 (Feature-based) 的比較與範例

## 執行摘要
隨著生成式人工智慧 (Generative AI) 從實驗性的 Jupyter Notebooks 轉向生產環境的企業級應用，軟體架構的選擇成為了決定專案成敗的關鍵因素。LangGraph 作為一個專為構建有狀態、多代理 (Multi-Agent) 應用而設計的框架，其獨特的圖論 (Graph Theory) 執行模型對傳統的軟體設計模式提出了挑戰。當前，開發團隊主要面臨兩種架構典範的選擇：一種是強調技術職責分離的**分層架構 (Layer-based / Clean Architecture)**，另一種是強調業務能力聚合的**垂直切片架構 (Feature-based / Vertical Slice Architecture)**。
本報告旨在為架構師、資深工程師及技術決策者提供一份詳盡的研究指南。我們將深入探討這兩種架構在 LangGraph 專案中的實際應用，分析其對開發速度、可維護性、測試策略及系統擴展性的影響。研究表明，雖然分層架構在傳統企業軟體中具有統治地位，但在以 Agent 為中心的 AI 工程中，垂直切片架構（Vertical Slice Architecture, VSA）因其與 LangGraph 的「子圖 (Subgraph)」概念及「狀態機 (State Machine)」模型的高度契合，正逐漸成為構建複雜多代理系統的首選模式。本報告將透過詳盡的代碼結構分析、開發場景模擬及企業級最佳實踐（如 Monorepo 管理、狀態持久化、串流介面設計），為讀者提供具可操作性的架構藍圖。

---

## 1. AI 工程的架構轉向：從確定性到機率性
在深入比較具體架構之前，必須先理解 AI 應用程式與傳統軟體在根本屬性上的差異，以及這些差異如何重塑我們對「良好架構」的定義。

### 1.1 傳統軟體架構的演進與侷限
過去數十年，軟體工程界發展出了諸如分層架構 (N-Tier)、六角架構 (Hexagonal Architecture) 和洋蔥架構 (Onion Architecture) 等模式 。這些架構的核心目標是**解耦 (Decoupling)**：將核心業務邏輯（Domain）與外部依賴（如資料庫、UI、框架）分離。其背後的假設是：業務規則是確定性的、穩定的，而技術實現細節是易變的。
然而，在 LangGraph 驅動的 Agent 系統中，這個假設被打破了：

1. **框架即邏輯**：LangGraph 的圖結構（節點與邊的連接方式）本身就是業務邏輯的核心部分。試圖將 LangGraph 視為一個可隨時替換的「外部細節」而過度抽象，往往會導致「抽象洩漏 (Leaky Abstractions)」，使得開發者無法利用框架提供的高級功能（如時間旅行、循環偵測）。
2. **提示工程與程式碼的緊密耦合**：在傳統軟體中，邏輯在程式碼中；在 AI 軟體中，邏輯分佈在程式碼（工具定義、流程控制）與自然語言提示詞（Prompts）之間。將 Prompt 視為單純的資源文件與程式碼分離，會導致開發者在調試時需要在多個層級間頻繁切換，破壞了認知的連貫性 。
3. **狀態的複雜性**：傳統 Web 應用多為無狀態 (Stateless) 請求，狀態由資料庫管理。而 Agent 應用本質上是有狀態的 (Stateful)，對話歷史、工具輸出、中間推理步驟都需要在記憶體中維護並隨流程流轉 。

### 1.2 LangGraph 的設計哲學與架構需求
LangGraph 的設計深受圖論與狀態機影響。它不強制要求特定的專案結構，而是提供了一組低階原語（Nodes, Edges, State, Checkpointers）。這給予了開發者極大的自由度，但也帶來了結構混亂的風險——即所謂的「義大利麵條式圖形 (Spaghetti Graphs)」，其中條件邏輯、工具調用和狀態突變交織在一起，難以維護 。
因此，選擇一種能夠有效管理這種複雜性，同時又不限制 LLM 靈活性的架構至關重要。企業級 LangGraph 專案通常面臨以下需求：

- **模組化 (Modularity)**：能夠獨立開發和測試單個 Agent 或技能。
- **可觀測性 (Observability)**：清晰追蹤 Agent 的推理過程和工具調用 。
- **協作性 (Collaboration)**：支援多個團隊在同一個 Monorepo 中並行開發不同的子圖 。
- **演進性 (Evolvability)**：能夠從簡單的 ReAct Agent 平滑演進為複雜的多 Agent 協作系統 。

---

## 2. 分層架構 (Layer-based Architecture) 在 LangGraph 中的應用
分層架構，特別是「整潔架構 (Clean Architecture)」，是企業級軟體開發中最常見的模式。其核心思想是依據**技術職責**對程式碼進行水平切分。

### 2.1 架構層級詳解
在 LangGraph 專案中應用分層架構，通常會將專案劃分為以下四個主要層級，依賴關係嚴格由外向內 。

#### 2.1.1 領域層 (Domain Layer)
這是系統的核心，包含企業範圍內的業務實體與邏輯，且不依賴任何外部框架。

- **職責**：定義 Agent 的核心數據結構（State Schema）、業務實體（Entities）以及工具與服務的抽象介面（Interfaces）。
- **LangGraph 實現**：
  - **State Definitions**：定義 `AgentState` 的 Pydantic 模型或 TypedDict。這是系統中各個組件溝通的「通用語言」。
  - **Abstract Tools**：定義工具的接口，例如 `BaseSearchTool`，而不涉及具體的 API 實作（如 Tavily 或 Google Search）。
- **特點**：純 Python 程式碼，無 `langgraph` 或 `langchain` 的具體依賴（理想情況下），僅依賴標準庫或 Pydantic。

#### 2.1.2 應用層 (Application Layer)
此層包含應用程式的特定業務規則，即「用例 (Use Cases)」。

- **職責**：編排領域物件以完成特定任務。
- **LangGraph 實現**：
  - **Graph Construction**：在此層定義 `StateGraph` 的拓撲結構。這包括節點（Nodes）的添加和邊（Edges）的連接。
  - **Orchestration Logic**：定義條件邊（Conditional Edges）的路由邏輯，決定 Agent 下一步該做什麼 。
  - **Node Logic**：實現具體的節點函數，這些函數接收狀態，調用領域服務，並返回狀態更新。

#### 2.1.3 基礎設施層 (Infrastructure Layer)
此層提供領域層介面的具體實作，處理所有與外部世界的交互。

- **職責**：資料庫存取、外部 API 調用、LLM 客戶端配置。
- **LangGraph 實現**：
  - **Concrete Tools**：實作 `TavilySearchTool`、`PostgresRetriever` 等具體工具類別 。
  - **LLM Integration**：配置 `ChatOpenAI` 或 `ChatAnthropic`，處理 API Key 和模型參數。
  - **Persistence**：實作 `Checkpointer`（如 `PostgresSaver`），負責將 Agent 狀態持久化到資料庫 。

#### 2.1.4 表現層 (Presentation Layer)
這是系統的入口點，負責處理用戶輸入並觸發應用層的邏輯。

- **職責**：API 端點、CLI 介面、WebSocket 處理。
- **LangGraph 實現**：
  - **FastAPI Routes**：定義 RESTful API 或 WebSocket 端點，接收用戶請求，初始化圖形運行 (Runs)，並串流返回結果 。
  - **API Schemas**：定義前端與後端交互的 DTO (Data Transfer Objects)。

### 2.2 專案結構範例 (Layer-based)
src/
├── domain/                  # 核心業務邏輯與介面
│   ├── entities/
│   │   ├── **init**.py
│   │   ├── agent_state.py   # 定義 AgentState (TypedDict/Pydantic)
│   │   └── discussion.py    # 領域實體
│   └── interfaces/
│       ├── **init**.py
│       ├── llm_service.py   # LLM 服務介面
│       └── tool_registry.py # 工具註冊表介面
├── application/             # 應用邏輯與圖形編排
│   ├── graphs/
│   │   ├── **init**.py
│   │   ├── main_graph.py    # 主圖定義
│   │   └── subgraphs/       # 子圖定義
│   ├── nodes/
│   │   ├── **init**.py
│   │   ├── reasoner.py      # 推理節點邏輯
│   │   └── executor.py      # 執行節點邏輯
│   └── use_cases/
│       └── run_research.py  # 執行研究任務的用例
├── infrastructure/          # 具體實作細節
│   ├── llm/
│   │   ├── langchain_llm.py # LangChain LLM 實作
│   │   └── prompts.py       # Prompt 模板管理
│   ├── tools/
│   │   ├── search_tool.py   # 搜索工具實作
│   │   └── db_tool.py
│   └── persistence/
│       └── pg_saver.py      # PostgreSQL Checkpointer
└── presentation/            # API 與介面
├── api/
│   ├── main.py          # FastAPI 應用入口
│   └── routes.py        # API 路由
└── schemas/
└── request.py       # API 請求/回應模型

### 2.3 分層架構的深度評估

#### 優勢

1. **關注點分離 (Separation of Concerns)**：這是分層架構最大的優點。開發基礎設施的工程師不需要了解複雜的圖形邏輯，而專注於 Prompt 優化的工程師不需要關心資料庫連接細節 。
2. **可測試性 (Testability)**：由於依賴關係清晰且大量使用介面，Mock 外部依賴（如 LLM API 或資料庫）變得非常容易，有利於單元測試 。
3. **技術一致性**：所有的工具都放在 `infrastructure/tools`，所有的 Prompt 都放在 `infrastructure/llm`，這使得跨團隊強制執行代碼規範變得容易。

#### 劣勢與挑戰

1. **認知分散 (Cognitive Scattering)**：在開發一個新功能（例如為 Agent 增加「查詢天氣」的能力）時，開發者需要在 `domain` 定義介面，在 `infrastructure` 實作工具，在 `application` 修改圖結構，並在 `presentation` 更新 API 規範。這種「跳躍式」的開發體驗在需要快速迭代的 AI 專案中會顯著降低效率 。
2. **抽象過度 (Over-Abstraction)**：為了保持架構的「潔淨」，開發者可能會試圖隱藏 LangGraph 的細節。例如，創建一個通用的 `AgentRunner` 介面來包裝 `graph.invoke`。這往往會隱藏 LangGraph 強大的功能（如 `stream_events` 或 `interrupt`），導致開發者在需要使用這些進階功能時必須破壞封裝 。
3. **Prompt 與邏輯分離的代價**：在分層架構中，Prompt 通常被視為配置或資源，放在基礎設施層。然而，Prompt 實際上是 Agent 邏輯的核心。將 Prompt 與使用它的節點邏輯（應用層）物理分離，會導致開發者在調整 Prompt 時無法直觀地看到其對業務邏輯的影響 。

---

## 3. 垂直切片架構 (Feature-based / Vertical Slice Architecture) 在 LangGraph 中的應用
垂直切片架構（VSA）近年來在.NET 和 Node.js 社群中重新流行，並被證明非常適合微服務和 Agent 系統。其核心思想是依據**業務功能（Feature）或能力（Capability）**來組織代碼，而不是依據技術層級 。

### 3.1 架構理念：以 Agent 為中心的組織方式
在 LangGraph 專案中，一個「垂直切片」通常對應一個**特定的 Agent**（如研究 Agent、編碼 Agent）或一個**完整的子圖（Subgraph）**。在這個切片內部，包含了該 Agent 運行所需的一切：圖定義、Prompt、專屬工具、狀態定義甚至是測試代碼 。
這種架構遵循「高內聚 (High Cohesion)」原則：將一起改變的東西放在一起。當你需要修改研究 Agent 的行為時，你只需要關注 `features/researcher` 這個資料夾，而不需要在整個專案中尋找散落的檔案 。

### 3.2 垂直切片架構詳解
在 VSA 中，專案結構通常由一個「共享核心 (Shared Kernel)」和多個「功能切片 (Feature Slices)」組成。

#### 3.2.1 功能切片 (The Feature Slice)
每個切片都是一個自包含的模組，理想情況下，它對外僅暴露一個編譯好的 `CompiledGraph` 物件供上層調用。

- **State**：切片內部定義自己的 `SubgraphState`。這與全域狀態隔離，允許開發者在不影響其他 Agent 的情況下修改內部狀態結構 。
- **Graph**：定義該 Agent 具體的 `StateGraph`。
- **Tools**：僅該 Agent 使用的工具直接定義在切片內。
- **Prompts**：Prompt 模板與使用它的節點代碼放在一起，方便調試和版本控制。

#### 3.2.2 共享核心 (Shared Kernel)
為了避免代碼重複（例如多個 Agent 都需要使用資料庫或基本的 LLM 配置），VSA 會提取一個共享層 。

- **Common Tools**：通用的工具（如 `Calculator` 或 `GoogleSearch`）可以放在共享庫中。
- **Base State**：定義跨切片通用的狀態鍵（如 `messages`），確保不同 Agent 之間可以透過標準協議通信。
- **Infrastructure**：共享的資料庫連接、日誌記錄、認證邏輯。

### 3.3 專案結構範例 (Feature-based)
src/
├── features/                # 功能切片 (Agents/Subgraphs)
│   ├── researcher/          # 研究 Agent 切片
│   │   ├── **init**.py      # 導出 compiled_graph
│   │   ├── graph.py         # 定義 StateGraph
│   │   ├── state.py         # 定義 ResearcherState (私有)
│   │   ├── prompts.py       # 研究相關 Prompts
│   │   ├── tools.py         # 專屬工具 (如 PDF 解析)
│   │   └── tests/           # 針對此 Agent 的測試
│   ├── coder/               # 編碼 Agent 切片
│   │   ├── **init**.py
│   │   ├── graph.py
│   │   └── tools.py         # 專屬工具 (如 Python REPL)
│   └── supervisor/          # 協調者切片 (Orchestrator)
│       ├── graph.py         # 頂層圖，引入 Researcher 和 Coder
│       └── routing.py       # 路由邏輯
├── shared/                  # 共享核心 (Shared Kernel)
│   ├── state.py             # 全域 AgentState 定義
│   ├── llm.py               # LLM 工廠函數
│   ├── tools/               # 通用工具庫
│   │   └── web_search.py
│   └── utils/
│       └── tracing.py       # LangSmith 配置
└── main.py                  # 應用入口，掛載 Supervisor 圖

### 3.4 垂直切片架構的深度評估

#### 優勢

1. **與 LangGraph Subgraph 概念完美契合**：LangGraph 的核心功能之一是支援子圖，即將一個編譯好的圖作為另一個圖的節點 。VSA 的結構天然映射了這種模式：`features/researcher` 導出一個子圖，`features/supervisor` 將其作為節點引入。這使得架構與框架的概念模型高度一致。
2. **開發速度與維護性**：新加入團隊的開發者若被分配到「改進編碼 Agent」的任務，他只需要關注 `features/coder` 目錄。他不需要理解整個系統的複雜性，也不會不小心破壞其他 Agent 的邏輯 。
3. **靈活的技術選型**：在 VSA 中，不同的切片可以採用不同的實作策略。例如，簡單的分類 Agent 可以只用一個節點和 Prompt 實作，而複雜的研究 Agent 可以包含循環、反思 (Reflection) 和多個工具。架構不會強制要求所有功能都遵循相同的「層級」模式 。

#### 劣勢與挑戰

1. **代碼重複的風險**：如果沒有嚴格管理 `shared` 目錄，不同的切片可能會重複實作相同的邏輯（例如兩個 Agent 都寫了自己的 HTTP Client）。這需要透過代碼審查（Code Review）和提取共用邏輯到共享核心來緩解 。
2. **切片間界限的模糊**：有時很難決定一個功能是屬於某個特定切片還是共享核心。例如，「發送郵件」工具，如果只有一個 Agent 用，就在切片內；如果有兩個 Agent 用，是否立即移到共享層？這需要團隊有明確的重構約定。

---

## 4. LangGraph 核心機制與架構對齊
無論選擇何種架構，必須深入理解 LangGraph 的特定機制，因為這些機制會直接影響架構的實作細節。

### 4.1 狀態管理 (State Management)：TypedDict vs. Pydantic
在企業級應用中，如何定義 State 是一個關鍵決策。LangGraph 支援 `TypedDict` 和 `Pydantic` 模型 。

- **TypedDict (推薦用於內部狀態)**：LangGraph 的官方文檔和最佳實踐傾向於使用 `TypedDict` 來定義圖的狀態 。
  - **理由**：`TypedDict` 支援**部分更新 (Partial Updates)**。當一個節點返回 `{"messages": [new_msg]}` 時，LangGraph 會自動將其與現有狀態合併。這對於並行執行的節點特別重要，因為它們可以同時更新狀態的不同部分而不會發生衝突 。
  - **架構影響**：在 VSA 中，每個切片可以在 `state.py` 中定義自己的 `TypedDict`，並繼承自共享的 `BaseState`。
- **Pydantic (推薦用於邊界驗證)**：Pydantic 模型更適合用於輸入/輸出的驗證層 。
  - **理由**：在 API 邊界（表現層）或工具輸入驗證中，強型別和驗證邏輯是必須的。
  - **架構影響**：在分層架構中，領域實體通常是 Pydantic 模型，但在應用層轉換為 `TypedDict` 供 LangGraph 使用。

### 4.2 控制流 (Control Flow)：Conditional Edges vs. Command
LangGraph 近期引入的 `Command` 物件改變了控制流的設計模式，這對 VSA 特別有利 。

- **Conditional Edges (傳統模式)**：
  - 需要定義路由函數（Router Function）和條件邊。路由邏輯與節點邏輯是分離的。
  - **缺點**：在 VSA 中，這意味著 Supervisor 必須明確知道所有子 Agent 的存在並定義路由規則，增加了耦合度。
- **Command 物件 (現代模式)**：
  - 節點可以直接返回 `Command(goto="next_node", update={...})`。
  - **優勢**：這實現了「無邊圖 (Edgeless Graph)」。Agent 可以動態決定下一步去哪裡，甚至可以跳轉到父圖（Parent Graph）的節點 (`graph=Command.PARENT`)。
  - **架構影響**：這極大地增強了 VSA 的解耦能力。一個子圖中的 Agent 可以發出指令將控制權交還給 Supervisor，而不需要 Supervisor 預先定義複雜的條件判斷邏輯 。
**表 4.1：Handoff 機制比較**

| 特性 | Conditional Edges | Command Object | 適用架構場景 |
| --- | --- | --- | --- |
| 邏輯位置 | 圖定義 (Edges) | 節點實作 (Return value) | Command 更適合 VSA，因其將路由邏輯封裝在 Agent 內部 |
| 耦合度 | 高 (Router 需知曉圖結構) | 低 (節點決定下一步) | Command 降低了 Supervisor 對具體子圖行為的依賴 |
| 狀態更新 | 與路由分離 | 原子操作 (Update + Route) | Command 避免了多 Agent 狀態同步的競態條件 |
| 跨子圖跳轉 | 需複雜配置 | 支援 Command.PARENT | Command 原生支援層級式多 Agent 系統 |

### 4.3 子圖與狀態隔離 (Subgraphs and State Isolation)
LangGraph 的子圖機制允許父圖與子圖擁有不同的 Schema 。

- **共享 Schema**：如果子圖作為節點直接加入，它必須共享父圖的狀態鍵（Keys）。這適合緊密協作的 Agent。
- **獨立 Schema**：可以透過一個轉換函數來調用子圖，將父圖狀態轉換為子圖狀態，執行完畢後再轉換回來。這在 VSA 中非常有用，它允許開發者為特定功能的 Agent 設計完全優化的內部狀態，而不必污染全域狀態 。

---

## 5. 企業級模式：混合單一倉庫 (Hybrid Monorepo) 與共享核心
對於大型企業團隊，單純的 VSA 可能不足以應對數十個 Agent 的管理。此時，結合 **Monorepo** 工具的混合模式是最佳實踐 。

### 5.1 Monorepo 工具鏈：uv 與 Poetry
現代 Python 工具鏈如 `uv` 和 `Poetry` 提供了強大的 Workspace 功能，這對於管理 LangGraph 多 Agent 專案至關重要 。

#### 5.1.1 為什麼需要 Workspaces？
在一個大型 LangGraph 專案中，不同的 Agent 可能依賴不同版本的庫（儘管應盡量避免），或者更常見的是，它們都依賴一組共享的內部庫（Shared Kernel）。

- **依賴隔離與共享**：Workspace 允許在根目錄維護一個 `uv.lock` 鎖定檔，確保所有 Agent 使用相同版本的基礎依賴（如 `langchain-core`），同時允許各個 Agent 包定義自己的依賴 。
- **本地開發體驗**：開發者可以在根目錄運行 `uv run`，自動解析所有內部包的引用，無需手動發布或安裝。

### 5.2 推薦的目錄結構 (Hybrid Enterprise Pattern)
這是一個結合了 VSA 和分層思想（在共享庫中）的企業級結構範例。
my-langgraph-monorepo/
├── pyproject.toml              # Workspace 根定義
├── uv.lock                     # 全域依賴鎖定
├── libs/                       # 共享庫 (Shared Kernel)
│   ├── core-state/             # 定義全域狀態與協議
│   │   ├── src/
│   │   └── pyproject.toml
│   └── enterprise-tools/       # 企業級工具包 (ACL)
│       ├── src/
│       │   ├── salesforce/     # Salesforce 工具封裝
│       │   └── vector_db/      # 向量庫封裝
│       └── pyproject.toml
└── agents/                     # 獨立的 Agent 專案 (Vertical Slices)
├── researcher/
│   ├── src/
│   ├── pyproject.toml      # 依賴 libs/core-state
│   └── Dockerfile
├── customer-support/
│   ├── src/
│   ├── pyproject.toml
│   └── Dockerfile
└── supervisor/             # 頂層編排器
├── src/
└── pyproject.toml

### 5.3 共享核心的設計原則
在 `libs/` 中的代碼應遵循嚴格的設計原則，充當「防腐層 (Anti-Corruption Layer, ACL)」。

- **工具封裝**：不要直接在 Agent 中使用原始的 API 客戶端。在 `enterprise-tools` 中封裝 `BaseTool`，處理重試、錯誤處理和輸出格式化。Agent 只需導入並使用這些工具，而不必關心底層實現。
- **協議定義**：在 `core-state` 中定義 Agent 之間的通訊協議（例如，handoff 時的 `Command` 格式）。這確保了即使是由不同團隊開發的 Agent，也能夠互相理解對方的輸出。

---

## 6. 持久化與記憶策略 (Persistence and Memory)
LangGraph 的強大之處在於其內建的持久化能力。在架構設計時，必須區分**短期記憶**與**長期記憶**。

### 6.1 短期記憶：Checkpointers
短期記憶是指當前對話線程（Thread）的狀態。這由 `Checkpointer` 管理 。

- **機制**：每次狀態更新（節點執行完畢）後，Checkpointer 會將狀態序列化並存入資料庫（如 Postgres）。
- **架構決策**：
  - **生產環境**：必須使用 `PostgresSaver` 或 `RedisSaver`，而非內存中的 `MemorySaver`。這支援了水平擴展，任何 API 實例都可以恢復任何線程的執行 。
  - **配置位置**：Checkpointer 的配置應在應用程式的入口點（如 FastAPI 的 `lifespan` 或依賴注入層），而不是硬編碼在圖定義中。

### 6.2 長期記憶：The Store
長期記憶是指跨對話線程的資訊（如用戶偏好、過去的任務結果）。

- **LangGraph Store**：LangGraph 提供了 `Store` 介面，用於存儲和檢索 JSON 文檔及向量數據 。
- **架構模式**：
  - 不要將長期記憶塞進 `State` TypedDict 中，這會導致 Context Window 爆炸。
  - **Profile Node**：在圖的開始處設計一個「Profile」節點，根據 User ID 從 Store 中檢索相關記憶，並將其注入到 Prompt 的 System Message 中。
  - **Memory Node**：在對話結束或關鍵節點，設計一個節點負責提取有價值的資訊並寫回 Store。

---

## 7. 介面與串流模式 (Interface & Streaming Patterns)
Agent 系統的使用者體驗高度依賴於即時反饋。因此，架構必須支援高效的串流（Streaming）。

### 7.1 後端設計：FastAPI 與 Async
標準的部署模式是將 LangGraph 包裝在 FastAPI 服務中 。

- **非同步優先**：LangGraph 是原生非同步的。API 端點應使用 `async def` 並調用 `graph.astream_events`。
- **長任務管理**：對於耗時較長的任務（如深度研究），不應使用單一 HTTP 請求等待結果。應採用「提交任務 -> 返回 Thread ID -> 建立 WebSocket/SSE 連接」的模式 。

### 7.2 前端協議：AG-UI 與 SSE
為了標準化 Agent 與 UI 的交互，AG-UI (Agent-GUI) 協議正在成為一種新興標準 。

- **Server-Sent Events (SSE)**：相比 WebSocket，SSE 更輕量、防火牆友好，且完美契合 Agent 的單向輸出流（Agent -> User）。
- **事件結構**：後端應將 LangGraph 的內部事件（`on_chat_model_stream`, `on_tool_start`, `on_tool_end`）轉換為標準化的前端事件：
  - `text_delta`：文字生成的增量。
  - `tool_call`：工具調用的元數據（用於 UI 顯示「正在搜索...」）。
  - `state_update`：狀態變更通知。
**表 7.1：LangGraph 與前端交互模式**

| 模式 | 適用場景 | 優點 | 缺點 |
| --- | --- | --- | --- |
| 同步 HTTP | 簡單問答，回應極快 (<3s) | 實作最簡單 | 使用者體驗差，容易超時 |
| WebSocket | 雙向即時通訊，語音交互 | 雙向延遲低 | 連接維護複雜，需處理斷線重連 |
| SSE (推薦) | 大多數 Agent 串流場景 | 單向串流標準，瀏覽器原生支援 | 僅支援單向 (Server -> Client) |

---

## 8. 測試與可觀測性 (Testing and Observability)
在 VSA 中，測試策略比傳統分層架構更為直觀。

### 8.1 測試策略

- **單元測試 (Unit Tests)**：針對每個切片內的 `graph.py` 中的節點函數進行測試。由於節點只是純函數（接收 State，返回 Update），這非常容易測試。可以 Mock 傳入的 State 和工具調用 。
- **整合測試 (Integration Tests)**：針對編譯好的子圖進行端到端測試。使用 `LangSmith` 的評估功能，輸入一組測試用例，驗證 Agent 的輸出是否符合預期 。
- **回歸測試**：利用 LangGraph 的 `Store` 或 Checkpoint 歷史數據，重放過去的對話來確保新代碼沒有破壞舊邏輯。

### 8.2 可觀測性 (Observability)
由於 Agent 的非確定性，可觀測性是生產環境的必須品。

- **LangSmith 集成**：在共享核心中統一配置 LangSmith Tracing。確保每個 `Run` 都有正確的 `project_name` 和 `tags`，以便區分不同 Agent 的表現 。
- **Prompt 版本管理**：結合 MLflow 或 LangSmith Hub 管理 Prompt 版本。在 VSA 中，雖然 Prompt 檔案在切片內，但其內容應透過 Registry 進行加載，以實現動態更新和 A/B 測試 。

---

## 9. 結論與建議
經過對分層架構與垂直切片架構在 LangGraph 專案中的深入比較，我們得出以下結論：

1. **垂直切片架構 (VSA) 是 LangGraph 的自然選擇**：由於 LangGraph 的子圖機制、狀態隔離需求以及 Agent 開發的高內聚特性，VSA 提供了比分層架構更優越的開發體驗和系統可維護性。它避免了在多層之間跳躍的認知負擔，並允許每個 Agent 獨立演進。
2. **混合 Monorepo 是企業級擴展的關鍵**：對於擁有多個 Agent 團隊的企業，單純的 VSA 可能導致代碼重複。採用基於 `uv` 或 `Poetry` 的 Workspace 機制，建立「共享核心 (Shared Kernel)」來管理通用工具和協議，是平衡解耦與重用的最佳實踐。
3. **擁抱 LangGraph 原生特性**：架構應圍繞框架特性構建，而不是對抗它。使用 `TypedDict` 進行狀態管理，利用 `Command` 物件進行動態路由，並依賴 `Checkpointer` 實現持久化，這些決策應內建於架構規範中。

### 給架構師的建議清單

- [ ] **採用垂直切片**：為每個 Agent 建立獨立的目錄，包含其圖定義、Prompt 和專屬工具。
- [ ] **建立共享核心**：提取通用的 LLM 配置、Tracing 設置和企業級工具封裝到共享庫。
- [ ] **標準化介面**：定義全域通用的 `AgentState` 基礎結構和 Handoff 協議。
- [ ] **實作串流後端**：使用 FastAPI + SSE 作為標準的 Agent 暴露方式。
- [ ] **投資可觀測性**：從第一天起就集成 LangSmith 或類似工具，這對 Agent 的調試至關重要。
透過遵循這些架構原則，企業可以構建出既具備靈活性以適應 AI 快速迭代，又具備穩健性以支撐關鍵業務的 LangGraph 應用系統。

---

Source: https://gemini.google.com/app/abb65fb588b66fe5
Exported at: 2026-02-19T02:51:59.552Z
