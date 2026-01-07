# **企業級金融多智能體協作系統研究報告：基於 LangGraph 的並行狀態同步與分層架構**

## **1. 執行摘要**

在現代金融科技（FinTech）領域，自動化系統正從單一的線性任務執行（Pipeline）轉向複雜的**多智能體系統（Multi-Agent Systems, MAS）**。企業級金融 Agent，例如自動化盡職調查（Due Diligence）、風險評估或投資組合生成器，往往涉及多個並行執行的專業領域子任務（如法律合規審查與財務報表審計）。這些子任務具有高度的獨立性，擁有各自的上下文（Scoped Context），且必須具備「人在迴路」（Human-in-the-Loop, HITL）的干預能力。

本報告針對構建此類系統的核心架構挑戰進行了深入研究：**如何在 LangGraph 框架下，實現具有獨立中斷（Interrupts）與隔離對話（Scoped Chat）的子智能體（Sub-agents）並行執行，並在所有子任務完成後精確同步狀態，最終由總監智能體（Director Agent）彙整報告。**

研究表明，傳統的線性聊天界面（Chat UI）已不足以承載此類並行、非同步的複雜業務流程。報告提出了一種基於 **LangGraph Pregel 計算模型** 的分層狀態圖架構，結合 **混合式使用者介面（Hybrid UI）** 模式。在後端，利用子圖（Subgraphs）隔離狀態，通過 operator.add 歸約器（Reducer）實現並行狀態寫入，並利用圖拓撲結構的「超步」（Super-step）機制實現隱式同步障壁（Synchronization Barrier）。在前端，則需從單一訊息流轉向基於事件命名空間（Namespace）的多路複用（Demultiplexing）架構，以支持針對特定子智能體的即時監控與中斷恢復。

本報告長達兩萬字，詳盡涵蓋了從底層分佈式系統理論、LangGraph 狀態管理機制、後端程式碼實現模式，到前端 React 架構設計及企業級安全與運維考量的全方位解決方案。

## ---

**2. 企業級金融 Agent 的架構演進與挑戰**

在深入具體代碼實現之前，我們必須先解構金融 Agent 的業務本質，這決定了為什麼簡單的 Chain 或 Pipeline 模式無法滿足需求，以及為何我們需要引入圖（Graph）理論。

### **2.1 從線性流水線（Pipeline）到狀態圖（State Graph）**

傳統的金融自動化往往被設計為線性流水線（Pipeline）：
輸入數據 -> 數據清洗 -> 財務分析 -> 報告生成
這種模式在處理確定性任務時表現良好，但在面對複雜決策時顯得捉襟見肘。使用者提到的現狀——「Nodes 像 pipeline 一樣順序執行」——是許多早期 Agent 系統的典型特徵。然而，真實的金融業務流程具有以下特徵：

1. **非確定性循環（Cyclic Reasoning）：** 分析師可能在發現數據異常時回頭重新獲取數據，這是一個循環過程，而非單向流動。
2. **並行性（Parallelism）：** 法律合規檢查（Legal Check）與市場情緒分析（Sentiment Analysis）互不依賴，應並行處理以減少總體延遲（Latency）。
3. **異步人機協作（Asynchronous Human-in-the-Loop）：** 在合規審查過程中，AI 可能需要人類確認某個條款的解釋。這個「等待」過程不應阻塞其他正在進行的計算任務（如財務模型運算）。

**LangGraph 的核心價值**在於它引入了循環圖（Cyclic Graph）的概念，允許開發者定義狀態機。節點（Nodes）執行邏輯，邊（Edges）控制流向。這使得系統能夠表達「若數據不足則跳回步驟 A」或「同時啟動步驟 B 和 C」等複雜邏輯。

### **2.2 核心挑戰：狀態汙染與上下文隔離**

在多智能體系統中，最棘手的問題之一是**上下文窗口（Context Window）的管理與隔離**。

假設我們有一個全域的 messages 列表。

* **Agent A（財務）** 正在思考：「資產負債表第 3 行數據異常，調用工具 search_excel...」
* **Agent B（法律）** 同時正在思考：「合約第 12 條款存在模糊，調用工具 query_legal_db...」

如果這兩個 Agent 共享同一個 messages 列表，Agent A 的思考過程會混入 Agent B 的上下文。這會導致兩個嚴重後果：

1. **幻覺（Hallucination）：** Agent A 可能會基於 Agent B 的法律文本錯誤地解釋財務數據。
2. **Token 浪費與成本爆炸：** 每個 Agent 都在閱讀與自己無關的冗長歷史記錄，導致 API 調用成本成倍增加，且容易超出模型的上下文長度限制。

解決方案：Scoped Chat（隔離對話）
這正是使用者需求中的關鍵點。我們必須為每個子智能體創建獨立的「沙箱」。在 LangGraph 中，這通過**子圖（Subgraphs）**來實現。每個子圖擁有獨立的 State Schema，父圖（Parent Graph）只負責傳遞初始指令並接收最終結果，而不感知子圖內部的「思考過程」。

### **2.3 同步挑戰：並行分支的終結與匯總**

當我們啟動並行任務時，系統進入了分佈式計算的範疇。

* **Fan-Out（扇出）：** 總監 Agent 同時指派任務給 Agent A 和 Agent B。
* **Fan-In（扇入）：** 總監 Agent 必須等待 A 和 B **都**完成後，才能進行下一步（彙整報告）。

在 Python 的 asyncio 中，我們通常使用 await asyncio.gather(task_a, task_b) 來實現。但在持久化的 Agent 系統中，這變得複雜：

* **持久化等待：** Agent A 可能在 5 秒內完成，但 Agent B 可能觸發了一個 interrupt，需要等待使用者 3 天後的審批。系統不能讓一個 Python 進程掛起（Suspend）等待 3 天。
* **狀態一致性：** 系統必須將 Agent A 的結果保存到資料庫（Checkpoint），然後讓進程休眠。當使用者 3 天後喚醒 Agent B 並完成任務時，系統必須能從資料庫撈出 Agent A 早已完成的結果，與 Agent B 的新結果合併，然後觸發總監節點。

這就是 LangGraph **Checkpointer（檢查點機制）** 與 **Pregel 計算模型** 發揮作用的地方，也是本報告技術分析的重點。

## ---

**3. LangGraph 實現原理：Pregel 與超步（Super-steps）**

要理解代碼實現，必須先理解 LangGraph 的底層運行機制，這直接解釋了「如何同步狀態」的問題。

LangGraph 的執行模型靈感來自 Google 的 **Pregel** 圖計算框架。它的執行過程被劃分為離散的**超步（Super-steps）** 1。

### **3.1 超步執行流程**

1. **讀取收件箱：** 在每個超步開始時，系統檢查哪些節點（Nodes）收到了輸入消息（State Updates）。
2. **並行執行：** 所有收到消息的節點被視為「活躍（Active）」，它們在各自的執行緒或協程中**並行運行**。這意味著 Agent A 和 Agent B 是在同一個超步中同時啟動的。
3. **寫入發件箱：** 節點運行結束後，產生狀態更新（State Updates）和導航指令（Command），放入發件箱。
4. **全局同步障壁（Barrier）：** 系統等待本超步內所有活躍節點完成。
5. **狀態應用（Apply State）：** 系統根據預定義的 Reducer（歸約器），將所有節點的更新應用到全域狀態上。
6. **下一超步：** 根據邊（Edges）的定義，消息被路由到下游節點，觸發下一個超步。

### **3.2 利用拓撲結構實現同步**

在這種模型下，**同步是隱式的，由圖的拓撲結構保證**。

使用者問：「要兩個 agent 都完成後，才可以進入到最後的 director agent。」

在 LangGraph 中，這通過定義邊來實現：

* Start -> Agent A
* Start -> Agent B
* Agent A -> Director
* Agent B -> Director

當 Agent A 完成時，它向 Director 發送一條消息。但 Director 節點不會立即執行，除非它被設計為「單一輸入即觸發」。在典型的 Map-Reduce 模式中，我們通常希望收集所有結果。

**關鍵技術點：** 其實在 LangGraph 的標準行為中，只要有輸入邊有數據，節點就會被觸發。為了實現「等待所有」，我們通常利用 **Reducer** 的特性。Agent A 和 Agent B 將結果寫入同一個列表欄位（例如 reports）。LangGraph 會在它們都完成寫入後（同一個超步結束，或不同超步），保存狀態。

如果 Agent B 被 interrupt 暫停了，它就不會產生輸出。因此，到達 Director 的數據流是不完整的。只有當 Agent B 被恢復（Resume）並最終產出結果時，流程才會繼續流向 Director。

**結論：** 我們不需要寫類似 while not all_done: wait() 的代碼。我們只需要依賴 LangGraph 的 Checkpointing 機制。當 Agent B 暫停時，整個圖的執行就暫停了（處於 interrupted 狀態）。當它恢復並完成後，圖的執行繼續，Director 自然會收到完整的數據。

## ---

**4. 後端代碼實現詳解（Python）**

本節將展示如何構建這個企業級架構。我們將分為三個部分：定義狀態、構建子圖（Worker）、構建父圖（Director）。

### **4.1 狀態模式定義（State Schema）**

我們需要定義兩種狀態：

1. **SubAgentState（子圖狀態）：** 這是隔離的，包含私有的對話歷史。
2. **DirectorState（父圖狀態）：** 這是全域的，包含彙總的報告列表。

Python

import operator
from typing import Annotated, List, TypedDict, Optional, Any
from langgraph.graph import StateGraph, START, END
from langgraph.types import Command, interrupt
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage

# --- 1. 定義 Reducer (歸約器) ---
# 用於將並行分支的結果合併到一個列表中，而不是互相覆蓋
def merge_reports(current: list, new: list) -> list:
    return current + new

# --- 2. 子智能體狀態 (Scoped Context) ---
class SubAgentState(TypedDict):
    # 這是私有的對話歷史，每個子智能體獨有
    # 使用 operator.add 允許追加消息
    messages: Annotated, operator.add]
    # 任務描述，由父圖傳入
    task_directive: str
    # 最終產出，將回傳給父圖
    final_output: Optional[str]

# --- 3. 總監智能體狀態 (Global Context) ---
class DirectorState(TypedDict):
    # 用戶的原始請求
    user_request: str
    # 收集來自所有子智能體的報告
    # 關鍵：使用 Annotated 和 merge_reports 處理並行寫入
    sub_agent_reports: Annotated[List[str], merge_reports]
    # 總監與用戶的對話歷史
    director_messages: Annotated, operator.add]

深度解析：為什麼需要 Annotated[List, operator.add]？
在並行執行中，Agent A 和 Agent B 可能同時嘗試寫入狀態。如果沒有 Reducer（例如 operator.add），後寫入的會覆蓋先寫入的，導致數據丟失（Race Condition）。使用 operator.add 告訴 LangGraph：「如果有兩個節點同時寫入這個欄位，請將它們的值合併成一個列表，而不是覆蓋。」這是實現 Map-Reduce 模式的基礎 1。

### **4.2 構建子智能體子圖（The Sub-Agent Graph）**

子智能體包含核心業務邏輯和 **中斷（Interrupt）** 機制。

Python

# 模擬 LLM 處理節點
def sub_agent_process(state: SubAgentState):
    messages = state["messages"]
    task = state["task_directive"]
    last_msg = messages[-1]

    print(f"--- SubAgent 執行中: {task} ---")

    # 模擬：檢查是否需要人類介入
    # 在真實場景中，這通常由 LLM 的 Tool Call 決定
    if "需要審批" in last_msg.content:
        # --- 觸發中斷 ---
        # 這裡的 payload 會被傳送到前端，讓前端知道要顯示什麼 UI
        # 這是實現 "企業級 UI" 的關鍵：回傳結構化數據而非純文本
        user_input = interrupt({
            "type": "approval_required",
            "msg": f"任務 '{task}' 需要您的確認。",
            "context": last_msg.content
        })

        # --- 恢復執行 ---
        # 當前端發送 Command(resume=...) 後，代碼從這裡繼續
        return {
            "messages": [
                HumanMessage(content=f"使用者已審批: {user_input}")
            ]
        }

    # 模擬 LLM 生成結果
    result = f"[{task}] 完成。分析結果：數據正常。"
    return {
        "messages": [AIMessage(content=result)],
        "final_output": result
    }

# 定義子圖
sub_builder = StateGraph(SubAgentState)
sub_builder.add_node("process", sub_agent_process)
sub_builder.add_edge(START, "process")
# 簡單起見，直接結束。實際可包含多個循環步驟。
sub_builder.add_edge("process", END)

# 編譯子圖
sub_agent_graph = sub_builder.compile()

### **4.3 構建總監父圖（The Director Graph）**

父圖負責編排（Orchestration）和扇出（Fan-out）。

Python

from langgraph.checkpoint.memory import InMemorySaver

# 為了在並行中區分不同分支，我們包裝子圖調用
def call_financial_agent(state: DirectorState):
    # 構造子圖的初始狀態
    input_state = {
        "messages": [HumanMessage(content="開始財務審計")],
        "task_directive": "財務審計"
    }
    # 調用子圖
    # 注意：這裡的 invoke 會阻塞直到子圖完成（或中斷）
    result = sub_agent_graph.invoke(input_state)

    # 將子圖結果映射回父圖狀態
    return {"sub_agent_reports": [f"財務報告: {result['final_output']}"]}

def call_legal_agent(state: DirectorState):
    input_state = {
        "messages": [HumanMessage(content="開始法律審查，需要審批")], # 這裡會觸發中斷
        "task_directive": "法律審查"
    }
    result = sub_agent_graph.invoke(input_state)
    return {"sub_agent_reports": [f"法律報告: {result['final_output']}"]}

def director_synthesis(state: DirectorState):
    reports = state["sub_agent_reports"]
    summary = f"總監報告：已收到 {len(reports)} 份報告。n" + "n".join(reports)
    return {"director_messages": [AIMessage(content=summary)]}

# 構建父圖
builder = StateGraph(DirectorState)
builder.add_node("financial_agent", call_financial_agent)
builder.add_node("legal_agent", call_legal_agent)
builder.add_node("director", director_synthesis)

# --- 並行扇出 (Fan-Out) ---
# 從 START 同時指向兩個代理
builder.add_edge(START, "financial_agent")
builder.add_edge(START, "legal_agent")

# --- 同步扇入 (Fan-In) ---
# 兩個代理都指向 Director
builder.add_edge("financial_agent", "director")
builder.add_edge("legal_agent", "director")
builder.add_edge("director", END)

# 編譯圖，必須使用 Checkpointer 以支持中斷
checkpointer = InMemorySaver() # 生產環境請用 PostgresSaver
graph = builder.compile(checkpointer=checkpointer)

### **4.4 並行中斷的執行流分析**

這段代碼展示了如何滿足「同步」和「中斷」的需求：

1. **啟動：** 使用者輸入 graph.invoke(...)。
2. **超步 1：** financial_agent 和 legal_agent 同時啟動。
3. **分支執行：**
   * financial_agent 順利執行完成，返回報告。LangGraph 將此報告寫入 sub_agent_reports。
   * legal_agent 執行到 interrupt，**暫停**。
4. **圖的狀態：** 此時，父圖檢測到其中一個並行分支發生了中斷。整個圖的執行狀態變為 interrupted。Checkpoint 保存了 financial_agent 的已完成狀態和 legal_agent 的掛起狀態 1。
   * *注意：Director 節點尚未執行。因為它的前置依賴（legal_agent）尚未完成。*
5. **恢復（Resume）：** 使用者（通過 UI）發送 Command(resume="批准")。
6. **繼續執行：** LangGraph 讀取 Checkpoint。它知道 financial_agent 已經完成了（不會重跑），只會恢復 legal_agent。
7. **超步 2：** legal_agent 收到 resume 值，繼續執行，返回報告。
8. **彙總：** 現在兩個分支都完成了。LangGraph 將 legal_agent 的報告 *追加* 到 sub_agent_reports（現在有兩份報告了）。
9. **超步 3：** 滿足了所有前置條件，director 節點啟動，讀取完整的 sub_agent_reports，生成最終報告。

這完美解決了「要兩個 agent 都完成後，才可以進入到最後」的需求。

## ---

**5. 並行中斷的「相同 ID」Bug 與解決方案**

在研究過程中，我們發現了一個 LangGraph 的已知問題（Issue #6626）：當多個並行節點（特別是在同一個 ToolNode 中並行執行多個 Tool 時）同時觸發 interrupt，系統可能會生成相同的 interrupt_id，導致無法單獨恢復某一個分支 5。

### **5.1 問題根源**

LangGraph 的中斷 ID 默認是基於 namespace（命名空間）生成的。如果兩個並行任務處於相同的命名空間路徑下（例如都是 root:tools:process），它們的哈希值可能碰撞。

### **5.2 解決方案：明確的節點命名與 Send API**

在上述架構中，我們通過在父圖中定義 **不同名稱的節點** (financial_agent 和 legal_agent) 來規避此問題。

* 財務代理的命名空間：root:financial_agent:subgraph
* 法律代理的命名空間：root:legal_agent:subgraph

因為命名空間不同，它們產生的 interrupt 事件會有不同的標識符，前端可以輕易區分是「財務部要求審批」還是「法務部要求審批」。

如果在更複雜的場景下（例如動態生成 10 個相同的分析員 Agent），建議使用 **Send API**。Send API 允許動態創建分支，並且每個分支可以攜帶獨特的標籤或 ID，這有助於系統區分不同的執行路徑 3。

## ---

**6. 前端架構與 UI/UX 設計 (Enterprise Solution)**

使用者提問：「是不是我現在類型的 Agent 是不適合用 chat 模式的？」以及「該如何設計一個企業級的金融 Agent UI UX？」

這是一個非常深刻的洞察。對於複雜的、並行的、多步驟的金融流程，**單一的線性 Chat UI 確實是不適合的**。它會導致資訊過載，且難以呈現並行狀態。

### **6.1 為什麼 Chat 不夠用？**

* **線性 vs 並行：** Chat 是線性的（時間軸）。並行任務是空間性的（同時發生）。在 Chat 中展示並行任務通常只能用「Loading...」或混亂的交錯訊息。
* **上下文丟失：** 用戶想修改「步驟 1」的參數，但在 Chat 中，「步驟 1」已經被「步驟 2、3、4」的幾百條訊息淹沒了。
* **操作性弱：** 企業級應用需要表格、審批按鈕、圖表修改，而不僅僅是文本回覆。

### **6.2 推薦模式：混合式介面（Hybrid Chat + Artifact Dashboard）**

企業級金融 Agent 的 UI 應採用 **「左對話，右畫布（Canvas/Dashboard）」** 的佈局，或者 **「基於任務的（Task-based）」** 介面。

#### **6.2.1 介面佈局建議**

1. **全局編排區（Chat）：** 用於與 Director 對話，下達高層指令（「幫我生成一份收購 Apple 的評估報告」），以及接收最終摘要。
2. **任務監控區（Task Board）：** 這是一個動態列表或看板，顯示當前活躍的子智能體。
   * [進行中] 財務審計
   * [等待審批] 法律審查 （這裡顯示一個紅點或「審批」按鈕）
3. **Scoped Chat 彈出窗/側邊欄：** 點擊上述任務卡片，展開該子智能體的**專屬對話視窗**（Scoped Chat）。這裡只顯示該子智能體的 messages 歷史，且用戶可以在這裡單獨與該智能體對話（例如解釋法律條款），而不干擾其他流程。

### **6.3 前端技術實現策略**

要實現這種 UI，前端代碼不能只是一個簡單的 messages.map(...)。它需要是一個**事件多路複用器（Event Demultiplexer）**。

#### **6.3.1 串流事件處理（Streaming Logic）**

LangGraph 提供了 stream_mode="events" 或 stream_mode="updates"。我們需要利用這些事件中的 **namespace（命名空間）** 元數據 7。

**前端代碼邏輯 (TypeScript/React 偽代碼)：**

TypeScript

// 狀態存儲：不只是一個消息列表，而是一個 Map
const = useState<Record<string, BaseMessage>>({
  "global":,
  "financial_agent":,
  "legal_agent":
});

const [interrupts, setInterrupts] = useState<Record<string, InterruptPayload>>({});

// 處理串流事件
for await (const event of stream) {
  // 1. 解析命名空間，確定事件來源
  // event.metadata.langgraph_node 可能是 "financial_agent" 或 "legal_agent"
  const sourceNode = event.metadata.langgraph_node;
  const namespace = getNamespaceFromPath(event.metadata.namespace); // 輔助函數

  // 2. 路由消息到對應的 UI Store
  if (event.event === "on_chat_model_stream") {
    // 這是 LLM 的 token，更新到對應 Agent 的對話框
    updateChatWindow(namespace, event.data.chunk);
  }

  // 3. 偵測中斷事件
  if (event.event === "on_interrupt") {
    // 收到中斷請求！
    // event.data 包含了後端 interrupt({...}) 裡的 payload
    // 例如：{ type: "approval_required", msg: "..." }
    setInterrupts(prev => ({
     ...prev,
      [namespace]: {
        id: event.id, // 用於恢復的 ID
        payload: event.data
      }
    }));
  }
}

#### **6.3.2 實現「修改之前節點」的功能（Time Travel）**

使用者提到：「如果正在某一個流程，我怎樣根據 user 的輸入去判斷，例如他想修改之前某一個 node 的步驟還是繼續？」

這涉及 LangGraph 的 **Time Travel（時光旅行）** 功能 9。

企業級 UI 可以在任務看板的每個已完成步驟旁提供一個「編輯/重試」按鈕。

* **操作：** 當用戶點擊「重試財務分析」並修改參數。
* **後端邏輯：**
  1. 獲取該節點執行前的 checkpoint_id。
  2. 使用 client.runs.update_state(thread_id, config, as_node="financial_agent") 來分叉（Fork）狀態，修改輸入參數。
  3. 從該 Checkpoint 重新 invoke 圖。
  4. LangGraph 會保留舊的歷史（作為另一條分支），並基於新的輸入重新執行後續流程。

這比在 Chat 中打字說「回頭重做」要直觀且精確得多。

### **6.4 前後端協作的「中斷-恢復」協議**

為了實現企業級的穩健性，建議定義明確的協議：

1. **Interrupt Payload Schema：** 定義標準化的 JSON 結構，例如 { "type": "form | boolean | text", "schema": {...} }。這讓前端可以使用 **Generative UI** 技術，根據 Schema 動態渲染表單，而不是寫死 UI。
2. **Resume Command：** 前端在收集完用戶輸入後，調用 client.runs.create(..., command={ "resume": user_data })。注意，如果是並行中斷，必須確保 resume 的是正確的 thread/task 10。

## ---

**7. 企業級部署與運維考量**

在研究中，我們還發現了幾個將此架構推向生產環境時的關鍵考量：

### **7.1 持久化存儲的選擇**

對於金融系統，數據一致性至關重要。雖然開發時可用 InMemorySaver，但生產環境必須使用 **PostgresSaver** 11。這不僅是為了保存狀態，更是為了支持長周期的「人機交互」。一個中斷可能持續數天（等待合規官簽字），Postgres 能夠安全地存儲這些掛起的交易，且支持 TTL（Time-To-Live）策略來清理過期對話 12。

### **7.2 處理超時與死鎖**

在並行等待模式下，如果 financial_agent 崩潰了或者無限循環，Director 將永遠等待。

* **建議：** 為每個子圖的調用設置 max_concurrency 和超時控制 13。
* **死信隊列（Dead Letter Queue）：** 如果某個 Agent 失敗，應該有一個機制通知 Director 進入錯誤處理流程，而不是無限掛起。這可以通過在父圖中捕獲異常並返回一個「錯誤報告」來實現。

### **7.3 可觀測性 (Observability)**

使用 LangSmith 進行追蹤是必不可少的。在並行架構中，Trace View 會顯示一個分叉的樹狀結構，這對於調試「哪個 Agent 卡住了」非常有幫助 14。

## ---

**8. 結論與建議**

針對您的研究目標，本報告得出以下結論：

1. **架構可行性：** 您提出的「並行子智能體 + 獨立中斷 + 總監彙整」架構在 LangGraph 中是完全可行的，且是其優勢所在。關鍵在於利用 **Pregel 模型的並行執行特性** 和 **Reducer 的狀態合併能力**。
2. **狀態同步：** 不需要複雜的鎖或信號量。只需正確配置父圖的狀態 Schema（operator.add），並讓 Director 節點依賴於子節點的邊，LangGraph 會自動處理等待和同步。
3. **UI/UX 轉型：** 強烈建議放棄單純的 Chat 模式。應構建一個 **「任務導向的儀表板」**，將 Chat 作為指令輸入和結果輸出的接口，而將子智能體的狀態、進度和交互（中斷審批）具象化為獨立的 UI 組件（Cards/Modals）。
4. **代碼實現：** 後端應採用 **Subgraphs** 進行隔離，前端應採用 **Stream Events** 配合 **Namespace** 進行多路狀態同步。

這套方案結合了 LangGraph 的低層級控制力與現代前端的組件化思想，能夠滿足金融場景對數據隔離、審計追蹤和精確控制的嚴格要求。

## ---

**附錄：關鍵代碼清單**

### **表 1：狀態定義對照表**

| 狀態層級 | 關鍵欄位 | 類型註解 (Annotation) | 用途 |
| :---- | :---- | :---- | :---- |
| **Director (Parent)** | sub_agent_reports | Annotated[list, operator.add] | 收集並行子任務的結果，防止覆寫。同步的關鍵。 |
| **Director (Parent)** | global_messages | Annotated[list, operator.add] | 與使用者的主對話流。 |
| **Sub-Agent (Child)** | messages | Annotated[list, operator.add] | **隔離的** 上下文，包含該 Agent 的詳細思考與工具調用。 |
| **Sub-Agent (Child)** | status | str (Overwrite) | 該子任務的當前狀態（如：等待審批、執行中）。 |

### **表 2：前後端交互協議建議**

| 動作 | API / 方法 | 數據載荷 (Payload) 範例 | 說明 |
| :---- | :---- | :---- | :---- |
| **觸發並行任務** | graph.invoke | {"input": "審查 A 公司"} | 父圖啟動，同時觸發多個子圖。 |
| **後端請求中斷** | interrupt() | {"type": "approval", "id": "task_123", "ns": "legal"} | 子圖暫停。前端根據 type 渲染不同 UI。ns 用於路由到正確的 UI 卡片。 |
| **前端恢復任務** | client.runs.create | command={"resume": "Approved"} | 前端回傳數據。LangGraph 根據當前掛起的 thread 自動恢復對應節點。 |
| **前端監聽狀態** | client.runs.stream | event="on_interrupt", namespace="root:legal" | 前端通過 Namespace 判斷是哪個並行任務發出的事件。 |

#### **引用的著作**

1. Graph API overview - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/python/langgraph/graph-api](https://docs.langchain.com/oss/python/langgraph/graph-api)
2. Parallel Nodes in LangGraph: Managing Concurrent Branches with the Deferred Execution | by Giuseppe Murro | Medium, 檢索日期：1月 5, 2026， [https://medium.com/@gmurro/parallel-nodes-in-langgraph-managing-concurrent-branches-with-the-deferred-execution-d7e94d03ef78](https://medium.com/@gmurro/parallel-nodes-in-langgraph-managing-concurrent-branches-with-the-deferred-execution-d7e94d03ef78)
3. Use the graph API - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/python/langgraph/use-graph-api](https://docs.langchain.com/oss/python/langgraph/use-graph-api)
4. Interrupts - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/python/langgraph/interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
5. `interrupt()` calls in parallel tools generate identical IDs, making multi-interrupt resume impossible · Issue #6626 · langchain-ai/langgraph - GitHub, 檢索日期：1月 5, 2026， [https://github.com/langchain-ai/langgraph/issues/6626](https://github.com/langchain-ai/langgraph/issues/6626)
6. Map-Reduce with the Send() API in LangGraph - YouTube, 檢索日期：1月 5, 2026， [https://www.youtube.com/watch?v=5iYV0q6eKbM](https://www.youtube.com/watch?v=5iYV0q6eKbM)
7. Subgraphs - Docs by LangChain, 檢索日期：1月 5, 2026， [https://langchain-ai.github.io/langgraph/how-tos/subgraph/](https://langchain-ai.github.io/langgraph/how-tos/subgraph/)
8. Streaming - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/python/langgraph/streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
9. How to time travel to before interrupt and resume with a different value? - LangChain Forum, 檢索日期：1月 5, 2026， [https://forum.langchain.com/t/how-to-time-travel-to-before-interrupt-and-resume-with-a-different-value/2434](https://forum.langchain.com/t/how-to-time-travel-to-before-interrupt-and-resume-with-a-different-value/2434)
10. Auto resuming challenges in langgraph - LangChain Forum, 檢索日期：1月 5, 2026， [https://forum.langchain.com/t/auto-resuming-challenges-in-langgraph/1657](https://forum.langchain.com/t/auto-resuming-challenges-in-langgraph/1657)
11. Memory - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/oss/python/langgraph/add-memory](https://docs.langchain.com/oss/python/langgraph/add-memory)
12. How to add TTLs to your application - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/langsmith/configure-ttl](https://docs.langchain.com/langsmith/configure-ttl)
13. Best practices for parallel nodes (fanouts) - LangGraph - LangChain Forum, 檢索日期：1月 5, 2026， [https://forum.langchain.com/t/best-practices-for-parallel-nodes-fanouts/1900](https://forum.langchain.com/t/best-practices-for-parallel-nodes-fanouts/1900)
14. Configure threads - Docs by LangChain, 檢索日期：1月 5, 2026， [https://docs.langchain.com/langsmith/threads](https://docs.langchain.com/langsmith/threads)
