# **LangGraph Checkpointer 機制深度技術調研報告：原理、架構與並行子圖狀態管理**

## **1. 執行摘要 (Executive Summary)**

本研究報告旨在針對 LangGraph 框架中的 Checkpointer（檢查點）機制進行詳盡的技術剖析，特別聚焦於其在複雜 AI Agent 架構中的應用，包括巢狀子圖（Nested Subgraphs）與並行執行（Parallel Execution）場景。報告首先通過通俗易懂的類比闡釋了 Checkpointer 的核心概念，隨後深入探討了其基於 Google Pregel 模型的底層計算原理。

核心分析重點在於 PostgresSaver 的持久化架構。我們解構了其資料庫表設計（Table Design），特別是複合主鍵（Composite Keys）與命名空間（Namespaces）的策略，這些設計是支持子圖級別狀態隔離與復原的關鍵。

針對用戶提出的特定場景——即包含兩個並行子圖與一個後續子圖的主圖架構——本報告證實了 LangGraph 具備在子圖層級進行精確狀態保存與復原的能力。這得益於其獨特的 checkpoint_ns（檢查點命名空間）機制，該機制能夠在並行執行時為每個分支維護獨立的狀態歷史。報告最後提供了詳細的實施建議與技術路徑，展示了如何利用 PostgreSQL 的結構化特性來實現企業級的 AI 狀態管理。

## ---

**2. 引言：AI Agent 的狀態管理挑戰與 LangGraph 的解法**

在探討 Checkpointer 的技術細節之前，必須先理解其解決的核心問題：**大型語言模型（LLM）的無狀態性（Statelessness）**。

本質上，LLM 是一個函數：輸入文本，輸出文本。它不具備記憶，無法知道上一輪對話發生了什麼。為了構建能夠執行多步任務、具備長期記憶的 AI Agent，開發者必須在模型外部維護一個「狀態」（State）。早期的解決方案（如 LangChain 的 AgentExecutor）採用了較為線性的狀態管理，但在處理複雜邏輯（如循環、分支、並行處理）時顯得力不從心。

LangGraph 應運而生，它將 Agent 的工作流建模為一個圖（Graph）。在這個圖中，節點（Node）是計算單元，邊（Edge）是控制流。而 **Checkpointer** 則是這個系統的「時間機器」與「黑盒子」，負責在圖的每一步驟（Super-step）之間凍結時間，將當前的所有狀態（變量、記憶、上下文）持久化到外部存儲中。這不僅實現了記憶功能，更開啟了「人機協同」（Human-in-the-loop）、「時光倒流」（Time Travel）與「故障恢復」（Fault Tolerance）等高級能力。

## ---

**3. LangGraph Checkpointer 核心機制**

### **3.1 小學生也能懂的原理：電子遊戲的「存檔」大法**

為了讓非技術背景的讀者也能深刻理解 Checkpointer 的運作原理，我們可以使用**「角色扮演遊戲（RPG）的自動存檔」**作為類比。

想像你在玩一款類似《塞爾達傳說》或《超級瑪利歐》的冒險遊戲：

* **AI Agent（主角）：** 你控制的遊戲角色，負責在迷宮中探險、打怪、解謎。
* **LangGraph（遊戲世界）：** 整個迷宮的地圖，包含了許多房間（節點 Nodes）和通道（邊 Edges）。
* **State（背包）：** 主角身上背的背包。裡面裝著金幣、鑰匙、地圖和生命值。這就是「狀態」。

沒有 Checkpointer 的情況：
這就像是玩以前的紅白機遊戲，且沒有電池記憶功能。如果你玩到一半，媽媽突然拔掉了插頭（程式崩潰或伺服器重啟），或者是你走錯路掉進了陷阱（遇到錯誤），當你重新打開遊戲機時，主角會回到遊戲的最開始，背包空空如也。你必須從頭再來，這非常令人沮喪。
有 Checkpointer 的情況：
Checkpointer 就像是現代遊戲中的**「強力自動存檔（Auto-Save）」**功能。

1. **每一步都存檔：** 每當主角走出一個房間（完成一個 Node 的任務），準備進入下一個房間時，系統會自動「暫停」時間。
2. **拍快照（Snapshot）：** 系統會拿相機拍一張照片，記錄下：
   * 主角現在在哪個房間？
   * 背包裡確切有哪些東西（多少金幣、什麼道具）？
   * 現在是幾點幾分？
3. **寫入記憶卡（PostgresSaver）：** 這張照片被永久保存在遊戲機的硬碟裡（PostgreSQL 資料庫）。

為什麼這很強大？
這不僅僅是為了防止當機。這還讓你擁有了**「時光倒流」**的能力。
假設你在並行執行的任務中（比如同時派兩個分身去兩個不同的迷宮），分身 A 在迷宮深處失敗了。

* **傳統模式：** 整個遊戲結束，重頭來過。
* **LangGraph 模式：** 你可以打開「存檔列表」，找到分身 A 進入迷宮第 3 層之前的那個存檔點（Checkpoint），點擊「讀取」。你的分身 A 就會復活在那個時間點，背包裡的裝備也完全恢復。你可以換一種策略繼續玩，而不需要重打前面的關卡。

### **3.2 底層理論：Pregel 計算模型與「超步」（Super-step）**

深入技術層面，LangGraph 的運行機制深受 Google 在 2010 年發表的 **Pregel** 圖計算模型的啟發。這是一種用於處理大規模圖數據的「批量同步並行」（Bulk Synchronous Parallel, BSP）模型。

LangGraph 將 Agent 的執行過程離散化為一系列的 **「超步」（Super-step）**。

#### **3.2.1 超步的生命週期**

每一個超步包含三個原子操作：

1. **讀取（Read）：** 活躍的節點讀取上一輪傳遞給它們的消息或狀態更新。
2. **計算（Compute）：** 節點執行其內部的邏輯（例如調用 LLM、查詢數據庫、執行 Python 代碼）。
3. **寫入（Write）：** 節點將計算結果轉化為狀態更新（State Update）或發送消息給下一個節點。

#### **3.2.2 檢查點的介入時機**

Checkpointer 並不是隨時隨地都在工作，它嚴格地卡在**超步與超步之間**的邊界上。

* 當一個超步中的所有並行節點都完成「計算」並產生「寫入」操作後，系統會進入**同步屏障（Synchronization Barrier）**。
* 在這個屏障處，LangGraph 收集所有的寫入操作（Writes），將它們應用到當前的狀態（State）上，形成一個新的狀態版本。
* **此刻，Checkpointer 啟動：** 它將這個全新的狀態版本序列化，並寫入持久化存儲。只有當寫入成功後，系統才會釋放屏障，允許下一個超步開始。

這種機制保證了**事務的一致性（Transactional Consistency）**。如果在計算過程中發生錯誤，狀態不會被部分更新；系統可以安全地回滾到上一個超步結束時的狀態。

## ---

**4. 架構詳解：PostgresSaver 與資料庫設計**

用戶特別關心如果使用 PostgresSaver，其資料庫表結構是如何設計來支持上述機制的。這是理解子圖狀態復原的關鍵。

LangGraph 的 PostgresSaver 並非簡單地將數據轉儲為一個二進制 Blob，而是採用了高度結構化、標準化的關聯式資料庫設計，以支持高效的查詢、過濾和分片。

### **4.1 資料庫表結構深度剖析 (Table Schema)**

當我們初始化 PostgresSaver（調用 .setup()）時，它會在 PostgreSQL 中創建數個核心表。其中最重要的是 checkpoints 表和 checkpoint_writes 表。

#### **4.1.1 核心表：checkpoints**

這張表存儲了圖在每一個超步結束時的完整狀態快照。

| 欄位名稱 (Column) | 資料類型 (Type) | 說明與關鍵作用 |
| :---- | :---- | :---- |
| **thread_id** | TEXT | **會話標識符。** 代表一個完整的對話或任務執行緒。在用戶的場景中，主圖和所有的子圖都會共享這同一個 thread_id，將它們聯繫在一起。 |
| **checkpoint_ns** | TEXT | **命名空間（Namespace）。** 這是支持子圖復原的**核心欄位**。它標識了當前狀態屬於圖中的哪一個層級。主圖的命名空間通常為空字串 ""，而子圖的命名空間則類似於路徑，如 agent:subgraph_node_name。 |
| **checkpoint_id** | TEXT | **版本標識符。** 通常是一個單調遞增的 UUID 或時間戳字串，標識了這是在該執行緒、該命名空間下的第幾個步驟。 |
| **parent_checkpoint_id** | TEXT | **前驅指針。** 指向上一個版本的 checkpoint_id，形成一個鏈表結構，允許系統追溯歷史路徑。 |
| **type** | TEXT | 序列化類型（如 json, msgpack）。 |
| **checkpoint** | JSONB | **狀態負載。** 存儲實際的 Agent 狀態數據（例如對話歷史 messages、變量值）。使用 JSONB 允許資料庫對狀態內容進行索引和查詢。 |
| **metadata** | JSONB | 元數據。記錄了觸發此檢查點的來源（如 source: loop 或 source: input）、步驟編號、寫入操作的發起者等。 |

複合主鍵（Composite Primary Key）：
表的主鍵由 (thread_id, checkpoint_ns, checkpoint_id) 共同組成。

* 這意味著，在同一個 thread_id 下，資料庫可以同時存儲多個不同 checkpoint_ns 的狀態。
* **結論：** 這直接支持了並行子圖的狀態保存。即使兩個子圖同時運行，它們擁有不同的 checkpoint_ns，因此它們的狀態記錄在資料庫中是獨立的行（Rows），互不衝突。

#### **4.1.2 寫入表：checkpoint_writes**

這張表存儲了在超步期間產生的「待處理寫入」（Pending Writes）。這對應於 Pregel 模型中的消息傳遞。

| 欄位名稱 | 資料類型 | 說明 |
| :---- | :---- | :---- |
| thread_id | TEXT | 關聯的執行緒 ID。 |
| checkpoint_ns | TEXT | 寫入操作發生的命名空間。 |
| checkpoint_id | TEXT | 關聯的檢查點 ID。 |
| task_id | TEXT | 產生此寫入的特定任務 ID。 |
| channel | TEXT | 目標通道名稱（例如 messages）。 |
| value | BYTEA | 序列化後的寫入值。 |

這張表的存在允許 LangGraph 處理非確定性的執行路徑。如果一個流程被中斷，系統不僅知道最後的「狀態」（在 checkpoints 表），還知道當時正在傳遞但尚未處理的「消息」（在 checkpoint_writes 表）。在恢復時，系統可以重放這些消息。

#### **4.1.3 大對象表：checkpoint_blobs**

為了優化性能，LangGraph 不會將所有數據都塞進 checkpoints 表。對於較大且不常變動的數據（例如很長的文檔、圖片數據），系統會將其存儲在 checkpoint_blobs 表中，並在主表中僅存儲引用（Hash）。這減少了主表的 I/O 壓力，實現了類似 Git 的去重存儲機制。

## ---

**5. 實戰場景分析：並行子圖與狀態復原**

現在，我們將這些理論應用到用戶具體的實戰場景中。

### **5.1 場景定義與流程圖**

用戶描述的架構如下：

1. **Main Graph（主圖）：** 啟動執行。
2. **Parallel Branch（並行分支）：** 兩個節點同時運行。
   * **Node A** 調用 **Subgraph 1**。
   * **Node B** 調用 **Subgraph 2**。
3. **Join（匯合）：** 等待 Subgraph 1 和 2 全部完成。
4. **Sequential Node（順序節點）：** Node C 調用 **Subgraph 3**。

我們可以用以下的圖表化描述來展示這個流程（對應於用戶要求的「圖片或圖表形式」）：

程式碼片段

graph TD
    Start((開始)) --> Main_Start

    subgraph Parallel_Execution
        direction LR
        Main_Start --> NodeA
        Main_Start --> NodeB

        subgraph Subgraph_1 [子圖 1 執行流]
            S1_Start((S1 開始)) --> S1_Step1
            S1_Step1 --> S1_Step2
            S1_Step2 --> S1_End((S1 結束))
        end

        subgraph Subgraph_2 [子圖 2 執行流]
            S2_Start((S2 開始)) --> S2_Step1
            S2_Step1 --> S2_End((S2 結束))
        end

        NodeA -.-> S1_Start
        NodeB -.-> S2_Start
    end

    S1_End --> Join_Node{匯合等待}
    S2_End --> Join_Node

    Join_Node --> NodeC

    subgraph Subgraph_3 [子圖 3 執行流]
        S3_Start --> S3_Step1
        S3_Step1 --> S3_End
    end

    NodeC -.-> S3_Start
    S3_End --> End((結束))

### **5.2 並行執行中的狀態隔離 (State Isolation)**

在這個場景中，關鍵問題是：**當 Subgraph 1 和 Subgraph 2 同時運行時，它們的狀態會打架嗎？**

答案是**不會**。這正是 checkpoint_ns 發揮作用的地方。

假設我們設定 thread_id = "user-session-001"。
當並行階段開始時，PostgresSaver 會記錄以下並行的狀態流：

1. **主圖狀態流：**
   * thread_id: user-session-001
   * checkpoint_ns: "" (空)
   * **狀態：** 處於「等待 Node A 和 Node B 返回」的掛起狀態。
2. **子圖 1 狀態流（由 Node A 觸發）：**
   * thread_id: user-session-001
   * checkpoint_ns: NodeA:Subgraph1 (LangGraph 會自動根據節點路徑生成此命名空間)
   * **狀態：** 隨著 S1_Step1, S1_Step2 的執行，不斷寫入新的 Checkpoint 行（Rows）。
3. **子圖 2 狀態流（由 Node B 觸發）：**
   * thread_id: user-session-001
   * checkpoint_ns: NodeB:Subgraph2
   * **狀態：** 隨著 S2_Step1 的執行，寫入屬於它自己的 Checkpoint 行。

資料庫視角：
在資料庫中，這些記錄是完全隔離的。Postgres 的複合主鍵 (thread_id, checkpoint_ns, checkpoint_id) 確保了即使兩個子圖在同一毫秒寫入狀態，它們也擁有不同的 checkpoint_ns，因此互不干擾。

### **5.3 幫我研究 checkpointer 可不可以復原或保存去到 subgraph level 的狀態？**

**結論：可以。**

LangGraph 的設計原則是「分形」（Fractal）的。子圖在執行時，對於 Checkpointer 來說，就如同一個獨立運行的圖，只是它剛好共享了父圖的 thread_id 並多了一個命名空間前綴。

如何做到？
這依賴於 LangGraph 運行時（Runtime）的上下文傳遞機制。

1. **隱式傳遞：** 當主圖編譯時啟用了 Checkpointer (checkpointer=postgres_saver)，這個 Checkpointer 實例會自動注入到所有的子圖中（前提是子圖也是通過 StateGraph 編譯並作為節點加入的）。
2. **命名空間堆疊：** 當執行流進入子圖時，運行時會將當前的命名空間（例如 ""）加上當前節點名（例如 NodeA），生成新的命名空間 NodeA。如果子圖裡面還有子圖，命名空間會繼續堆疊變為 NodeA:InnerNode:DeepSubgraph。
3. **獨立讀寫：** 子圖內部的 get_state 和 update_state 操作，會自動限定在當前的命名空間下。

## ---

**6. 技術實現：怎樣可以做到精確復原？**

用戶問到具體的實現方法，特別是如何復原。這在開發調試（Debugging）或人機交互（Human-in-the-loop）場景中極為重要。

### **6.1 保存狀態的配置**

要實現這一點，代碼層面需要確保 PostgresSaver 被正確初始化並傳遞給編譯步驟。

Python

# 1. 設置 PostgresSaver
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg_pool import ConnectionPool

DB_URI = "postgresql://user:pass@localhost:5432/db"
pool = ConnectionPool(conninfo=DB_URI, max_size=20, kw={"autocommit": True, "row_factory": dict_row})

# 必須運行一次 setup() 來創建表結構
with pool.connection() as conn:
    checkpointer = PostgresSaver(conn)
    checkpointer.setup()

# 2. 定義圖結構 (簡化示意)
# 定義 Subgraph 1
sub_builder1 = StateGraph(SubState1)
sub_builder1.add_node("s1_step1", func_a)
subgraph1 = sub_builder1.compile() # 注意：這裡通常不需要顯式傳入 checkpointer，它會從父圖繼承

# 定義主圖
main_builder = StateGraph(MainState)
main_builder.add_node("NodeA", subgraph1) # 將編譯好的子圖作為節點
main_builder.add_node("NodeB", subgraph2)
main_builder.add_edge(START, "NodeA")
main_builder.add_edge(START, "NodeB")

# 3. 編譯主圖時傳入 checkpointer
graph = main_builder.compile(checkpointer=checkpointer)

### **6.2 復原（Time Travel）的具體操作**

假設 **Subgraph 1** 在運行到一半時報錯了，或者你想手動修改 **Subgraph 1** 中間某一步的變量。你需要知道該子圖的 checkpoint_ns。

步驟一：查看歷史記錄
你可以查詢特定 thread_id 的所有歷史記錄，這會顯示所有命名空間的檢查點。

Python

config = {"configurable": {"thread_id": "session-001"}}
# 列出所有檢查點
for state in graph.get_state_history(config):
    print(state.config['configurable']['checkpoint_ns'], state.config['configurable']['checkpoint_id'])

# 輸出示例：
# ""  uuid-main-end
# "NodeA:Subgraph1" uuid-sub1-step2
# "NodeB:Subgraph2" uuid-sub2-step1
# "NodeA:Subgraph1" uuid-sub1-step1
# ""  uuid-main-start

步驟二：定位並加載特定子圖狀態
假設你想恢復到 Subgraph 1 的 Step 1 結束時的狀態。你需要構建一個包含特定 checkpoint_ns 和 checkpoint_id 的配置對象。

Python

# 構建復原配置
restore_config = {
    "configurable": {
        "thread_id": "session-001",
        "checkpoint_ns": "NodeA:Subgraph1",  # 關鍵：指定子圖的命名空間
        "checkpoint_id": "uuid-sub1-step1"   # 關鍵：指定該子圖的特定版本 ID
    }
}

# 獲取該時刻子圖的內部狀態
snapshot = graph.get_state(restore_config)
print("子圖當時的變量:", snapshot.values)

步驟三：從子圖內部恢復執行
如果你使用這個 restore_config 來調用 graph.invoke()，LangGraph 引擎會識別出你指向的是一個巢狀的子圖狀態。

Python

# 修改狀態（可選）
graph.update_state(restore_config, {"internal_var": "new_value"})

# 恢復執行
# 注意：這裡的 Command 或輸入 None 會觸發從該檢查點繼續
graph.invoke(None, config=restore_config)

原理說明：
當你傳入帶有 checkpoint_ns 的配置時，PostgresSaver 會在資料庫中執行類似以下的 SQL 查詢：

SQL

SELECT * FROM checkpoints
WHERE thread_id = 'session-001'
  AND checkpoint_ns = 'NodeA:Subgraph1'
  AND checkpoint_id = 'uuid-sub1-step1';

這就精確地抓取到了子圖在那一刻的「背包」，而完全忽略了主圖或並行兄弟節點（Node B）的狀態。引擎隨後加載這個背包，並將執行指針（Program Counter）設置回該子圖的對應節點，從而實現精確復原。

## ---

**7. 深入解析：為什麼可以做到？(The "Why")**

結合上述原理，我們可以總結為什麼 LangGraph 能在並行執行下做到這一點：

1. 狀態的命名空間隔離（Namespace Isolation）：
   這是最核心的原因。資料庫不是把所有東西混在一起，而是通過 checkpoint_ns 這個維度，將並行執行的不同分支在邏輯上切分成了獨立的存儲空間。對於資料庫而言，存儲「主圖狀態」和存儲「子圖 A 狀態」沒有區別，都是存儲一行數據，只是標籤（Tag）不同。
2. 事務性寫入（Transactional Writes）：
   Postgres 的 ACID 特性保證了並行寫入的安全性。當 Node A 和 Node B 同時完成一步並嘗試寫入狀態時，Postgres 的行級鎖（Row-level locking）和 MVCC 機制確保了這些並發寫入不會互相覆蓋或產生髒數據。
3. 遞歸的圖執行引擎（Recursive Graph Runtime）：
   LangGraph 的引擎本身就是遞歸設計的。當它執行一個類型為 CompiledGraph 的節點時，它會 spawning（衍生）一個新的運行時實例。這個新實例繼承了父級的 Checkpointer，但在寫入時會自動附加上自己的命名空間前綴。這種架構設計從代碼層面保證了狀態的層級化管理。
4. 不可變的快照鏈（Immutable Snapshot Chain）：
   每個 Checkpoint 一旦寫入，原則上是不可變的（Immutable）。新的狀態只會產生新的 Checkpoint ID。這意味著「歷史」永遠被完整保留。無論你的並行邏輯多麼複雜，只要你保留了那個 ID，你就能隨時回到那個時刻。

## **8. 結論**

通過對 LangGraph Checkpointer 機制的深入調研，特別是針對 PostgresSaver 的表結構分析，我們可以確認：**LangGraph 具備強大的能力來處理並行子圖的狀態保存與復原。**

其底層原理依賴於：

1. **Pregel 模型** 的超步同步機制，規範了狀態更新的時機。
2. **PostgreSQL 資料庫** 的複合主鍵設計（thread_id + checkpoint_ns），在物理存儲層面實現了並行狀態的隔離。
3. **分層命名空間** 機制，確保了無論圖的嵌套層級多深，每一個執行單元都有其唯一的狀態地址。

對於開發者而言，這意味著可以放心地設計複雜的、並行的 AI Agent 工作流，並確信系統能夠在任何粒度（從主流程到深層子圖）上進行精確的狀態追蹤與故障恢復。這為構建企業級、高可靠性的 AI 應用提供了堅實的基礎設施支持。

**參考文獻標識：** 1

#### **引用的著作**

1. What is a Checkpointer in LangGraph — and Why It's a Game-Changer for AI Agents | by Vignesh | Dec, 2025 | Medium, 檢索日期：1月 6, 2026， [https://medium.com/@vignesh_2710/what-is-a-checkpointer-in-langgraph-and-why-its-a-game-changer-for-ai-agents-430a0afa52b8](https://medium.com/@vignesh_2710/what-is-a-checkpointer-in-langgraph-and-why-its-a-game-changer-for-ai-agents-430a0afa52b8)
2. Mastering LangGraph Checkpointing: Best Practices for 2025 - Sparkco, 檢索日期：1月 6, 2026， [https://sparkco.ai/blog/mastering-langgraph-checkpointing-best-practices-for-2025](https://sparkco.ai/blog/mastering-langgraph-checkpointing-best-practices-for-2025)
3. Postgres Schema for LangGraph Checkpointer · Issue #465 · langchain-ai/docs - GitHub, 檢索日期：1月 6, 2026， [https://github.com/langchain-ai/docs/issues/465](https://github.com/langchain-ai/docs/issues/465)
4. PostgresSaver | langchain.js, 檢索日期：1月 6, 2026， [https://reference.langchain.com/javascript/classes/_langchain_langgraph-checkpoint-postgres.index.PostgresSaver.html](https://reference.langchain.com/javascript/classes/_langchain_langgraph-checkpoint-postgres.index.PostgresSaver.html)
5. Persistence - Docs by LangChain, 檢索日期：1月 6, 2026， [https://docs.langchain.com/oss/python/langgraph/persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
6. Built with LangGraph! #17: Checkpoints | by Okan Yenigün | Towards Dev - Medium, 檢索日期：1月 6, 2026， [https://medium.com/@okanyenigun/built-with-langgraph-17-checkpoints-2d1d54e1464b](https://medium.com/@okanyenigun/built-with-langgraph-17-checkpoints-2d1d54e1464b)
7. MULTIPLE_SUBGRAPHS - Docs by LangChain, 檢索日期：1月 6, 2026， [https://docs.langchain.com/oss/python/langgraph/errors/MULTIPLE_SUBGRAPHS](https://docs.langchain.com/oss/python/langgraph/errors/MULTIPLE_SUBGRAPHS)
8. `tool_use` ids were found without `tool_result` blocks immediately after · Issue #5109 · langchain-ai/langgraph - GitHub, 檢索日期：1月 6, 2026， [https://github.com/langchain-ai/langgraph/issues/5109](https://github.com/langchain-ai/langgraph/issues/5109)
9. langgraph-checkpoint-postgres - PyPI, 檢索日期：1月 6, 2026， [https://pypi.org/project/langgraph-checkpoint-postgres/](https://pypi.org/project/langgraph-checkpoint-postgres/)
10. Memory overview - Docs by LangChain, 檢索日期：1月 6, 2026， [https://docs.langchain.com/oss/python/langgraph/memory](https://docs.langchain.com/oss/python/langgraph/memory)
11. Developing a scalable Agentic service based on LangGraph | by Martin Hodges - Medium, 檢索日期：1月 6, 2026， [https://medium.com/@martin.hodges/developing-a-scalable-agentic-service-based-on-langgraph-02b3689f287c](https://medium.com/@martin.hodges/developing-a-scalable-agentic-service-based-on-langgraph-02b3689f287c)
12. Checkpointing | LangChain Reference, 檢索日期：1月 6, 2026， [https://reference.langchain.com/python/langgraph/checkpoints/](https://reference.langchain.com/python/langgraph/checkpoints/)
