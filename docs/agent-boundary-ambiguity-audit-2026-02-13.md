# Agent Boundary Ambiguity Audit (2026-02-13)

Date: 2026-02-13
Scope: `finance-agent-core/src/agents/{intent,fundamental,news,technical,debate}`
Policy Baseline: `docs/clean-architecture-engineering-guideline.md`, `docs/backend-guideline.md`, `docs/frontend-guideline.md`

## 1. 目的

這份文檔是「逐一處理」的單一清單，回答三件事：

1. 每個 Agent 現在有哪些邊界不清楚（class/function 級別）。
2. 為什麼這些點不清楚（根因）。
3. 最終期望應落在哪一層（domain/application/data/interface）。

本文件是 refactor backlog，不是歷史記錄。

## 2. 判定標準（本次審計）

1. `domain` 不應依賴 `data` / `interface` / infra 客戶端。
2. `application` 不應承擔 payload schema parsing / formatter 細節。
3. `data` 不應依賴其他 agent 的 internal 實作。
4. `interface` 可做 contract/DTO/parser，但不做業務決策。
5. cross-agent 只走 public artifact contract（kind/version + typed model）。

Priority:

1. `P0`: 明顯違反層邊界，會持續擴散 tech debt。
2. `P1`: 邊界可運作但責任混雜，維護成本高。
3. `P2`: 命名/結構一致性問題，風險較低但應收斂。

Status Update (2026-02-13):

1. P0 items `D1`, `D2`, `T1` 已完成清理並通過回歸測試。
2. 其餘項目維持 backlog，按優先級逐步處理。

## 3. 總覽

| Agent | P0 | P1 | P2 | 主要風險 |
|---|---:|---:|---:|---|
| intent | 0 | 3 | 2 | application 承擔 parsing/selection 細節，domain model 角色模糊 |
| fundamental | 0 | 5 | 3 | application/orchestrator 過厚，domain 使用 JSONObject 偏重 payload |
| news | 0 | 6 | 3 | use_cases 過大且同時含 orchestration + parsing + formatting |
| technical | 1 | 4 | 2 | application 依賴 interface serializer（層向內依賴） |
| debate | 2 | 5 | 2 | domain->data 反向依賴，cross-agent 讀取走 internal ports |

## 4. Agent 級別清單

## 4.1 Intent Agent

### A1 (P1)
- 位置: `finance-agent-core/src/agents/intent/application/orchestrator.py:93`
- 問題: `parse_candidates` 直接處理 raw mapping/list 並 `model_validate`。
- 原因: 邊界 parser 還在 application，沒有集中到 interface parser。
- 最終期望:
  - `interface/parsers.py` 提供 `parse_ticker_candidates(...)`。
  - orchestrator 只接收 typed candidates。

### A2 (P1)
- 位置: `finance-agent-core/src/agents/intent/application/orchestrator.py:129`
- 問題: `resolve_selected_symbol` 混合 user input schema 相容邏輯。
- 原因: HITL resume payload schema 未完全由 interface 層封裝。
- 最終期望:
  - `interface/parsers.py` 輸出 `ResolvedSelectionInput`。
  - application 僅做業務決策（pick symbol policy）。

### A3 (P1)
- 位置: `finance-agent-core/src/agents/intent/application/use_cases.py:24`
- 問題: `_heuristic_extract` 與 LLM prompt/structured output 並存於同檔。
- 原因: 應用層內同時有 orchestration 與 extraction strategy 細節。
- 最終期望:
  - 抽 `domain/extraction_policies.py`（heuristic policy）
  - application 組裝策略，不承載細節實作。

### A4 (P2)
- 位置: `finance-agent-core/src/agents/intent/domain/models.py:6`
- 問題: `TickerCandidate` 用 Pydantic，角色在 Domain/Interface 邊界模糊。
- 原因: Domain entity 與 transport model 尚未明確分離。
- 最終期望:
  - 若作為交換契約: 移到 `interface/contracts.py`。
  - 若作為業務 VO: domain 保留 dataclass/純型別，interface 做 DTO 映射。

### A5 (P2)
- 位置: `finance-agent-core/src/agents/intent/interface/contracts.py:5`
- 問題: interface contract 直接依賴 domain model `TickerCandidate`。
- 原因: domain/interface 未切清 model ownership。
- 最終期望:
  - interface contract 自有 DTO model。
  - domain 透過 mapper 轉換，不直接被 interface import。

## 4.2 Fundamental Agent

### F1 (P1)
- 位置: `finance-agent-core/src/agents/fundamental/application/use_cases.py:118`
- 問題: use_cases 內同時做 canonicalization、artifact save、preview build、state update 組裝。
- 原因: application 聚合過多 adapter/interface 責任。
- 最終期望:
  - use_cases 保留「業務決策 + output intent」。
  - output artifact/state 組裝下沉 `interface/serializers.py`。

### F2 (P1)
- 位置: `finance-agent-core/src/agents/fundamental/application/orchestrator.py:142`
- 問題: `run_*` 方法處理大量 state extraction/fallback/錯誤 payload 組裝。
- 原因: orchestrator 還是「node helper mega file」型態。
- 最終期望:
  - state read/write 下沉到 `application/state_readers.py` + `application/state_updates.py`。
  - orchestrator 只保留流程轉移。

### F3 (P1)
- 位置: `finance-agent-core/src/agents/fundamental/domain/model_selection.py:13`
- 問題: domain service 使用 `JSONObject`/payload path (`base.total_revenue`)。
- 原因: domain 依賴外部 payload shape，不是純 domain object。
- 最終期望:
  - 建立 `domain/entities.py` 的 typed report projection。
  - model_selection 對 typed entity 計算，不直接走 JSON path。

### F4 (P1)
- 位置: `finance-agent-core/src/agents/fundamental/data/ports.py:38`
- 問題: data port `model_dump + cast` 再抽 `financial_reports` list。
- 原因: typed port 之上仍有二次手動 mapping。
- 最終期望:
  - `TypedArtifactPort` 直接支持 nested field extract 或 domain repo mapper。
  - port return typed domain projection，而不是 raw list cast。

### F5 (P2)
- 位置: `finance-agent-core/src/agents/fundamental/application/use_cases.py:25`
- 問題: mapper context 欄位命名/語義跨層混用（`valuation_summary`, `status`, `model_type`）。
- 原因: app dto 與 interface preview dto 未切分。
- 最終期望:
  - `application/dto.py` 定義 app dto。
  - `interface/mappers.py` 負責 preview dto 轉換。

## 4.3 News Agent

### N1 (P1)
- 位置: `finance-agent-core/src/agents/news/application/use_cases.py:154`
- 問題: 一個檔案同時包含 selector fallback、fetch payload builder、analysis chain、LLM 結果解析。
- 原因: use_cases 過大，責任混合（policy + parser + formatter + orchestration helper）。
- 最終期望:
  - 切分為:
    - `application/selection_service.py`
    - `application/fetch_service.py`
    - `application/analysis_service.py`
    - `interface/parsers.py`（LLM/JSON parse）
 - 狀態: PARTIAL DONE (2026-02-13)
 - 備註: 已拆出 `selection_service.py`、`fetch_service.py`、`analysis_service.py`；
   `interface/parsers.py` 收斂仍待後續波次。

### N2 (P1)
- 位置: `finance-agent-core/src/agents/news/application/orchestrator.py:60`
- 問題: node flow + state extraction + artifact write/update 全集中。
- 原因: orchestrator 還是「流程+資料處理」雙責任。
- 最終期望:
  - orchestrator 只負責節點轉移。
  - state/result 組裝下沉到 dedicated state update builders。
 - 狀態: DONE (2026-02-13)
 - 備註: 已新增 `application/state_readers.py` 與 `application/state_updates.py`；
   `orchestrator.py` 已切換至此兩模組。

### N3 (P1)
- 位置: `finance-agent-core/src/agents/news/data/ports.py:117`
- 問題: `load_news_items_for_debate` 在 news data port 內處理 debate 消費語義。
- 原因: producer package 內承擔 consumer 特化需求。
- 最終期望:
  - news package 只暴露 public artifact contract（typed）。
  - debate consumer 在自己 data/interface parser 轉換。
 - 狀態: DONE (2026-02-13)
 - 備註: `NewsArtifactPort.load_news_items_for_debate` 已移除；
   debate 端已改為直接透過 shared artifact contract 解析。

### N4 (P1)
- 位置: `finance-agent-core/src/agents/news/application/use_cases.py:74`
- 問題: `format_selector_input` 這類展示/提示格式化屬 interface concern。
- 原因: prompt formatting 分散在 use_cases。
- 最終期望:
  - prompt formatter 收斂到 `interface/prompt_formatters.py`。
 - 狀態: DONE (2026-02-13)
 - 備註: `format_selector_input` 與 `build_analysis_chain_payload` 已下沉到
   `news/interface/prompt_formatters.py`，application service 只負責調用。

### N5 (P2)
- 位置: `finance-agent-core/src/agents/news/application/use_cases.py:91`
- 問題: `_ChainLike/_ModelDumpLike/_LLMLike` protocol 與執行細節混在同檔。
- 原因: typing scaffolding 未模組化。
- 最終期望:
  - 移到 `application/ports.py`，use_cases 只引用 port interface。
 - 狀態: DONE (2026-02-13)
 - 備註: 已新增 `news/application/ports.py`，並完成
   `selection_service.py`、`fetch_service.py`、`analysis_service.py`、`orchestrator.py`
   對集中 protocol 的引用切換。

### N6 (P2)
- 位置: `finance-agent-core/src/agents/news/domain/services.py:23`
- 問題: domain service 直接操作 dict 結構，typed entity 弱。
- 原因: domain projection 未完整建立。
- 最終期望:
  - domain 使用 `NewsItemEntity`/`AnalysisEntity`。
  - data/interface 做 dict <-> entity mapping。
 - 狀態: DONE (2026-02-13)
 - 備註: 已新增 `news/domain/entities.py` 與 `news/data/mappers.py`；
   `aggregate_news_items` 已改為只接受 `NewsItemEntity`，並由
   `NewsArtifactPort.project_news_item_entities(...)` 進入 domain。

## 4.4 Technical Agent

### T1 (P0)
- 位置: `finance-agent-core/src/agents/technical/application/use_cases.py:11`
- 問題: application 直接 import `interface.serializers.build_full_report_payload`。
- 原因: 層依賴方向反向（application -> interface）。
- 最終期望:
  - 將 serializer 調用移至 interface adapter/orchestrator邊界。
  - application 只輸出 domain/app dto。
 - 狀態: DONE (2026-02-13)

### T2 (P1)
- 位置: `finance-agent-core/src/agents/technical/application/orchestrator.py:33`
- 問題: orchestrator 直接調用 `canonicalize_technical_artifact_data`。
- 原因: interface canonicalization 責任滲入 application flow。
- 最終期望:
  - canonicalization 收斂到 data repo 或 interface serializer adapter。

### T3 (P1)
- 位置: `finance-agent-core/src/agents/technical/data/ports.py:82`
- 問題: `load_debate_payload` 在 producer data port 內實作 debate consumer 特化。
- 原因: cross-agent consumer 邏輯放錯 package。
- 最終期望:
  - 技術指標 public contract 固定；
  - debate 在自身 parser 層轉換成可辯論 payload。

### T4 (P1)
- 位置: `finance-agent-core/src/agents/technical/application/orchestrator.py:303`
- 問題: `run_semantic_translate` 同時處理 backtest/wfa context、LLM 詮釋、artifact 寫入、preview 組裝。
- 原因: application use case 拆分不足。
- 最終期望:
  - 分拆 `semantic_service`, `report_service`, `state_updates`。

### T5 (P2)
- 位置: `finance-agent-core/src/agents/technical/application/use_cases.py:128`
- 問題: use_cases 仍包含大量 pandas/index 轉換細節（infra-like）。
- 原因: domain/application 與 data transformation 邊界未細分。
- 最終期望:
  - pandas 序列化/資料轉換抽到 data mapper。
  - application 只協調 typed series objects。

## 4.5 Debate Agent

### D1 (P0)
- 位置: `finance-agent-core/src/agents/debate/domain/services.py:11`
- 問題: domain 直接 import data 層 market_data。
- 原因: 明確違反 clean dependency direction。
- 最終期望:
  - domain 定義 `RiskFreeRatePort`/`PayoffMapPolicy` 介面。
  - application 注入 data adapter，domain 不 import data。
 - 狀態: DONE (2026-02-13)

### D2 (P0)
- 位置: `finance-agent-core/src/agents/debate/data/report_reader.py:5`
- 問題: debate data 直接 import fundamental/news/technical data ports。
- 原因: 依賴其他 agent internal，非 public contract。
- 最終期望:
  - 透過 shared public artifact contract（kind/version + typed models）。
  - debate reader 只依賴 shared contract reader，不依賴他 agent data package。
 - 狀態: DONE (2026-02-13)

### D3 (P1)
- 位置: `finance-agent-core/src/agents/debate/domain/services.py:20`
- 問題: `SycophancyDetector`（fastembed model 載入）放在 domain。
- 原因: 這是 infra/tool concern，不是純業務規則。
- 最終期望:
  - 移到 `data/clients` 或 `application/services` 並以 port 注入。

### D4 (P1)
- 位置: `finance-agent-core/src/agents/debate/application/use_cases.py:52`
- 問題: `DebateFactExtractionResult` 放 use_cases.py，與其他 dto 分散。
- 原因: dto ownership 不一致，造成「放哪裡」反覆爭議。
- 最終期望:
  - 統一放 `application/dto.py`（或 domain value object，二選一且固定）。

### D5 (P1)
- 位置: `finance-agent-core/src/agents/debate/application/use_cases.py:65`
- 問題: `prepare_debate_reports` 依賴 `compress_*` 與 artifact loading，混合 application/data/domain concerns。
- 原因: reader + compression + flow 組裝未分離。
- 最終期望:
  - data reader 回 typed source bundle。
  - domain 提供 pure compression policy。
  - application 僅 orchestrate。

### D6 (P2)
- 位置: `finance-agent-core/src/agents/debate/interface/contracts.py:247`
- 問題: `parse_debate_artifact_model` 是薄封裝，路由層與 parse 層仍有重複。
- 原因: registry 與 agent interface parse 還有重複橋接。
- 最終期望:
  - parse 路由統一走 artifact contract registry，agent interface 只保留 model/rules。

## 5. 橫向（跨 agent）問題

### X1 (P0) Cross-agent internal coupling
- 位置: `debate/data/report_reader.py`
- 問題: 直接依賴他 agent data ports。
- 最終期望: 全部改為 shared public artifact contract reader。

### X2 (P1) Application 過厚 + State update 拼裝分散
- 位置: `fundamental/news/technical` orchestrator/use_cases 多處。
- 問題: 每個 agent 都重複 state extraction/update 組裝。
- 最終期望: 每 agent 標準化 `application/state_readers.py` + `application/state_updates.py`。

### X3 (P1) Domain 對 JSON payload 依賴過重
- 位置: `fundamental/domain/model_selection.py`, `news/domain/services.py` 等。
- 問題: domain 直接操作 dict path，易受 contract shape 變動影響。
- 最終期望: domain 只吃 typed entities/value objects。

### X4 (P2) 命名不一致（service/use_cases/orchestrator/parser）
- 問題: 同類責任在不同 agent 命名策略不同，造成放置判斷成本。
- 最終期望: 以 `docs/backend-guideline.md` 命名規則統一（後續單獨命名規範文檔可再固化）。

## 6. 最終目標（每個 agent 一致形態）

每個 agent 最終都收斂到：

1. `domain/`: entity/value object/rules/pure services（不 import data/interface）。
2. `application/`: use cases + orchestrator + dto + ports + state readers/updates。
3. `data/`: repositories/clients/typed artifact ports（只處理 IO 與 mapping）。
4. `interface/`: contracts/parsers/serializers/mappers（payload boundary）。

Cross-agent:

1. producer 發布 public artifact contract（kind/version + typed model）。
2. consumer 透過 shared contract reader 讀取，不 import producer internal package。

## 7. 建議執行順序（逐一處理）

1. `P0` 先清（D1, D2, T1, X1）。
2. 再清三個高頻厚檔（N1, F1/F2, T4）。
3. 最後做 naming/typed entity 收尾（P2 + X4）。

DoD（每個項目）:

1. 新增/更新對應測試（至少 boundary parser + use case）。
2. 不引入 compatibility fallback。
3. 不新增 `Any`。
4. 不新增 cross-agent internal import。
