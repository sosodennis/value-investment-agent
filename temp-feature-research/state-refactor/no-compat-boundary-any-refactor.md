# No-Compatibility Refactor Plan

## 1. 目標

本次重構只做一件事：把系統改成「單一型別契約 + 嚴格邊界驗證」，不保留向後相容分支。

### 目標清單

1. 移除核心流程中的 `hasattr(...)`/`model_dump` 雙軌判斷。
2. 統一 State 內資料形狀（只允許 canonical dict payload）。
3. 移除 `Any`，改成明確型別（包含 JSON value、事件 payload、中斷 payload）。
4. 邊界層 fail-fast，不再 fallback 到 legacy shape。

### 非目標

1. 不做平滑遷移。
2. 不保證舊 checkpoint/舊 payload 可讀。
3. 不保留「dict + Pydantic 混用」的兼容邏輯。

## 2. 什麼是邊界 (Boundary)

邊界 = 「外部不受我們完整型別控制」的地方。
邊界外資料進來要先 normalize，出去要先 serialize。

### 系統邊界

1. LangGraph runtime event (`astream_events`) -> `/src/interface/adapters.py`
2. HTTP request/response -> `/api/server.py`
3. DB ORM model (`Artifact`, `ChatMessage`) -> `/src/services/*.py`
4. LLM output -> `/src/workflow/nodes/*/nodes.py`
5. Interrupt payload -> `/src/workflow/interrupts.py` + `/src/interface/adapters.py`

### 核心區 (非邊界)

1. `/src/workflow/state.py`
2. `/src/workflow/nodes/**`
3. `/src/interface/mappers.py`

核心區不做 duck typing，不使用 `hasattr` 猜 shape。

## 3. Canonical 契約 (不相容舊格式)

### 3.1 Artifact payload (State 內)

State 內 `artifact` 一律使用 dict TypedDict，禁止直接存 Pydantic object。

```python
class ArtifactReferencePayload(TypedDict):
    artifact_id: str
    download_url: str
    type: str


class ArtifactPayload(TypedDict):
    summary: str
    preview: dict[str, JSONValue] | None
    reference: ArtifactReferencePayload | None
```

### 3.2 JSON 型別 (全域)

新增 `/src/common/types.py`：

```python
type JSONScalar = str | int | float | bool | None
type JSONValue = JSONScalar | list["JSONValue"] | dict[str, "JSONValue"]
```

所有原本 `Any` 的 payload 型別，改成 `JSONValue` 或更細的 TypedDict。

### 3.3 邊界規則

1. Inbound：`model_validate(...)` or strict parser，失敗直接 raise。
2. Core：只接受 canonical type，沒有 fallback。
3. Outbound：只輸出 JSON-serializable canonical payload。

## 4. 主要改動範圍

### A. Interface layer

1. `/src/interface/mappers.py`
2. `/src/interface/adapters.py`
3. `/src/interface/protocol.py`
4. `/src/interface/schemas.py`

### B. Workflow hot paths

1. `/src/workflow/state.py`
2. `/src/workflow/nodes/debate/nodes.py`
3. `/src/workflow/nodes/financial_news_research/nodes.py`
4. `/src/workflow/nodes/intent_extraction/nodes.py`
5. `/src/workflow/nodes/technical_analysis/nodes.py`
6. `/src/workflow/nodes/fundamental_analysis/nodes.py`

### C. Service / API

1. `/src/services/history.py`
2. `/api/server.py`

## 5. Before/After 範例

### 範例 1：Mapper 去除 duck typing

Before:

```python
if hasattr(value, "artifact") and value.artifact:
    return value.artifact.model_dump() if hasattr(value.artifact, "model_dump") else value.artifact
if isinstance(value, dict) and value.get("artifact"):
    ...
```

After:

```python
def extract_artifact(value: AgentContextPayload) -> ArtifactPayload | None:
    return value.get("artifact")
```

說明：`value` 在進 core 前已保證是 canonical TypedDict。

### 範例 2：Debate 取 artifact id

Before:

```python
if hasattr(news_artifact, "reference") and news_artifact.reference:
    artifact_id = news_artifact.reference.artifact_id
elif isinstance(news_artifact, dict) and news_artifact.get("reference"):
    ...
```

After:

```python
def resolve_news_artifact_id(ctx: FinancialNewsContext) -> str | None:
    artifact = ctx.get("artifact")
    if artifact and artifact.get("reference"):
        return artifact["reference"]["artifact_id"]
    return ctx.get("news_items_artifact_id")
```

### 範例 3：History 序列化去掉 `Any` + `hasattr`

Before:

```python
elif hasattr(obj, "model_dump"):
    return obj.model_dump(mode="json")
elif hasattr(obj, "dict"):
    return obj.dict()
```

After:

```python
def to_json_value(obj: object) -> JSONValue:
    if isinstance(obj, dict):
        return {str(k): to_json_value(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [to_json_value(v) for v in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    raise TypeError(f"Non-serializable metadata type: {type(obj)!r}")
```

## 6. Any 移除策略

### 6.1 先建共用型別

新增：

1. `JSONValue`, `JSONObject`, `JSONArray`
2. `InterruptResumePayload` TypedDict
3. `LangGraphEventPayload` TypedDict (只涵蓋目前用到欄位)

### 6.2 檔案級改動

1. `/api/server.py`
   - `resume_payload: Any | None` -> `InterruptResumePayload | None`
   - `build_agent_lookup(graph: Any)` -> protocol 或具體 LangGraph 型別
2. `/src/interface/protocol.py`
   - `data: dict[str, Any]` -> `dict[str, JSONValue]`
   - `metadata: dict[str, Any]` -> `dict[str, JSONValue]`
3. `/src/interface/schemas.py`
   - `preview: dict[str, Any] | None` -> `dict[str, JSONValue] | None`
4. `/src/workflow/state.py`
   - `dict[str, Any]` 與 `list[Any]` 改成對應 TypedDict / union
5. `/src/interface/mappers.py`
   - `map_all_outputs(graph_state: dict[str, Any])` -> `Mapping[str, AgentContextPayload]`

## 7. 執行階段

### Phase 0: Type Foundation

1. 新增 `/src/common/types.py`
2. 定義 `ArtifactPayload`/`ArtifactReferencePayload`
3. 所有 Context 的 `artifact` 改用 payload TypedDict

### Phase 1: Boundary Hardening

1. adapter/server/history 增加 strict parser
2. 不符 shape 直接報錯（含錯誤訊息與 node 名）

### Phase 2: Core Cleanup

1. 重寫 `NodeOutputMapper`（移除 `hasattr`）
2. 重寫 `debate/nodes.py` 的 artifact/provenance 讀取 helper
3. 移除 `model_dump if hasattr(...)` 分支

### Phase 3: Any Removal

1. 全域替換 `Any`
2. 開啟靜態檢查 gate（mypy/pyright）

### Phase 4: Tests + Gate

1. 更新單元測試（僅測 canonical shape）
2. 新增負測試：非 canonical payload 必須 fail-fast

## 8. 驗收標準

1. `rg -n "hasattr\\(" src api` 不再出現在 core 熱點（interface mapper + debate + history）。
2. `rg -n "\\bAny\\b" src api` 為 0（或只剩外部第三方 stub 無法避免處）。
3. 所有 `artifact` 在 state/checkpoint/replay 中 shape 一致。
4. 任何 legacy payload 進入邊界會得到明確錯誤，不會被靜默吞掉。

## 9. 風險與切換策略

因為無 compatibility，必須一次切換：

1. 清掉舊 checkpoint/thread 測試資料（避免舊 shape 混入）。
2. 前後端同版發布（protocol 同步）。
3. 發版前跑全流程 e2e（intent -> FA/news/TA -> debate -> artifacts -> thread APIs）。
