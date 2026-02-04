# **企業級 LangGraph 架構白皮書：基於 TypedDict 的狀態規約與高韌性錯誤處理機制深入解析**

## **1. 執行摘要：從自動化腳本到彈性代理系統的演進**

在當前的企業級軟體架構中，人工智慧代理（AI Agents）正迅速從實驗性的腳本轉變為核心業務流程的驅動者。這種轉變帶來了前所未有的挑戰：系統不再是線性的、確定的，而是循環的、概率性的且高度依賴上下文的。LangGraph 作為一種低層次的編排框架，通過將代理工作流建模為圖（Graph），提供了管理這種複雜性的必要原語：節點（Nodes）、邊（Edges）、狀態（State）與檢查點（Checkpointers）。然而，企業級應用的容錯要求遠高於原型展示，必須能夠處理網路抖動、模型幻覺、狀態污染以及並發衝突等多重故障模式。

本報告旨在建立一套基於 LangGraph 的企業級開發標準，特別聚焦於兩大核心支柱：**基於 TypedDict 的強型別狀態管理**與**多層次的錯誤處理架構**。不同於傳統的 Pydantic 模型或非結構化字典，TypedDict 在運行時提供了極致的序列化效率，同時在開發時保留了靜態分析的能力，這使其成為構建高吞吐量代理系統的首選狀態載體。

報告將深入探討分佈式圖計算中的錯誤生命週期，從節點級別的重試策略（Retry Policies）到圖級別的動態路由（Dynamic Routing）。我們將分析如何利用 Command 原語實現優雅降級，以及如何在多代理（Multi-Agent）監工模式（Supervisor Pattern）中有效地隔離與傳播子圖（Subgraph）錯誤。此外，針對金融與數據密集型場景，本報告將詳細闡述如何安全地持久化高精度數據（如 Decimal）與大型對象（如 DataFrame），並針對近期揭露的序列化漏洞（如 CVE-2025-64439）提供具體的防禦策略 1。

這是一份為系統架構師與資深 AI 工程師撰寫的深度技術指南，旨在定義構建可擴展、可審計且具備自我修復能力的 LangGraph 應用的最佳實踐。

## ---

**2. 狀態管理的哲學：基於 TypedDict 的標準化規約**

在 LangGraph 的架構中，狀態（State）是圖的靈魂。它是所有節點共享的上下文，也是代理記憶的唯一載體。在企業級應用中，狀態設計的優劣直接決定了系統的可維護性與擴展性。雖然 LangGraph 支援多種狀態定義方式，但 TypedDict 因其輕量化與原生 Python 字典的兼容性，成為了構建高性能圖結構的標準。

### **2.1 TypedDict 與 Pydantic 的架構權衡**

在選擇狀態模式時，開發者通常在 TypedDict 與 Pydantic BaseModel 之間權衡。企業級最佳實踐強烈建議在**圖的內部狀態（Internal State）**使用 TypedDict，而在**邊界驗證（IO Validation）**使用 Pydantic。

TypedDict 的核心優勢在於其「結構化子類型（Structural Subtyping）」特性與零運行時開銷。當圖在數千個節點間快速流轉時，Pydantic 的序列化與驗證開銷會顯著累積。此外，LangGraph 的底層檢查點機制（Checkpointers）本質上是將狀態存儲為 JSON 或 Msgpack，TypedDict 與這種鍵值對結構的映射最為自然，避免了不必要的物件實例化開銷 2。

**表 1：TypedDict 與 Pydantic 在 LangGraph 中的適用性對比**

| 特性維度 | TypedDict (推薦用於內部狀態) | Pydantic BaseModel (推薦用於邊界驗證) |
| :---- | :---- | :---- |
| **運行時開銷** | 極低（原生字典） | 中高（需驗證與實例化） |
| **序列化兼容性** | 100% JSON 兼容 | 需調用 .model_dump() |
| **Reducer 整合** | 原生支援 Annotated | 需額外配置 |
| **靈活性** | 支援結構化子類型（寬鬆匹配） | 嚴格的名義類型（Nominal Typing） |
| **靜態分析** | 支援 Mypy/Pyright | 支援完善 |
| **典型用途** | 節點間傳遞的共享上下文 | 用戶輸入驗證、API 響應格式化 |

### **2.2 三層架構狀態設計模式**

為了防止下游節點出現「神秘錯誤」並確保數據流的清晰，企業級項目應採用**三層狀態架構**。這種模式將輸入、內部邏輯與輸出嚴格分離，確保敏感的中間變量（如原始檢索文檔、思考鏈日誌）不會洩漏到最終響應中，同時保證輸入數據的完整性。

1. **InputState（輸入規約）**：定義圖啟動時必須提供的最小數據集。
2. **OverallState（全域規約）**：包含所有中間運算結果、私有鍵值與累加器。這是圖編譯時使用的主要 Schema。
3. **OutputState（輸出規約）**：定義最終返回給調用者的數據視圖，通常是 OverallState 的子集。

Python

from typing import TypedDict, Annotated, List, Optional, Union
import operator
from langgraph.graph.message import add_messages

# 定義基礎消息類型
class BaseGraphState(TypedDict):
    thread_id: str
    user_id: str

# 輸入狀態：嚴格限制調用者必須提供的參數
class InputState(BaseGraphState):
    query: str
    max_retries: Optional[int]

# 全域狀態：包含運行時的所有上下文與 Reducer 邏輯
class OverallState(InputState):
    # 使用 add_messages Reducer 處理對話歷史的追加與更新
    messages: Annotated[List[dict], add_messages]

    # 使用 operator.add 處理分佈式節點的日誌聚合
    error_logs: Annotated[List[dict], operator.add]

    # 私有上下文，不應暴露給外部
    _retrieved_docs: List[str]
    _reasoning_trace: List[str]
    retry_count: Annotated[int, operator.add]

# 輸出狀態：僅暴露最終結果
class OutputState(TypedDict):
    messages: List[dict]
    error_logs: List[dict]

在這種設計中，Annotated 與 Reducer 函數（如 operator.add）的結合至關重要。在並行執行（如 Map-Reduce 模式）中，多個節點可能同時嘗試寫入 error_logs。如果沒有 Reducer，後完成的節點將覆蓋先完成節點的寫入，導致錯誤日誌丟失。使用 operator.add 確保了所有分支的錯誤都能被安全地聚合到列表中，這對於事後審計與調試至關重要 2。

### **2.3 處理大型數據集與狀態膨脹**

在金融分析或數據科學場景中，代理經常需要處理大型數據結構，例如 Pandas DataFrame 或高維向量。初學者常見的錯誤是將這些大型對象直接存儲在 TypedDict 狀態中。這會導致嚴重的性能問題：每次狀態更新都會觸發檢查點的序列化與寫入操作，導致資料庫 I/O 激增，甚至觸發記憶體溢出（OOM）。

**最佳實踐：引用與存儲分離（Store-Reference Pattern）**

狀態對象應僅作為**控制平面（Control Plane）**，存儲輕量級的元數據、ID 與控制標誌。重型的**數據平面（Data Plane）**應卸載到 LangGraph 的 BaseStore 或外部對象存儲（如 S3、Redis Blob）中。

**實施策略：**

1. **卸載（Offloading）**：當節點生成 DataFrame 時，將其序列化並存入 BaseStore，獲取一個唯一的 object_id。
2. **引用（Referencing）**：僅將 object_id 寫入圖的 TypedDict 狀態。
3. **懶加載（Lazy Loading）**：下游節點僅在需要進行計算時，通過 object_id 從 Store 中檢索數據 5。

這不僅減少了檢查點的大小，還使得「時間旅行（Time Travel）」調試變得更加輕量，因為歷史狀態快照僅包含 ID 引用而非數據副本。

## ---

**3. 持久化層的安全性與數據完整性**

企業級應用的韌性依賴於可靠的持久化機制。LangGraph 的檢查點系統（Checkpointer）負責將圖的執行狀態保存到資料庫中，以便在故障後恢復或進行人工干預。然而，默認的序列化機制在處理特殊數據類型與安全性方面存在陷阱。

### **3.1 序列化漏洞防禦：CVE-2025-64439 解析**

近期安全公告（CVE-2025-64439）指出，LangGraph 的 JsonPlusSerializer 在 3.0 版本之前存在遠程代碼執行（RCE）漏洞。當序列化器在處理無法編碼的內容回退到 "json" 模式時，攻擊者若能控制存入檢查點的數據，便可能構造惡意負載在反序列化時執行任意 Python 代碼 1。

**企業級防禦強制規約：**

1. **版本鎖定**：所有生產環境必須強制使用 langgraph-checkpoint >= 3.0，該版本已修補此漏洞，禁止了不安全的自定義對象反序列化。
2. **禁用 JSON 回退**：在配置序列化器時，應明確禁止不可信數據的 JSON 構造器模式。
3. **加密存儲**：對於必須使用 pickle 處理的複雜 Python 對象（如自定義類實例），必須配合 EncryptedSerializer 使用。這確保了即使攻擊者能夠訪問資料庫，也無法篡改 Pickle 數據流來注入惡意代碼 7。

Python

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.postgres import PostgresSaver

# 安全配置：明確禁止不安全的加載行為（視版本 API 而定，主要依賴升級）
# 對於敏感數據，推薦疊加加密層
# from langgraph.checkpoint.serde.encrypted import EncryptedSerializer

serializer = JsonPlusSerializer(pickle_fallback=False) # 在企業環境中，盡量避免 fallback 到 pickle
checkpointer = PostgresSaver.from_conn_string(DB_URI, serde=serializer)

### **3.2 高精度金融數據的序列化挑戰**

在金融應用中，精度至關重要。Python 的 Decimal 類型用於處理貨幣計算，但標準的 JSON 序列化會將 Decimal 轉換為浮點數（Float），導致精度丟失（例如 Decimal("100.00") 變成 100.0，甚至在運算後出現 99.999999）。LangGraph 的默認序列化器在某些情況下可能無法完美保留 Decimal 的字面值 9。

**解決方案：自定義金融序列化協議**

企業應實作自定義的 SerializerProtocol，將 Decimal 強制轉換為字串存儲，並在讀取時還原，確保「存入即所得」。

Python

import json
from decimal import Decimal
from langgraph.checkpoint.serde.base import SerializerProtocol
from typing import Any

class FinancialSafeSerializer(SerializerProtocol):
    def dumps(self, obj: Any) -> bytes:
        # 使用自定義 encoder 將 Decimal 轉為字串
        return json.dumps(obj, default=self._decimal_encoder).encode("utf-8")

    def loads(self, data: bytes) -> Any:
        # 使用 parse_float 鉤子將浮點數字串還原為 Decimal
        return json.loads(data.decode("utf-8"), parse_float=Decimal)

    @staticmethod
    def _decimal_encoder(obj):
        if isinstance(obj, Decimal):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

這種做法雖然增加了少量的序列化開銷，但在涉及賬務核對的系統中是絕對必要的，它消除了浮點數運算的不確定性風險 11。

## ---

**4. 錯誤處理矩陣：從重試到優雅降級**

在分佈式圖計算中，錯誤是不可避免的常態。企業級錯誤處理策略必須區分**瞬態錯誤（Transient Errors）與持久性錯誤（Persistent Errors）**，並針對不同層級採取相應的緩解措施。

### **4.1 節點級別的重試策略（Retry Policies）**

對於網路超時、限流（Rate Limiting）或服務暫時不可用（503 Service Unavailable）等瞬態錯誤，最有效的處理方式是就地重試。LangGraph 提供了聲明式的 RetryPolicy，這比在每個節點內部手寫 try...except 循環更為優雅且統一。

**最佳實踐配置：**

不要對所有錯誤進行重試。盲目的重試會導致「驚群效應（Thundering Herd）」，加劇下游服務的負載。應配置白名單異常，並啟用指數退避（Exponential Backoff）與抖動（Jitter）。

Python

from langgraph.pregel import RetryPolicy

# 定義標準化的企業重試策略
API_RETRY_POLICY = RetryPolicy(
    max_attempts=3,
    initial_interval=0.5,   # 初始等待 500ms
    backoff_factor=2.0,     # 指數增長：0.5s -> 1.0s -> 2.0s
    jitter=True,            # 加入隨機抖動，防止並發請求同步重試
    retry_on=tuple() # 僅針對特定異常
)

# 在圖構建時應用
graph.add_node("call_llm_model", model_node, retry=API_RETRY_POLICY)

**關鍵洞察**：嚴禁將 ValueError 或 KeyError 等邏輯錯誤加入重試列表。這些錯誤通常是確定性的（Deterministic），重試只會浪費計算資源並增加延遲 12。

### **4.2 基於 Command 的動態路由與降級**

當重試次數耗盡，或者遇到無法恢復的語義錯誤時，系統不應直接崩潰（Crash），而應進入**降級模式（Graceful Degradation）**。LangGraph 的 Command 原語允許節點在運行時動態決定下一步的跳轉目標，這為實現複雜的錯誤恢復邏輯提供了強大支持。

**模式：本地捕獲與動態跳轉**

傳統的 try...except 只能處理代碼塊內的異常，而結合 Command 對象，我們可以將異常轉化為圖的控制流。

Python

from langgraph.types import Command
from langgraph.graph import END

def risky_tool_node(state: OverallState) -> Command:
    try:
        # 執行高風險操作
        result = external_api.call()
        return Command(
            update={"result": result, "error_logs":},
            goto="next_process_node"
        )
    except Exception as e:
        # 捕獲異常，不拋出，而是更新錯誤日誌並跳轉到降級處理節點
        error_info = {"node": "risky_tool", "error": str(e), "timestamp": "..."}
        return Command(
            update={"error_logs": [error_info]}, # 利用 reducer 記錄錯誤
            goto="fallback_handler_node" # 動態路由到備用邏輯
        )

這種模式的優勢在於它將錯誤處理邏輯局部化，不需要在圖的全局邊（Edge）定義中充斥著複雜的條件判斷（Conditional Edges）。Command(goto=...) 優先級高於靜態定義的邊，提供了運行時的靈活介入能力 14。

### **4.3 處理圖遞歸錯誤（GraphRecursionError）**

在 Agent 自主循環（如「思考-行動-觀察」循環）中，無限循環是常見風險。LangGraph 默認設有 recursion_limit（通常為 25）以防止堆疊溢出。當達到此限制時，會拋出 GraphRecursionError，導致整個圖崩潰。

**企業級處理策略：**

1. **狀態計數器（TTL）**：在狀態中維護一個顯式的 loop_count 或 step_count。
2. **主動中斷**：在條件邊中檢查此計數器，一旦接近限制，主動路由到人工干預節點或強制結束節點，而不是等待系統拋出異常。

Python

def router(state):
    # 主動檢測，避免 GraphRecursionError 崩潰
    if state["loop_count"] > 20:
        return Command(
            update={"error_logs": ["Max recursion depth reached"]},
            goto="human_help_node"
        )
    return "agent_node"

這不僅防止了崩潰，還為用戶提供了有意義的反饋（例如：「任務過於複雜，已轉交人工處理」），而非冰冷的系統錯誤堆疊 16。

## ---

**5. 多代理監工模式（Supervisor Pattern）與子圖韌性**

在複雜的企業場景中，單一圖無法承載所有邏輯，通常採用**監工模式（Supervisor Pattern）**，由一個頂層路由代理調度多個專業化的**子圖（Subgraphs）**。這種架構帶來了新的錯誤傳播挑戰。

### **5.1 子圖錯誤的隔離與傳播**

LangGraph 中的子圖對於父圖而言是一個黑盒節點。如果子圖內部發生未捕獲的異常（如 GraphRecursionError），該異常會直接冒泡到父圖，導致父圖崩潰。

**安全調用包裝器（Safe Subgraph Wrapper）：**

為了隔離子圖故障，不應直接將子圖編譯後的 Runnable 作為節點加入父圖，而應將其包裝在一個負責錯誤邊界處理的函數中。

Python

def safe_subgraph_invocation(state: OverallState):
    # 準備子圖輸入
    sub_input = transform_to_subgraph_state(state)
    try:
        # 調用子圖
        result = compiled_subgraph.invoke(sub_input)
        return {"subgraph_result": result}
    except Exception as e:
        # 攔截子圖崩潰，轉化為父圖的錯誤狀態
        return {
            "error_logs":,
            "subgraph_result": None,
            "system_status": "degraded"
        }

這種模式確保了即使某個子系統（如「研究代理」）完全崩潰，主流程（如「客戶響應」）仍能繼續運行，可能僅是回應「無法獲取最新研究數據，但根據現有知識...」 16。

### **5.2 父子圖狀態同步與 Command.PARENT**

在某些場景下，子圖需要直接更新父圖的狀態（例如，子圖是一個工具調用鏈，需要將中間產生的重要標記寫回全局上下文）。LangGraph 提供了 Command(graph=Command.PARENT) 機制來實現這一點。

**使用規範：**

1. **共享 Schema 鍵值**：父圖與子圖必須在 TypedDict 中定義相同的鍵（Key）。
2. **Reducer 一致性**：如果該鍵在父圖中定義了 Reducer（如 add_messages），子圖的更新也會遵循該 Reducer 邏輯。

Python

# 子圖節點代碼
def child_node(state):
    return Command(
        update={"global_alert": "Detected Critical Issue"},
        graph=Command.PARENT # 將此更新推送到父圖狀態
    )

然而，這也引入了耦合。如果父圖沒有定義 global_alert 鍵，運行時將報錯。因此，必須建立嚴格的文檔規約，明確子圖對父圖狀態的依賴契約 19。

## ---

**6. 人機協同（HITL）：中斷、驗證與恢復**

在金融交易、醫療診斷等高風險領域，全自動代理是不可接受的。LangGraph 的 interrupt 機制允許系統在關鍵決策點暫停，等待人類確認。

### **6.1 中斷機制的冪等性（Idempotency）挑戰**

當圖執行到 interrupt() 時，它會暫停並保存檢查點。當用戶提供輸入並恢復執行時，**LangGraph 會從包含 interrupt 調用的那個節點的起始處重新執行**，而不是從 interrupt 語句的下一行繼續 22。

**這意味著：中斷節點必須是冪等的。**

**錯誤範例（非冪等）：**

Python

def payment_node(state):
    api.charge_credit_card() # 副作用：扣款
    approval = interrupt("Approve receipt?") # 暫停
    email.send_receipt()

如果用戶批准並恢復，payment_node 會重新運行，導致**二次扣款**。

**正確範例（分離副作用）：**

將副作用邏輯與中斷邏輯拆分為不同節點，或在中斷節點內進行狀態檢查。

Python

def payment_node(state):
    # 檢查是否已扣款（基於狀態中的標誌）
    if not state.get("is_charged"):
        api.charge_credit_card()
        return {"is_charged": True} # 更新狀態

    approval = interrupt("Approve receipt?")
    #...

### **6.2 用戶輸入的循環驗證**

當用戶通過 Command(resume=value) 提供輸入時，該輸入可能是無效的。系統不能假設人類輸入總是正確的。需要構建一個「驗證循環」。

Python

def human_input_node(state):
    prompt_msg = "Please enter age:"
    error_msg = None

    while True:
        # 結合前一次的錯誤信息進行中斷
        user_val = interrupt({"msg": prompt_msg, "error": error_msg})

        # 驗證邏輯
        if validate_age(user_val):
            return {"age": user_val} # 有效，退出節點更新狀態

        # 無效，更新錯誤信息，進入下一次 while 循環 -> 再次觸發 interrupt
        error_msg = "Invalid age. Try again."

這種模式利用了節點重新執行的特性，在節點內部形成一個閉環，直到獲得合法輸入才允許圖繼續推進，確保了髒數據不會污染全局狀態 22。

## ---

**7. 結論與建議**

構建企業級 LangGraph 應用不僅僅是編寫 Prompt 與連接 LLM，更是一項系統工程。它要求開發者從「快樂路徑（Happy Path）」的思維轉向防禦性編程。

**核心總結：**

1. **狀態即契約**：使用 TypedDict 嚴格定義 Input/Overall/Output 三層狀態，利用 Annotated 與 Reducer 處理並發衝突。
2. **數據分層**：將大型數據（DataFrame）卸載到外部存儲，狀態中僅保留輕量級引用。
3. **安全持久化**：升級檢查點庫以修復 RCE 漏洞，並針對金融數據實作自定義序列化協議以保留精度。
4. **防禦性編排**：使用 RetryPolicy 處理瞬態錯誤，使用 Command 處理邏輯降級，並通過包裝器隔離子圖故障。
5. **冪等設計**：在 HITL 流程中，時刻警惕節點重入導致的副作用重複執行問題。

遵循這些標準，企業可以構建出既具備 AI 的靈活性，又擁有傳統軟體工程健壯性的智能代理系統。

## ---

**8. 附錄：參考表格**

### **表 2：LangGraph 錯誤類型與處理策略對照表**

| 錯誤類別 | 典型場景 | 推薦處理策略 | LangGraph 機制 |
| :---- | :---- | :---- | :---- |
| **瞬態錯誤 (Transient)** | 503 服務不可用、Socket 超時 | 自動重試（帶退避與抖動） | RetryPolicy |
| **邏輯/數據錯誤 (Logical)** | 400 錯誤請求、JSON 解析失敗 | 快速失敗或路由至人工 | interrupt() 或 條件邊 |
| **語義錯誤 (Semantic)** | 模型幻覺、拒絕回答 | 自我修正反饋迴圈 | Supervisor 重提示 (Re-prompt) |
| **系統錯誤 (Critical)** | 資料庫連線失敗、認證過期 | 熔斷並報警 | 異常冒泡至應用監控層 |
| **遞歸錯誤 (Recursion)** | 代理間無限循環 | 強制終止或降級 | recursion_limit 配置、TTL 計數器 |

### **表 3：Command 對象使用模式速查**

| 模式名稱 | 用途 | 語法範例 |
| :---- | :---- | :---- |
| **標準更新** | 更新狀態並流向下一節點 | Command(update={"key": "val"}) |
| **動態跳轉** | 忽略預定義邊，強制跳轉 | Command(goto="node_name") |
| **父圖更新** | 子圖向父圖傳遞數據 | Command(update={...}, graph=Command.PARENT) |
| **恢復執行** | 響應中斷並提供數據 | Command(resume={"decision": "approved"}) |

#### **引用的著作**

1. RCE in "json" mode of JsonPlusSerializer · Advisory · langchain-ai/langgraph - GitHub, 檢索日期：2月 3, 2026， [https://github.com/langchain-ai/langgraph/security/advisories/GHSA-wwqv-p2pp-99h5](https://github.com/langchain-ai/langgraph/security/advisories/GHSA-wwqv-p2pp-99h5)
2. LangGraph Best Practices - Swarnendu De, 檢索日期：2月 3, 2026， [https://www.swarnendu.de/blog/langgraph-best-practices/](https://www.swarnendu.de/blog/langgraph-best-practices/)
3. LangGraph 101: Let's Build A Deep Research Agent | Towards Data Science, 檢索日期：2月 3, 2026， [https://towardsdatascience.com/langgraph-101-lets-build-a-deep-research-agent/](https://towardsdatascience.com/langgraph-101-lets-build-a-deep-research-agent/)
4. Understanding Reducers in LangGraph: How State Updates Work (With Examples!), 檢索日期：2月 3, 2026， [https://www.youtube.com/watch?v=UrVno_5wB08](https://www.youtube.com/watch?v=UrVno_5wB08)
5. Langgraph checkpointer selective memory - LangChain Forum, 檢索日期：2月 3, 2026， [https://forum.langchain.com/t/langgraph-checkpointer-selective-memory/1639](https://forum.langchain.com/t/langgraph-checkpointer-selective-memory/1639)
6. Mastering LangGraph Checkpointing: Best Practices for 2025 - Sparkco, 檢索日期：2月 3, 2026， [https://sparkco.ai/blog/mastering-langgraph-checkpointing-best-practices-for-2025](https://sparkco.ai/blog/mastering-langgraph-checkpointing-best-practices-for-2025)
7. Persistence - Docs by LangChain, 檢索日期：2月 3, 2026， [https://docs.langchain.com/oss/python/langgraph/persistence](https://docs.langchain.com/oss/python/langgraph/persistence)
8. How to implement custom BaseCheckpointSaver? - LangGraph - LangChain Forum, 檢索日期：2月 3, 2026， [https://forum.langchain.com/t/how-to-implement-custom-basecheckpointsaver/1606](https://forum.langchain.com/t/how-to-implement-custom-basecheckpointsaver/1606)
9. Python Json Serialize A Decimal Object - GeeksforGeeks, 檢索日期：2月 3, 2026， [https://www.geeksforgeeks.org/python/python-json-serialize-a-decimal-object/](https://www.geeksforgeeks.org/python/python-json-serialize-a-decimal-object/)
10. Python JSON serialize a Decimal object - Stack Overflow, 檢索日期：2月 3, 2026， [https://stackoverflow.com/questions/1960516/python-json-serialize-a-decimal-object](https://stackoverflow.com/questions/1960516/python-json-serialize-a-decimal-object)
11. Add precision option for decimal datatype · Issue #237 · aidh-ms/OpenICU - GitHub, 檢索日期：2月 3, 2026， [https://github.com/aidh-ms/OpenICU/issues/237](https://github.com/aidh-ms/OpenICU/issues/237)
12. A Beginner's Guide to Handling Errors in LangGraph with Retry Policies - DEV Community, 檢索日期：2月 3, 2026， [https://dev.to/aiengineering/a-beginners-guide-to-handling-errors-in-langgraph-with-retry-policies-h22](https://dev.to/aiengineering/a-beginners-guide-to-handling-errors-in-langgraph-with-retry-policies-h22)
13. Handling Errors in LangGraph with Retry Policies - YouTube, 檢索日期：2月 3, 2026， [https://www.youtube.com/watch?v=m3edGzRlR5Y](https://www.youtube.com/watch?v=m3edGzRlR5Y)
14. The best way in LangGraph to control flow after retries exhausted, 檢索日期：2月 3, 2026， [https://forum.langchain.com/t/the-best-way-in-langgraph-to-control-flow-after-retries-exhausted/1574](https://forum.langchain.com/t/the-best-way-in-langgraph-to-control-flow-after-retries-exhausted/1574)
15. DOC: Document behavior when node has both Command.goto and static edge · Issue #5829 · langchain-ai/langgraph - GitHub, 檢索日期：2月 3, 2026， [https://github.com/langchain-ai/langgraph/issues/5829](https://github.com/langchain-ai/langgraph/issues/5829)
16. Gracefully handling GraphRecursionError from subgraphs so the ..., 檢索日期：2月 3, 2026， [https://forum.langchain.com/t/gracefully-handling-graphrecursionerror-from-subgraphs-so-the-parent-agent-can-retry-or-degrade/2018](https://forum.langchain.com/t/gracefully-handling-graphrecursionerror-from-subgraphs-so-the-parent-agent-can-retry-or-degrade/2018)
17. Graph recursion error for multi agent architecture : r/LangGraph - Reddit, 檢索日期：2月 3, 2026， [https://www.reddit.com/r/LangGraph/comments/1lv19jm/graph_recursion_error_for_multi_agent_architecture/](https://www.reddit.com/r/LangGraph/comments/1lv19jm/graph_recursion_error_for_multi_agent_architecture/)
18. Graph API overview - Docs by LangChain, 檢索日期：2月 3, 2026， [https://docs.langchain.com/oss/javascript/langgraph/graph-api](https://docs.langchain.com/oss/javascript/langgraph/graph-api)
19. Callback Issue: Command.PARENT triggers on_chain_error - LangChain Forum, 檢索日期：2月 3, 2026， [https://forum.langchain.com/t/callback-issue-command-parent-triggers-on-chain-error/1065](https://forum.langchain.com/t/callback-issue-command-parent-triggers-on-chain-error/1065)
20. LangGraph: How do I read subgraph state without an interrupt? (Open Deep Research) : r/LangChain - Reddit, 檢索日期：2月 3, 2026， [https://www.reddit.com/r/LangChain/comments/1moi94j/langgraph_how_do_i_read_subgraph_state_without_an/](https://www.reddit.com/r/LangChain/comments/1moi94j/langgraph_how_do_i_read_subgraph_state_without_an/)
21. LangGraph routing to parent graph is shown as error · langfuse · Discussion #6060 - GitHub, 檢索日期：2月 3, 2026， [https://github.com/orgs/langfuse/discussions/6060](https://github.com/orgs/langfuse/discussions/6060)
22. Interrupts - Docs by LangChain, 檢索日期：2月 3, 2026， [https://docs.langchain.com/oss/python/langgraph/interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
