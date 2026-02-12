# Backend Canonicalization Flow (Model-Driven, Domain-Split)

Applies to:
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/canonical_serializers.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/canonical_models/__init__.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/canonical_models/shared.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/canonical_models/fundamental.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/canonical_models/news.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/canonical_models/debate.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/interface/canonical_models/technical.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/workflow/nodes/**/nodes.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/api/server.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/types/agents/artifact-parsers.ts`

## 1. Objective

把 backend artifact 的 shape 正規化責任集中在 schema（Pydantic）層，並以 domain-split module 管理，避免規則散落、多處 `hasattr` 判斷與遺漏風險。

策略：`zero-compat / fail-fast`。

## 2. Runtime Flow

`Node Raw Output` -> `canonical_serializers facade` -> `canonical_models/<domain>.py (Pydantic validate + normalize)` -> `artifact_manager.save_artifact` -> `/api/artifacts/{id}` -> `frontend parser-first`

## 3. Module Responsibilities

1. Nodes (`workflow/nodes/*/nodes.py`)
- 只負責產生 domain raw data。
- 存檔前必須呼叫 `canonicalize_*_artifact_data(...)` 或 `normalize_financial_reports(...)`。

2. Facade (`canonical_serializers.py`)
- 提供穩定入口（fundamental/news/debate/technical）。
- 不承載 domain business rule，只轉發到 parser 並保留 context error。

3. Schema layer (`canonical_models/*.py`)
- `shared.py`: 共用 coercion/validation helper。
- `fundamental.py`: traceable field + report schema + extension type normalize。
- `news.py`: sentiment/impact/category normalize。
- `debate.py`: verdict/risk/scenario/history/facts normalize。
- `technical.py`: statistical enums + raw time-series normalize。
- 輸出統一使用 `model_dump(mode="json")`。
  - fundamental：`exclude_none=False`（保留 traceable null sentinel）。
  - news/debate/technical：`exclude_none=True`（降低 null 噪音）。

4. API layer (`api/server.py`)
- 僅回傳已 canonicalized 且已儲存的 artifact，不做臨時 patch。

5. Frontend parser layer (`artifact-parsers.ts`)
- parser-first，契約漂移立即 fail-fast。

## 4. Pseudo

```python
# node
raw = build_news_artifact(...)
canonical = canonicalize_news_artifact_data(raw)
artifact_id = await artifact_manager.save_artifact(data=canonical, ...)
```

```python
# facade
def canonicalize_news_artifact_data(value: object) -> JSONObject:
    return parse_news_artifact_model(value)
```

```python
# domain schema
class NewsArtifactModel(BaseModel):
    overall_sentiment: Literal["bullish", "bearish", "neutral"]
    @field_validator("overall_sentiment", mode="before")
    def _normalize_sentiment(...)
```

## 5. Standard Change Workflow

1. 修改 node raw output（新增/刪除欄位）。
2. 修改對應 domain model：
- `canonical_models/fundamental.py`
- `canonical_models/news.py`
- `canonical_models/debate.py`
- `canonical_models/technical.py`
3. 若是新 domain parser，更新 `canonical_models/__init__.py` export。
4. 保持 `canonical_serializers.py` 入口對應正確。
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
