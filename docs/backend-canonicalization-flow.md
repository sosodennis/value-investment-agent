# Backend Canonicalization Flow (Model-Driven, Domain-Split)

Applies to:
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/artifacts/artifact_contract_registry.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/artifacts/artifact_contract_specs.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/interface/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/news/interface/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/technical/interface/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/debate/interface/contracts.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/artifacts/artifact_model_shared.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/**/nodes.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/shared/cross_agent/data/typed_artifact_port.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/*/data/ports.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/artifact-parsers.ts`

## 1. Objective

把 backend artifact 的 shape 正規化責任集中在 schema（Pydantic）層，並以 domain-split module 管理，避免規則散落、多處 `hasattr` 判斷與遺漏風險。

策略：`zero-compat / fail-fast`。

## 2. Runtime Flow

`Node Raw Output` -> `agents/*/interface/contracts.py (Pydantic validate + normalize)` -> `artifact_contract_registry (kind -> model, cross-agent reads)` -> `agents/*/data/ports.py via shared TypedArtifactPort` -> `artifact_manager.save_artifact (ArtifactEnvelope)` -> `/api/artifacts/{id} (discriminated envelope response)` -> `frontend parseArtifactEnvelope -> domain parser`

## 3. Module Responsibilities

1. Nodes (`workflow/nodes/*/nodes.py`)
- 只負責產生 domain raw data。
- 存檔前必須呼叫對應 agent interface parser（例如 `parse_news_artifact_model(...)`）。
- 讀取 artifact 必須透過 per-agent ports（`agents/*/data/ports.py`），不直接做 `dict/list` shape fallback。
- Cross-agent 讀取必須以 `artifact.reference.artifact_id` 為唯一來源，不可回退到舊 state mirror id。

2. Contract Specs (`artifact_contract_specs.py`)
- 單一維護 `kind -> model` 規格（SSOT）。
- API envelope 與 registry 皆共用此規格，避免雙維護。

3. Contract Registry (`artifact_contract_registry.py`)
- 單一維護 `kind -> model` 路由。
- 單一維護 cross-agent consumption policy（例如 news/debate/technical payload 允許的 kind）。
- domain artifact ports 僅調用 registry，不自行判斷 payload shape。

4. Schema layer
- `artifact_model_shared.py`: 共用 coercion/validation helper。
- `agents/*/interface/contracts.py`: per-agent schema 模組（fundamental/news/debate/technical）。
- 輸出統一使用 `model_dump(mode="json")`。
  - fundamental：`exclude_none=False`（保留 traceable null sentinel）。
  - news/debate/technical：`exclude_none=True`（降低 null 噪音）。

5. API layer (`api/server.py`)
- 僅回傳已 canonicalized 且已儲存的 artifact envelope。
- 由 `ArtifactApiResponse`（kind discriminator）做 response contract validate。

6. Domain Artifact Ports
- Shared generic: `shared/cross_agent/data/typed_artifact_port.py`
- Per-agent concrete: `agents/*/data/ports.py`
- 在 port 邊界做 Pydantic 驗證，節點內不再散落 defensive shape checks。

7. Frontend parser layer (`artifact-parsers.ts`)
- parser-first，契約漂移立即 fail-fast。
- 先由 `parseArtifactEnvelope(...)` 驗證 `kind/version`，再解析 `data`。

## 4. Pseudo

```python
# node
raw = build_news_artifact(...)
canonical = parse_news_artifact_model(raw)
artifact_id = await news_artifact_port.save_news_report(data=canonical, ...)
```

# domain schema
class NewsArtifactModel(BaseModel):
    overall_sentiment: Literal["bullish", "bearish", "neutral"]
    @field_validator("overall_sentiment", mode="before")
    def _normalize_sentiment(...)
```

## 5. Standard Change Workflow

1. 修改 node raw output（新增/刪除欄位）。
2. 修改對應 domain model：
- `agents/fundamental/interface/contracts.py`
- `agents/news/interface/contracts.py`
- `agents/technical/interface/contracts.py`
- `agents/debate/interface/contracts.py`
3. 若是新 parser helper，更新 `artifact_model_shared.py`。
4. 保持 `artifact_contract_registry.py` kind/model 對應正確。
5. 更新 backend tests：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_output_contract_serializers.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_artifact_api_contract.py`
6. 若 frontend 受影響，同 PR 更新 parser/adapter/component。
7. 跑 quality gates（backend + frontend）並附上結果。

## 6. Current Status

1. Fundamental: model-driven + domain-split 完成。
2. News: model-driven + domain-split 完成。
3. Debate: model-driven + domain-split 完成。
4. Technical: model-driven + domain-split 完成。

## 7. Why This Reduces Drift

1. 規則集中且按 domain 分檔，降低單檔過大與漏改風險。
2. 新欄位若未進 schema 會直接 validation fail，不會 silent pass。
3. API integration tests 鎖定實際 `/api/artifacts/{id}` contract。
