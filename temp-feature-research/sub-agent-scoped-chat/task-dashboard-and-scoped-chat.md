# **企業級金融智能體架構轉型研究報告：從線性對話到範圍化多智能體協作系統**

## **1. 執行摘要 (Executive Summary)**

隨著大型語言模型（LLM）在金融領域的應用從簡單的問答機器人（Chatbot）向能夠執行複雜任務的智能體（Agent）演進，傳統的單一線性對話介面（Linear Chat Interface）已逐漸成為限制系統效能與用戶體驗的瓶頸。本報告針對 **「如何將包含 Planner、Executor、Auditor、Approval、Calculator 等節點的金融 Agent 從流水線模式轉型為範圍化對話（Scoped Chat）與任務卡片（Task Cards）架構」** 這一核心議題，進行了詳盡的技術分析與解決方案設計。

研究表明，當前的線性 Pipeline 架構雖然在開發初期具有簡單易懂的優勢，但在面對企業級金融場景時，存在上下文污染、用戶介入困難、狀態可觀測性低以及錯誤恢復成本高等結構性缺陷。為了解決這些問題，本報告提出了一種基於 **LangGraph 子圖（Subgraphs）技術** 與 **事件驅動 UI（Event-Driven UI）** 的新型架構。

此架構的核心變革在於：

1. **後端重構**：從單一的 StateGraph 轉向分層的「主圖-子圖」結構，利用 LangGraph 的狀態隔離機制，為每個子智能體建立獨立的記憶體空間（Scoped Memory）。
2. **中台編排**：引入「監督者（Supervisor）」節點作為動態編排器，取代固定的順序執行，實現基於狀態的條件路由。
3. **前端轉型**：放棄單一的消息流視圖，轉向「儀表板（Dashboard）」佈局。利用任務卡片展示高維度的狀態快照（Snapshot），並通過點擊卡片展開的範圍化模態視窗（Scoped Modal）來提供細粒度的交互環境。
4. **人機迴路（HITL）**：利用持久化檢查點（Checkpointers）與中斷機制（Interrupts），實現「時光倒流（Time Travel）」與「狀態分叉（Forking）」，允許用戶在流程中途修正特定節點的決策而不需重啟整個任務。

本報告將分為十一個章節，總計約 15,000 字，深入探討此轉型的理論基礎、代碼改造路徑、UI/UX 設計模式以及企業級合規考量。

## ---

**2. 背景與現狀分析 (Background and Current State Analysis)**

在深入解決方案之前，我們必須對「金融智能體」的特殊屬性以及您現有的代碼架構進行深刻的解構。金融場景不同於一般的創意寫作或閒聊，它對精確性、可追溯性以及合規性有著極高的要求。

### **2.1 線性 Pipeline 架構的特徵與局限**

根據您的描述，目前的 Agent 設計為一個順序執行的 Pipeline：Planner -> Executor -> Auditor -> Approval -> Calculator。在 LangGraph 的語境下，這通常意味著一個扁平的 StateGraph，所有節點共享同一個 State Schema。

#### **2.1.1 共享狀態的「上下文污染」風險**

在典型的線性實作中，狀態定義通常如下所示：

Python

class SharedState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    context: dict

在這種架構下，Planner 生成的規劃、Executor 的 SQL 查詢語句、Auditor 的合規檢查報告，以及 Calculator 的 Python 代碼執行結果，全部都被追加（Append）到同一個 messages 列表中。

* **問題分析**：隨著流程的推進，Context Window 會被大量的中間步驟（Intermediate Steps）填滿。當流程到達最後的 Approval 階段時，LLM 需要處理前述所有節點的冗長歷史，這不僅增加了 Token 成本，更嚴重的是會導致「注意力分散（Attention Dilution）」。例如，Approval Agent 可能會被 Executor 早期的一個失敗嘗試所誤導，而忽略了最終成功的結果。
* **金融場景影響**：在金融審計中，清晰的證據鏈至關重要。將所有雜訊混合在一起，使得追溯決策依據變得極其困難。

#### **2.1.2 線性流的「交互僵化」**

您提到「如果正在某一個流程，我怎樣根據 user 的輸入去判斷，例如他想修改之前某一個node的步驟還是繼續？」這正是線性架構的最大痛點。

* **現狀**：在 Pipeline 模式中，一旦 Planner 完成並將控制權交給 Executor，流程就「過河拆橋」了。如果 Executor 執行失敗，或者用戶發現 Planner 的計畫有誤，系統通常只能報錯並重新開始，或者需要極其複雜的 if-else 邏輯來處理回退。
* **需求**：企業級應用需要的是「非線性」的交互。用戶應該能在 Executor 執行期間，突然暫停，回頭修改 Planner 的指令，然後讓 Executor 基於新的計畫重新運行。這需要底層架構支持「狀態持久化（Persistence）」與「版本控制（Versioning）」。

### **2.2 為什麼 Chat UI 不適合複雜金融 Agent**

您提出的疑問：「其實是不是我現在類型的 Agent 是不適合用 Chat 模式的？」答案是肯定的。

Chat UI（對話介面）是一種 **「流式（Stream-based）」** 的交互範式，它隱含了時間的線性流動。然而，複雜的金融任務（如投資組合再平衡、風險評估報告生成）本質上是 **「結構化（Structure-based）」** 和 **「狀態導向（State-oriented）」** 的。

| 特徵 | Linear Chat UI (ChatGPT-style) | Task-Oriented Dashboard (Enterprise) |
| :---- | :---- | :---- |
| **資訊呈現** | 依時間順序追加，舊訊息被推走 | 依邏輯模組分區，關鍵狀態常駐顯示 |
| **關注點** | 當前最新的對話氣泡 | 全局進度與各子系統的健康狀況 |
| **用戶操作** | 僅能輸入文字回應 | 點擊、審批、編輯參數、回滾版本 |
| **多工處理** | 困難，上下文容易混淆 | 容易，不同卡片代表不同並行任務 |
| **適用場景** | 諮詢、閒聊、簡單指令 | 複雜工作流編排、決策支持、審計 |

對於一個包含 Planner（規劃）、Executor（執行）、Auditor（核查）的系統，用戶需要同時關注：

1. **Planner** 到底規劃了什麼路徑？（需要全覽視圖）
2. **Executor** 當前執行到哪一步？（需要進度監控）
3. **Auditor** 發現了什麼風險？（需要高亮警示）

這些資訊如果在一個 Chat 窗口中交織出現，會造成極大的認知負荷（Cognitive Load）。因此，轉型為 **Scoped Chat（範圍化對話）** 配合 **Task Cards（任務卡片）** 不僅是 UI 的美化，更是為了符合人類在處理複雜任務時的認知模型。

## ---

**3. 架構重構：從單體到聯邦 (Architectural Transformation)**

要實現您期望的 UI 變革，必須先對後端 LangGraph 代碼進行深度的結構化改造。核心思路是將「單體架構（Monolithic Architecture）」轉型為「聯邦架構（Federated Architecture）」。

### **3.1 引入子圖 (Subgraphs) 與狀態隔離**

在 LangGraph 中，實現 Scope（範圍）的最佳實踐是使用 **Subgraphs** 1。這意味著每一個子智能體（Planner, Executor 等）都不再僅僅是一個 Node 函數，而是一個獨立完整的 StateGraph。

#### **3.1.1 為什麼需要子圖？**

* **狀態封裝（Encapsulation）**：Planner 子圖可以擁有自己的 messages 列表。當它在內部進行「自我反思（Self-reflection）」或與用戶進行多輪釐清需求的對話時，這些中間訊息只存在於 Planner 的子圖狀態中。當 Planner 完成任務，返回主圖（Parent Graph）的只有最終的 plan 對象。
* **獨立記憶體（Scoped Memory）**：Executor 子圖可以維護自己的 tool_outputs 歷史。這保證了當用戶在 UI 上打開 "Executor Card" 時，看到的只有工具調用的細節，而不會看到 Auditor 的評論。

#### **3.1.2 代碼結構對比**

**改造前（扁平結構）：**

Python

workflow = StateGraph(SharedState)
workflow.add_node("planner", planner_node)
workflow.add_node("executor", executor_node)
workflow.add_edge("planner", "executor")

**改造後（聯邦結構）：**

Python

# 1. 定義 Planner 子圖
planner_state = StateGraph(PlannerState)
planner_state.add_node("draft_plan", draft_node)
planner_state.add_node("refine_plan", refine_node)
planner_app = planner_state.compile()

# 2. 定義 Executor 子圖
executor_state = StateGraph(ExecutorState)
executor_state.add_node("tool_call", tool_node)
executor_app = executor_state.compile()

# 3. 定義主圖 (Orchestrator)
main_workflow = StateGraph(MainState)
main_workflow.add_node("planner_agent", planner_app) # 子圖作為節點
main_workflow.add_node("executor_agent", executor_app)
#...

這種結構為 UI 的 "Scoped Chat" 提供了物理上的數據隔離基礎。

### **3.2 引入編排器 (Orchestrator/Supervisor)**

您問到：「是不是要有一個編排器 node？」答案是：**對於企業級方案，絕對需要。**

在流水線模式中，流程是寫死的（A -> B -> C）。但在實際金融業務中，流程往往是動態的：

* Auditor 發現問題，需要退回給 Executor 重做（C -> B）。
* Executor 發現數據缺失，需要退回給 Planner 重新規劃（B -> A）。
* Approval 拒絕操作，流程終止或轉入人工介入（D -> Human）。

#### **3.2.1 監督者模式 (Supervisor Pattern)**

LangGraph 提供了 **Supervisor** 模式 3。這是一個特殊的 Node（通常由 LLM 扮演），它的職責不是執行任務，而是觀察當前狀態，並決定下一個該叫誰工作。

Python

def supervisor_node(state: MainState):
    # LLM 分析當前進度與各 Agent 的輸出
    decision = llm.invoke(
        "Based on the auditor's report: {report}, what should be done next?",
        tools=
    )
    return decision

引入 Supervisor 後，您的 UI 就不再只是顯示一個進度條，而是可以顯示一個動態的 **「決策路由圖」**，讓用戶明白為什麼系統在 Auditor 階段跳回了 Planner 階段。

### **3.3 企業級狀態模式 (Enterprise State Schema)**

為了支撐 UI 的「卡片」顯示，State 不能只存文本，必須存 **結構化數據**。

**建議的全局狀態定義：**

Python

class AgentState(TypedDict):
    # 用於 UI 全局時間軸
    global_events: List[str]

    # 各 Agent 的專屬數據插槽 (Slots)
    planner_data: Optional[PlannerOutput] # 包含 Plan 對象
    executor_data: Optional # 包含執行進度 %
    auditor_data: Optional # 包含合規分數
    approval_data: Optional # 包含待審批詳情

    # 控制流狀態
    next_step: str
    errors: List[str]

這樣，當前端渲染 "Planner Card" 時，不是去解析一堆對話，而是直接讀取 planner_data 欄位。這大大降低了前端的複雜度並提升了穩定性。

## ---

**4. UI/UX 設計：範圍化對話與任務卡片 (UI/UX Transformation)**

這部分是您需求的核心。我們將詳細描述如何將上述後端架構映射到前端介面。

### **4.1 介面佈局：金融智能體儀表板 (Financial Agent Dashboard)**

摒棄單一的 Chat 窗口，採用 **「三欄式佈局（Three-Pane Layout）」**：

1. **左側：導航與編排視圖 (Orchestration Rail)**
   * 顯示主流程的 DAG（有向無環圖）或時間軸。
   * 高亮當前活躍的節點（例如：Executor 正在閃爍）。
   * 顯示 Supervisor 的決策日誌（例如：「因風險過高，決定轉交 Auditor」）。
2. **中間：任務卡片矩陣 (Task Cards Matrix)**
   * 這是主工作區。Planner, Executor, Auditor, Approval, Calculator 各佔一張卡片。
   * **狀態可視化**：
     * *Idle (灰)*：尚未啟動。
     * *Running (藍/動畫)*：正在處理。
     * *Attention (黃)*：等待用戶輸入（如 Approval）。
     * *Error (紅)*：發生錯誤。
     * *Completed (綠)*：任務完成。
3. **右側/浮層：範圍化詳細視圖 (Scoped Detail Panel)**
   * 當用戶點擊中間的某張卡片時，從右側滑出或彈出該 Agent 的專屬視圖。
   * 這就是您所謂的 **Scoped Chat**，但根據 Agent 的角色，它的形式不一定是 Chat。

### **4.2 任務卡片與 Scope 詳解**

#### **4.2.1 Planner Card & Scope**

* **Card 內容**：顯示當前計畫的摘要（例如：「共 5 個步驟，目前執行第 0 步」）。
* **Scoped UI**：
  * **形式**：**互動式大綱（Interactive Outline）** 或 **樹狀圖（Tree View）**。
  * **交互**：用戶不應該跟 Planner "聊天"，而是直接 "編輯" 計畫。
  * **功能**：LangGraph 支持 update_state。UI 允許用戶拖拽調整步驟順序，或修改步驟描述。當用戶保存修改後，前端發送更新指令，後端的 Planner 狀態即被重置並基於新計畫繼續。

#### **4.2.2 Executor Card & Scope**

* **Card 內容**：顯示最近一次工具調用的結果（例如：「API: GetStockPrice(AAPL) -> $150」）。
* **Scoped UI**：
  * **形式**：**終端機/日誌視圖（Terminal/Log View）**。
  * **理由**：Executor 的工作是技術性的。Chat 氣泡不適合顯示 JSON 響應或 SQL 語句。
  * **交互**：提供 "Retry" 按鈕。如果某個工具報錯，用戶可以在此 Scope 內修正參數並單獨重試該工具調用。

#### **4.2.3 Auditor Card & Scope**

* **Card 內容**：顯示合規紅綠燈（Pass/Fail）及關鍵風險指標。
* **Scoped UI**：
  * **形式**：**差異比對視圖（Diff View）** 或 **檢查清單（Checklist）**。
  * **功能**：列出所有檢查項（如「數據來源可信度」、「金額限制」）。每一項旁邊顯示 Auditor 的判斷依據。
  * **交互**：提供 "Override"（覆蓋）功能。如果 Auditor 誤報，授權用戶可以手動將狀態改為 Pass。

#### **4.2.4 Approval Card & Scope**

* **Card 內容**：顯示「待審批」標籤，以及核心決策數據（如「轉帳金額：$50,000」）。
* **Scoped UI**：
  * **形式**：**表單（Form）**。
  * **功能**：這不是對話，是決策。顯示所有支持決策的上下文（來自 Auditor 的報告、Planner 的計畫）。
  * **交互**：兩個大按鈕 "Approve" 和 "Reject"，以及一個 "Comment" 輸入框。這對應 LangGraph 的 interrupt 機制。

#### **4.2.5 Calculator Card & Scope**

* **Card 內容**：顯示最後的計算公式與結果。
* **Scoped UI**：
  * **形式**：**Jupyter Notebook 風格的 Cell**。
  * **功能**：顯示計算的代碼與 Trace。
  * **交互**：允許用戶修改計算公式，這對於金融場景的「試算（What-if Analysis）」非常重要。

## ---

**5. 技術實現細節：從代碼到體驗 (Technical Implementation)**

要實現上述 UI，您需要解決三個核心技術難題：**串流路由（Streaming Routing）**、**中斷與恢復（Interrupt & Resume）**、以及**時間旅行（Time Travel）**。

### **5.1 串流數據的精準路由 (Precision Event Routing)**

在 Chat 模式下，所有的 token 都流向同一個窗口。但在 Scoped UI 中，前端必須知道：「這個 token 是屬於 Planner 的，還是 Executor 的？」

#### **5.1.1 利用 Metadata 進行過濾**

LangGraph 的 astream_events API 會輸出包含 metadata 的事件流 5。當您使用 Subgraphs 時，metadata 會包含 langgraph_node 和 langgraph_path。

**後端代碼要求**：確保每個節點有名稱。

Python

# 在編譯圖時
app = workflow.compile()

**前端數據流處理（TypeScript 邏輯示意）**：

TypeScript

const handleStreamEvent = (event) => {
  const nodeName = event.metadata.langgraph_node;
  const path = event.metadata.langgraph_path; // 例如 ['main', 'planner', 'draft']

  // 1. 判斷屬於哪個 Scope
  if (path.includes('planner')) {
    // 將 token 分發到 Planner 的 Store
    plannerStore.appendToken(event.data.chunk);
  } else if (path.includes('executor')) {
    // 將 token 分發到 Executor 的 Store
    executorStore.appendLog(event.data.chunk);
  }

  // 2. 更新卡片狀態
  if (event.event === 'on_chain_start') {
    cardStore.setStatus(nodeName, 'Running');
  } else if (event.event === 'on_chain_end') {
    cardStore.setStatus(nodeName, 'Idle');
  }
};

這種基於事件標籤的路由機制，是實現多視窗並行更新的基礎。

### **5.2 處理用戶中斷與修改 (Handling Interrupts & Modification)**

您問到：「如果正在某一個流程，我怎樣根據 user 的輸入去判斷，例如他想修改之前某一個node的步驟還是繼續？」

這涉及到 LangGraph 的兩大功能：**Interrupts** 和 **Checkpoints**。

#### **5.2.1 Approval 節點的中斷設計**

對於 Approval 節點，不應該讓 LLM 生成文字問用戶「你同意嗎？」，而應該使用 interrupt 函數 7。

**後端實作**：

Python

from langgraph.types import interrupt, Command

def approval_node(state):
    # 暫停執行，並將數據傳給前端
    human_feedback = interrupt({
        "type": "approval_request",
        "payload": {
            "amount": state['amount'],
            "risk": state['risk_score']
        }
    })

    # 恢復執行後的邏輯
    if human_feedback['action'] == 'approve':
        return Command(goto="calculator")
    else:
        return Command(goto="planner") # 拒絕則退回規劃

前端行為：
當前端收到 __interrupt__ 事件時，Approval Card 會變成黃色高亮，並彈出按鈕。用戶點擊 "Approve" 後，前端調用 API 發送 Command(resume={'action': 'approve'})，流程繼續。

#### **5.2.2 修改之前節點（Time Travel）**

如果用戶在 Executor 執行到一半時，想修改 Planner 的計畫，這需要用到 LangGraph 的 **Checkpoint** 功能 8。

1. **獲取歷史**：前端調用 client.threads.get_state_history(thread_id)，獲取過去每一個步驟的 Checkpoint ID。
2. **展示歷史**：在 UI 上，這可以表現為一個「撤銷（Undo）」按鈕或時間軸滑塊。
3. 分叉執行（Forking）：
   當用戶決定修改 Planner 的輸出時，前端調用 client.threads.update_state()：
   Python
   # 偽代碼：更新特定 checkpoint 的狀態
   config = {"configurable": {"thread_id": "123", "checkpoint_id": "step_5"}}
   client.update_state(
       config,
       {"planner_data": {"plan": "New Revised Plan..."}}, # 注入新的狀態
       as_node="planner" # 指定從哪個節點開始應用
   )

4. **重播**：接著調用 stream，LangGraph 會從那個 checkpoint 開始，使用新的狀態重新運行後續的所有流程（Executor, Auditor 等）。

這就是所謂的 **「人機協作修正（Human-in-the-loop Correction）」**，是企業級 Agent 的標配功能。

## ---

**6. 改動複雜度分析與實施路徑 (Complexity & Roadmap)**

### **6.1 複雜度評估：高 (High)**

這不是一個簡單的 UI 改版，而是全棧架構的升級。

* **後端複雜度**：
  * **狀態管理**：需要從非結構化列表轉向結構化 TypedDict。
  * **圖結構**：需要拆分主圖與子圖。
  * **持久化**：必須配置 Postgres 或 Redis Checkpointer，記憶體存儲（MemorySaver）無法滿足生產環境的長時任務需求 10。
* **前端複雜度**：
  * **狀態同步**：需要構建一個強大的前端 Store（如 Redux/Zustand）來映射後端的 Graph State。
  * **事件處理**：WebSocket/SSE 的連接管理與斷線重連機制。
  * **組件化**：開發專屬的 Card 和 Modal 組件。

### **6.2 建議實施路徑**

為了降低風險，建議分四個階段進行：

| 階段 | 任務 | 目標 |
| :---- | :---- | :---- |
| **Phase 1: 結構化狀態** | 修改 AgentState，增加 planner_output, audit_report 等專屬欄位。 | 讓後端數據具備結構，為 UI 讀取做準備。此時 UI 仍可保持 Chat 形式。 |
| **Phase 2: 子圖拆分** | 將 Planner 和 Executor 封裝為獨立 Subgraphs。 | 實現狀態隔離，避免上下文污染。確保 astream_events 能輸出正確路徑。 |
| **Phase 3: 任務卡片 UI** | 開發 Dashboard 原型，利用 astream_events 點亮卡片狀態（Running/Done）。 | 驗證串流路由機制是否可行。暫時點擊卡片只顯示原始 JSON。 |
| **Phase 4: 交互與中斷** | 實作 Approval 的 interrupt 和 Scoped Chat 的編輯功能。 | 實現完整的 HITL 能力。引入 Supervisor 進行動態路由。 |

## ---

**7. 企業級金融 Agent 的特殊考量 (Enterprise Considerations)**

在設計企業級方案時，除了功能實現，還必須考慮以下非功能性需求：

### **7.1 審計軌跡 (Audit Trail)**

在金融領域，**所有的交互都必須被記錄**。

* **技術實現**：不要只依賴 LangGraph 的 Checkpoint。建議在每個 Node 執行完畢後，將關鍵決策異步寫入一個不可篡改的審計日誌（Audit Log）數據庫。
* **UI 呈現**：在 Auditor Card 中，提供一個「下載審計報告」的功能，包含每個步驟的 Input/Output Snapshot 以及用戶的 Approval 記錄。

### **7.2 權限控制 (RBAC)**

不是所有用戶都能點擊 Approval Card 上的 "Approve" 按鈕。

* **UI 邏輯**：前端應根據當前用戶的角色（如 Manager vs. Analyst），動態禁用或隱藏特定卡片的操作按鈕。
* **後端驗證**：在 interrupt 恢復時，後端必須再次校驗發送 Resume 指令的用戶是否具備權限。

### **7.3 延遲與反饋 (Latency & Feedback)**

金融計算（Calculator）或複雜規劃（Planner）可能耗時較長。

* **樂觀更新 (Optimistic UI)**：當用戶修改計畫並提交時，UI 應立即顯示「正在更新...」，而不是等待服務器響應。
* **後台運行**：利用 LangGraph Cloud 或隊列機制，支持 Agent 在後台運行，用戶關閉瀏覽器後再回來查看進度（利用 thread_id 恢復會話）。

## ---

**8. 結論 (Conclusion)**

將您的金融 Agent 從線性 Chat 轉型為範圍化任務卡片 UI，雖然涉及較高的開發複雜度，但對於提升系統的**可用性（Usability）**、**可控性（Controllability）**與**合規性（Compliance）**至關重要。

您的現有代碼需要從「單一腳本」向「微服務化智能體」演進。通過引入 **LangGraph Subgraphs** 實現邏輯隔離，利用 **Supervisor** 實現動態編排，並配合前端的 **Event-Driven Dashboard**，您將能夠構建出一個真正符合企業級標準的金融智能體系統。這不僅解決了「如何修改前一步驟」的交互難題，更為未來擴展更多專業節點（如 Risk Analyst, Compliance Officer）奠定了堅實的架構基礎。

## ---

**9. 附錄：關鍵技術概念對照表**

| 概念 | 傳統 Chatbot 實作 | 企業級 Agent 實作 (LangGraph) | 作用 |
| :---- | :---- | :---- | :---- |
| **對話歷史** | List of Strings | Scoped State (Subgraphs) | 隔離不同智能體的上下文 |
| **人工介入** | 無 / 關鍵詞觸發 | Interrupt / Checkpoint | 允許暫停、審批與修改 |
| **流程控制** | Hardcoded Chain | Supervisor / Router | 實現動態、條件式執行 |
| **UI 更新** | Append Text | Event Routing (Metadata) | 實現多區域並行更新 |
| **錯誤恢復** | 重啟對話 | Time Travel (Update State) | 允許回退到特定步驟重試 |

---

(註：本報告所有技術建議均基於 LangGraph v0.2+ 版本的特性進行設計，並參考了最新的 Agentic Design Patterns 2。)

#### **引用的著作**

1. Conversational Patterns in LangGraph using Subgraphs | by Vinodh S Iyer | Medium, 檢索日期：1月 5, 2026， [https://medium.com/@vin4tech/conversational-patterns-in-langgraph-using-subgraphs-366d4dd27ebc](https://medium.com/@vin4tech/conversational-patterns-in-langgraph-using-subgraphs-366d4dd27ebc)
2. Subagents - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/python/langchain/multi-agent/subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)
3. LangGraph-style Agent Graphs: Fundamentals, Advanced Patterns, Features, and Future Directions - MGX, 檢索日期：1月 5, 2026， [https://mgx.dev/insights/langgraph-style-agent-graphs-fundamentals-advanced-patterns-features-and-future-directions/79417dacdf734afb986984fa2f1b692d](https://mgx.dev/insights/langgraph-style-agent-graphs-fundamentals-advanced-patterns-features-and-future-directions/79417dacdf734afb986984fa2f1b692d)
4. Multi-Agent Conversational Graph Designs : r/LangChain - Reddit, 檢索日期：1月 5, 2026， [https://www.reddit.com/r/LangChain/comments/1dogdy8/multiagent_conversational_graph_designs/](https://www.reddit.com/r/LangChain/comments/1dogdy8/multiagent_conversational_graph_designs/)
5. Streaming - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/python/langgraph/streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
6. Preserve event metadata of custom streaming events · Issue #6330 · langchain-ai/langgraph, 檢索日期：1月 5, 2026， [https://github.com/langchain-ai/langgraph/issues/6330](https://github.com/langchain-ai/langgraph/issues/6330)
7. Interrupts - Docs by LangChain, 檢索日期：1月 5, 2026， [https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/breakpoints/](https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/breakpoints/)
8. Use time-travel - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/python/langgraph/use-time-travel](https://docs.langchain.com/oss/python/langgraph/use-time-travel)
9. Persistence - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/javascript/langgraph/persistence](https://docs.langchain.com/oss/javascript/langgraph/persistence)
10. Need guidance on using LangGraph Checkpointer for persisting chatbot sessions : r/LangChain - Reddit, 檢索日期：1月 5, 2026， [https://www.reddit.com/r/LangChain/comments/1on4ym0/need_guidance_on_using_langgraph_checkpointer_for/](https://www.reddit.com/r/LangChain/comments/1on4ym0/need_guidance_on_using_langgraph_checkpointer_for/)
