這是一份融合了 **v2.0 的完整代碼細節** 與 **v3.0 的核心架構理念（View Model 模式、零 Deprecation）** 的最終版工程約章。

這份文件修復了 v3.0 中遺漏的數據庫與服務層實作細節，同時保留了最嚴格的介面隔離標準。

---

# 🚀 Value Investment Agent - Engineering Charter (v3.1 Final)

## 1. 核心架構願景

**從「單體大狀態 (Monolithic State)」轉型為「引用傳遞 (Pass-by-Reference) & 視圖分離 (View Model)」架構。**

* **現狀 (Legacy)**: 所有數據（財報、新聞、分析結果）都塞入 `AgentState`，通過 WebSocket 全量推送到前端。導致 Checkpoint 巨大、Token 浪費、前端卡頓。
* **目標 (Target)**:
* **State (真理來源)**: 僅存儲「業務數據 (Business Data)」、「控制流標記」與「數據指針 (IDs)」。
* **Artifact Store (重型倉庫)**: 重型數據存入外部 Postgres 表，與 Graph 狀態解耦。
* **Interface (翻譯官)**: 負責將 State 映射為前端需要的 `Preview` (熱數據) 與 `Reference` (冷數據)。
* **Frontend (雙速渲染)**: 立即渲染 `Preview`，按需拉取 (Pull) `Reference`。



---

## 2. 數據傳輸三層協議 (The 3-Tier Protocol)

工程師在新增數據字段前，必須對照此表決定存放位置與傳輸方式。**嚴禁使用已廢棄的 `data` 字段**。

| 層級 | 名稱 | 用途 | 大小限制 | 存放位置 | 傳輸方式 |
| --- | --- | --- | --- | --- | --- |
| **L1** | **Summary** | 消息氣泡文本 | < 500 chars | State (`messages`) | WebSocket Push |
| **L2** | **Preview** | **UI 關鍵渲染數據** (指標、狀態、標籤) | < 1 KB | State (`business fields`) -> Adapter | WebSocket Push |
| **L3** | **Reference** | **重型內容** (表格、長文、圖表配置) | 無限制 | Artifact Store (DB) | **Pull Only** (HTTP GET) |

---

## 3. 後端工程規範 (Backend Standards)

### 3.1 狀態容器 (State Management)

**規範**：Root State 必須使用 `TypedDict`。State 存儲的是**業務真理**，不需要包含 `preview` 字段（那是 Adapter 的工作）。

**文件**: `src/workflow/state.py`

```python
from typing import TypedDict, Annotated
from langgraph.graph.message import add_messages
from src.utils.reducers import merge_dicts

# GOOD: 使用 TypedDict，僅存業務數據與 ID
class AgentState(TypedDict):
    # 通信通道
    messages: Annotated[list, add_messages]

    # 業務狀態 (Source of Truth)
    fundamental_analysis: Annotated[dict, merge_dicts]
    # e.g., {
    #   "status": "success",
    #   "valuation_score": 85.5,    <-- 真理數據 (L2 源頭)
    #   "latest_report_id": "uuid"  <-- 指針 (L3 源頭)
    # }

    technical_analysis: Annotated[dict, merge_dicts]
    # e.g., {"status": "running", "chart_data_id": "uuid-..."}

```

### 3.2 外部 Artifact Store (Database Model)

**規範**：建立獨立的 `artifacts` 表，脫離 LangGraph 的 Checkpointer 機制。

**文件**: `src/infrastructure/models.py`

```python
from sqlalchemy import Column, String, DateTime, JSON
from datetime import datetime
import uuid
from .database import Base

class Artifact(Base):
    __tablename__ = "artifacts"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    key = Column(String, index=True)      # e.g., "fin_report_AAPL_2025_Q3"
    thread_id = Column(String, index=True, nullable=True) # 關聯會話
    type = Column(String)                 # e.g., "financial_report", "markdown"
    data = Column(JSON, nullable=False)   # <--- 5MB 的重型數據存這裡
    created_at = Column(DateTime, default=datetime.utcnow)

```

### 3.3 Artifact 服務層 (Service Layer)

**規範**：所有 Node 禁止直接操作 DB，必須通過 Manager 存取。

**文件**: `src/services/artifact_manager.py`

```python
from src.infrastructure.database import AsyncSessionLocal
from src.infrastructure.models import Artifact

async def save_artifact(data: dict, type: str, key_prefix: str) -> str:
    """存入 DB，返回 UUID"""
    async with AsyncSessionLocal() as session:
        artifact = Artifact(
            key=key_prefix,
            type=type,
            data=data
        )
        session.add(artifact)
        await session.commit()
        return artifact.id

async def get_artifact(artifact_id: str) -> dict | None:
    """按 ID 讀取"""
    # ... (標準 select 邏輯) ...

```

### 3.4 Node 開發模式 (Compute -> Clean -> Store -> Refer)

**規範**：Node 負責生成數據、存入 Artifact Store，並更新 State 中的**真理字段**與**指針**。

**文件**: `src/workflow/nodes/fundamental_analysis/graph.py`

```python
from src.interface.mappers import map_sec_to_clean_json # 用於清洗重型數據的 Mapper
from src.services.artifact_manager import save_artifact

async def financial_health_node(state):
    # 1. Compute/Fetch (獲取髒數據)
    raw_reports = await fetch_sec_data(state["ticker"])

    # 2. Clean (清洗為前端友好的大JSON)
    clean_large_data = map_sec_to_clean_json(raw_reports)

    # 3. Store (存入 DB)
    artifact_id = await save_artifact(
        data=clean_large_data,
        type="financial_report",
        key_prefix=f"fin_{state['ticker']}"
    )

    # 4. Refer (更新 State 真理)
    return Command(
        update={
            "fundamental_analysis": {
                "status": "success",
                "valuation_score": 85.5,         # 存入真理 (Adapter 會讀這個做 Preview)
                "latest_report_id": artifact_id  # 存入指針
            },
            "messages": [AIMessage(content=f"財報已生成 (ID: {artifact_id})")]
        }
    )

```

---

## 4. 介面適配層規範 (Interface Layer Standards)

這是連接後端邏輯與前端 UI 的橋樑，**也是本次重構最嚴格的部分**。

### 4.1 Protocol 契約 (API Contract)

**規範**：徹底移除 `data` 字段。強制區分 `preview` (熱數據) 與 `reference` (冷數據)。

**文件**: `src/interface/protocol.py`

```python
from pydantic import BaseModel, Field
from typing import Optional, Any, Dict

class ArtifactReference(BaseModel):
    artifact_id: str
    download_url: str  # e.g., "/api/v1/artifacts/{id}"
    type: str

class AgentOutputArtifact(BaseModel):
    summary: str

    # L2: Preview (熱數據) - UI 立即渲染用 (<1KB)
    # 來源：由 Adapter 調用 Mapper 從 State 生成
    preview: Optional[Dict[str, Any]] = Field(default=None)

    # L3: Reference (冷數據) - UI 異步加載用
    # 來源：指向 Artifact Store
    reference: Optional[ArtifactReference] = Field(default=None)

    # ⛔️ DEPRECATED: 已移除 data 字段，嚴禁使用

```

### 4.2 Mappers (視圖邏輯)

**規範**：負責定義「如何把後端 State 變成前端 Preview」。

**文件**: `src/interface/mappers.py`

```python
from typing import Dict, Any

def summarize_fundamental_for_preview(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    將 Fundamental State (真理) 映射為 Preview (視圖)
    """
    raw_score = state.get("valuation_score")

    return {
        "ticker": state.get("ticker"),
        "status_label": "完成" if state.get("status") == "success" else "處理中",
        # 格式化邏輯在這裡處理
        "score_display": f"{raw_score:.1f}" if raw_score else "N/A"
    }

```

### 4.3 Adapter (搬運工)

**規範**：Adapter 禁止直接透傳 State。必須調用 Mapper 生成 Preview，並檢查 ID 生成 Reference。

**文件**: `src/interface/adapters.py`

```python
from .protocol import AgentOutput, AgentOutputArtifact, ArtifactReference
from .mappers import summarize_fundamental_for_preview

def to_frontend_format(state: dict) -> AgentOutput:
    # 1. 獲取真理來源
    fund_state = state.get("fundamental_analysis", {})
    report_id = fund_state.get("latest_report_id")

    # 2. 生成 Preview (調用 Mapper)
    preview_payload = summarize_fundamental_for_preview(fund_state)

    # 3. 生成 Reference (檢查 ID)
    reference_payload = None
    if report_id:
        reference_payload = ArtifactReference(
            artifact_id=report_id,
            download_url=f"/api/artifacts/{report_id}",
            type="financial_report"
        )

    # 4. 組裝 (無 data 字段)
    return AgentOutput(
        step=state.get("current_node"),
        artifact=AgentOutputArtifact(
            summary="分析結果已更新",
            preview=preview_payload,
            reference=reference_payload
        )
    )

```

---

## 5. 前端工程規範 (Frontend Standards)

### 5.1 API Client (Fetch-on-Demand)

**規範**：前端使用 Hook 主動拉取數據。

**文件**: `src/hooks/useArtifact.ts`

```typescript
import useSWR from 'swr';

export function useArtifact<T>(artifactId?: string) {
  // 只有當 ID 存在時才發請求 (Conditional Fetching)
  const { data, error, isLoading } = useSWR<T>(
    artifactId ? `/api/artifacts/${artifactId}` : null,
    fetcher
  );

  return { data, error, isLoading };
}

```

### 5.2 組件實作 (Dual-Speed Rendering)

**規範**：組件需同時處理 `preview` (立即顯示) 和 `reference` (異步加載)。

**文件**: `src/components/agent-outputs/FundamentalAnalysisOutput.tsx`

```tsx
import { useArtifact } from '@/hooks/useArtifact';

export const FundamentalOutput = ({ state }) => {
  // 1. 解構 Protocol
  const { preview, reference } = state.artifact || {};

  // 2. Hot Path: 立即渲染關鍵指標 (無 Loading)
  if (!preview) return <Skeleton />;

  return (
    <div className="card">
      <div className="header">
        <h1>{preview.ticker}</h1>
        <span className="score">{preview.score_display}</span>
      </div>

      {/* 3. Cold Path: 異步加載詳細報表 */}
      {reference ? (
        <AsyncReportViewer artifactId={reference.artifact_id} />
      ) : (
        <div className="text-gray-400">詳細報表準備中...</div>
      )}
    </div>
  );
};

const AsyncReportViewer = ({ artifactId }) => {
    const { data } = useArtifact(artifactId);
    if (!data) return <Spinner />;
    return <FinancialTable data={data} />;
}

```

---

## 6. API 層規範 (API Layer)

**規範**：暴露只讀接口供前端「贖回」數據。

**文件**: `src/api/server.py`

```python
from fastapi import APIRouter, HTTPException
from src.services.artifact_manager import get_artifact

router = APIRouter()

@router.get("/artifacts/{artifact_id}")
async def fetch_artifact_endpoint(artifact_id: str):
    data = await get_artifact(artifact_id)
    if not data:
        raise HTTPException(status_code=404, detail="Artifact not found")
    return data  # 直接返回 JSON

```

---

## 7. 重構執行路線圖 (Migration Roadmap)

1. **Database**: 創建 `artifacts` 表 (SQL Migration)。
2. **Service**: 實作 `ArtifactManager` 並編寫單元測試。
3. **State**: 修改 `AgentState` 為 `TypedDict`，移除所有 `list[dict]` 類型的大字段。
4. **Protocol**: 修改 `protocol.py`，**徹底刪除 `data**`，新增 `preview` 和 `reference`。
5. **Mappers**: 創建 `summarize_..._for_preview` 函數系列。
6. **Nodes**: 逐個重構 Agent，將大數據寫入 `save_artifact`，State 只存真理數據與 ID。
7. **Adapter**: 重寫 `adapters.py`，連接 State 與 Mapper。
8. **Frontend**: 部署 `useArtifact` Hook 並更新組件以支持雙速渲染。
