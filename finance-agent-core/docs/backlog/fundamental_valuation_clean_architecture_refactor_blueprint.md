# Fundamental Clean Architecture Refactor Blueprint (Valuation + Data)

Execution tracker:
1. `finance-agent-core/docs/backlog/fundamental_refactor_execution_tracker.md`

## 1. 範圍與目標

本藍圖從原本只處理 `domain/valuation`，擴展為 **整個 fundamental 模組核心流程**：

1. `src/agents/fundamental/domain/valuation`
2. `src/agents/fundamental/infrastructure`

狀態更新（2026-03-01）：

1. `fundamental/data` legacy package 已移除。
2. `sec_xbrl`、`market_data`、`artifact repository` owner 已收斂到 `infrastructure/*`。
3. `application` 對 concrete infrastructure 依賴已移除，concrete wiring 已外置到 `agents/fundamental/wiring.py`。
4. `domain` 與 `infrastructure/sec_xbrl` 的 generic module 命名已完成收斂（`models/rules/services` -> semantic owners）。

目標：

1. 清晰分層（domain/application/interface/infrastructure）。
2. 命名去歧義（特別是 `skills`、`tools.py`、`data/ports.py`）。
3. 提升內聚，降低重複與隱式耦合。
4. 保留既有功能與數值結果可追溯（backtest drift 可控）。

## 2. 現況診斷（摘要）

### 2.1 Valuation 包（既有結論）

1. 代碼量大且重複高：`~8,343 LOC`，`param_builder.py` 單檔 `1,246 LOC`，`monte_carlo.py` `796 LOC`。
2. DCF standard/growth `tools.py` 高度重複。
3. `skills` 命名語義混亂（schema/calculator/auditor/prompt 混放）。

### 2.2 Data 包（新增 review）

1. 代碼量 `~11,110 LOC`，其中 `sec_xbrl/factory.py` `2,447 LOC`、`extractor.py` `643 LOC`、`forward_signals_text.py` `419 LOC`。
2. `data` 層責任混雜：
   - 同時承載 client、mapping、artifact repo、domain projection、signal scoring policy。
3. 介面契約與實作不一致：
   - `MarketDataProvider` 協議僅定義 `fetch_datums`，`MarketDataClient` 卻對 provider 做 duck-typing (`fetch` / `fetch_datums`)。
4. import-time side effects 偏多：
   - `set_identity(...)`、mapping registry auto-register、多個 env-driven 全域開關。
5. 模型重複：
   - `FinancialReport` 結構在 `data/sec_xbrl/models.py`、`interface/contracts.py`、`domain/valuation/report_contract.py` 各自演化。
6. 測試覆蓋不對稱：
   - `data` 最大複雜度區（sec_xbrl pipeline）缺少同等級測試保護。

## 3. 核心架構原則

1. Domain：只保留業務規則、計算、審核政策；不得直接讀 env、讀檔、打網路。
2. Application：負責用例編排與工作流協調；只依賴抽象 port。
3. Interface：API / contract / serializer / parser。
4. Infrastructure：外部系統與副作用（SEC、Yahoo/FRED、artifact manager、模型服務、env config）。
5. Legacy `data` package 不再作為橫向雜湊層；最終由 `infrastructure` owner modules 取代。

## 4. 目標目錄（整體 fundamental）

```text
src/agents/fundamental/
  domain/
    valuation/
      models/
      policies/
      calculators/
      monte_carlo/
      backtest/
    selection/
      entities.py
      services.py

  application/
    use_cases/
      run_financial_health.py
      run_model_selection.py
      run_valuation.py
      run_backtest.py
    services/
      financial_health_service.py
      model_selection_service.py
      valuation_execution_service.py
      preview_projection_service.py
      artifact_assembly_service.py
      state_transition_service.py
    ports/
      market_data_port.py
      financial_payload_port.py
      artifact_repo_port.py
    valuation/
      builders/
      registry/
      shared/

  interface/
    contracts.py
    mappers.py
    parsers.py
    serializers.py

  infrastructure/
    sec_xbrl/
      extractor.py
      mapping.py
      factory.py
      provider.py
      report_contracts.py
      mappings/
      matchers/
      rules/
    market_data/
      yahoo_finance_provider.py
      fred_macro_provider.py
      market_data_service.py
    artifacts/
      fundamental_artifact_repository.py
```

### 4.1 Layer 與重要 Package 的職責/邊界

#### Domain Layer

1. `domain/valuation/models`
   - 職責：估值核心資料模型（不含 API 格式、不含外部來源細節）。
   - 邊界：不得依賴 `application/interface/infrastructure`。
2. `domain/valuation/policies`
   - 職責：純業務規則與審核規則（growth、terminal、guardrails、audit）。
   - 邊界：不得讀 env、不得做 I/O。
3. `domain/valuation/calculators`
   - 職責：確定性計算圖與公式計算。
   - 邊界：只接受已準備好的輸入，不做資料抓取與 orchestration。
4. `domain/valuation/monte_carlo`
   - 職責：Monte Carlo 抽樣與統計核心演算法。
   - 邊界：不依賴 provider/client，不讀 runtime config。
5. `domain/selection`
   - 職責：模型選擇規則、選股語義規則。
   - 邊界：不得感知 artifact、transport、第三方 SDK。

#### Application Layer

1. `application/use_cases`
   - 職責：執行單一用例流程（financial health、model selection、valuation、backtest）。
   - 邊界：只透過 `application/ports` 存取外部能力；不得直接 import infrastructure 實作。
2. `application/services`
   - 職責：可重用的流程級服務（組裝 artifact、狀態轉換、預覽投影、估值執行協調）。
   - 邊界：不寫框架/傳輸格式，不做硬編碼 I/O。
3. `application/ports`
   - 職責：對外依賴抽象（market data、financial payload、artifact repo）。
   - 邊界：只定義 Protocol/Interface，不放 concrete instance。
4. `application/valuation/builders`
   - 職責：把 canonical report + market snapshot 轉為模型參數。
   - 邊界：不直接做最終估值計算；不耦合 API payload。
5. `application/valuation/registry`
   - 職責：模型 runtime 註冊與路由。
   - 邊界：只有 wiring，不承載業務規則細節。
6. `application/valuation/shared`
   - 職責：跨模型共享工具（trace merge、unwrap、共通 metadata）。
   - 邊界：只放無副作用共用邏輯。

#### Interface Layer

1. `interface/contracts.py`
   - 職責：外部輸入輸出 DTO 契約。
   - 邊界：不含業務規則，不含外部 client 呼叫。
2. `interface/parsers.py`
   - 職責：input validation/coercion（transport -> application-friendly shape）。
   - 邊界：不包含 domain 決策。
3. `interface/mappers.py`
   - 職責：view/response 映射。
   - 邊界：不做 orchestration，不碰 data source。
4. `interface/serializers.py`
   - 職責：artifact/event response 組裝。
   - 邊界：不放估值規則與抓取邏輯。

#### Infrastructure Layer

1. `infrastructure/sec/xbrl`
   - 職責：SEC XBRL 資料提取、mapping registry、財報工廠。
   - 邊界：輸出 canonical model；不直接驅動 application state machine。
2. `infrastructure/sec/text_signals/pipeline`
   - 職責：SEC 文字訊號抽取流程編排（FLS、retrieval、signal aggregation）。
   - 邊界：僅提供資料能力，不直接決定最終 valuation policy。
3. `infrastructure/sec/text_signals/matchers`
   - 職責：regex/lemma/dependency pattern 命中檢測。
   - 邊界：只做 matcher，不能承擔流程控制。
4. `infrastructure/sec/text_signals/rules`
   - 職責：詞典/模式規則載入與校驗。
   - 邊界：規則資料與載入器，不混流程邏輯。
5. `infrastructure/market_data/providers`
   - 職責：單一來源 provider（Yahoo/FRED）。
   - 邊界：每個 provider 只負責自己資料源轉換。
6. `infrastructure/market_data/market_data_service.py`
   - 職責：多 provider 聚合、優先級、fallback、cache。
   - 邊界：不承載估值公式與 domain 規則。
7. `infrastructure/artifacts`
   - 職責：artifact manager 實作與持久化適配。
   - 邊界：不包含業務決策。
8. `infrastructure/config`
   - 職責：env/runtime config provider。
   - 邊界：集中配置讀取；禁止分散在 domain/application 各處直接 `os.getenv`。

### 4.2 Layer 依賴規則（硬限制）

1. `domain` -> 僅可依賴 `domain` 與 `shared kernel`（純型別/工具）。
2. `application` -> 可依賴 `domain`、`application`、`shared kernel`；不得依賴 `infrastructure`。
3. `interface` -> 可依賴 `application`/`domain` 的公開契約；不得依賴具體 client。
4. `infrastructure` -> 可依賴所有上層抽象（尤其 `application/ports`），但反向依賴禁止。
5. Cross-layer 原則：外部世界只能經由 `ports` 進入 use case。

### 4.3 Cross-Agent Class 命名規範（特別是 Infrastructure）

#### A. 後綴語義（必須單一）

1. `*Provider`
   - 單一外部資料源 adapter（例如 Yahoo/FRED/SEC 單來源）。
   - 不做跨來源聚合、fallback、cache。
2. `*Service`
   - 流程級協調或聚合（可調用多個 provider/repository/policy）。
3. `*Repository`
   - 持久化讀寫 gateway（artifact/db/file store）。
4. `*Client`
   - 低階 transport client（HTTP/SDK wrapper）。若已是 provider，避免再用 client 命名重疊。
5. `*Factory`
   - 只做建構，不做 network side effect 與流程編排。
6. `*Mapper`
   - 僅做資料形狀轉換，不夾帶業務決策。
7. `*Policy` / `*Config`
   - 規則與配置讀取；不可同時負責業務流程。
8. `*Port`
   - 只允許 Protocol/abstract interface；不可作為 concrete 類名。

#### B. 類別命名格式

1. Class 使用 `PascalCase`，避免同一層同時混用 acronym 全大寫與首字母大寫（例如 `SEC...` vs `Sec...`）。
2. 建議 acronym 一律當普通詞處理：`Sec`, `Xbrl`, `Fred`, `Finbert`。
3. Private helper class（前綴 `_`）只允許在模組內部使用；不可成為跨模組主要抽象。
4. Protocol 型別命名避免 `*Fn` 爆炸；優先語義化接口（例：`SentenceRetriever`, `EvidenceBuilder`）。

#### C. 檔名與類名對齊

1. `*_service.py` 內主類應為 `*Service`。
2. `*_provider.py` 內主類應為 `*Provider`。
3. `ports.py` 只放 `Protocol` 或抽象 `Port`；concrete 實作應移到 `infrastructure/*repository.py`。

### 4.4 Fundamental 現況命名問題與建議改名（Infrastructure 優先）

1. `FundamentalArtifactPort`（concrete）-> `FundamentalArtifactRepository`
2. `NewsArtifactPort`（concrete）-> `NewsArtifactRepository`
3. `DebateArtifactPort`（concrete）-> `DebateArtifactRepository`
4. `TechnicalArtifactPort`（concrete）-> `TechnicalArtifactRepository`
5. `SearchType`（static factory）-> `SearchConfigFactory`
6. `SECFetchPolicy` + `_SecRateLimiter` -> `SecFetchPolicy` + `SecRateLimiter`（去 acronym 混用）
7. `FinBERTAnalyzer` / `FinbertDirectionReview` -> 同一規則（建議 `FinbertAnalyzer` / `FinbertDirectionReview`）
8. `ForwardSignalPayload`（interface DTO）-> `ForwardSignalModel`（與 `*Model` 系列一致）
9. `BaseFinancialModelFactory`（超巨類）拆後避免 `Base*Factory` 泛名，改為語義化：
   - `XbrlFieldResolver`
   - `FinancialReportAssembler`
   - `IndustryExtensionBuilder`

## 5. 命名與責任修正（重點）

### 5.1 Valuation 命名

1. `valuation/skills/*` -> `application/valuation/use_cases/*` 或 `application/valuation/builders/*`
2. `tools.py` -> `calculator.py` / `service.py`
3. `registry.py` -> `valuation_model_registry.py`

### 5.2 Data 命名

1. `data/ports.py`（含 concrete instance）拆為：
   - `application/ports/*.py`（純 protocol）
   - `infrastructure/artifacts/fundamental_artifact_repository.py`（實作）
2. `data/mappers.py` 中 domain projection 移到 `application`（use-case mapper）。
3. `data/clients/sec_xbrl/*` 已遷移到 `infrastructure/sec_xbrl/*`（財報抽取 + 文字訊號 pipeline）。
4. `application/services/` 不保留空 package，必須是具體職責模組（如 `*_service.py`）。

## 6. 高優先整改項目

### P1（先做）

1. 統一 `FinancialReport` canonical model（單一來源），其餘層做 mapper。
2. 拆解 `sec_xbrl/factory.py`：
   - `field_resolver.py`
   - `derived_metrics.py`
   - `industry_extension_builders.py`
   - `report_factory.py`
3. 消除 import-time side effects：
   - `set_identity` 改為 runtime bootstrap。
   - mapping register 改為顯式初始化。
4. 修正 provider contract：
   - `MarketDataProvider` 統一 `fetch(...) -> ProviderFetch`，去除 runtime duck-typing。

### P2（第二波）

1. 抽出 SEC text signal pipeline 配置與 env policy provider。
2. 將 `forward_signals_text.py` 的 orchestration 與 scoring policy 分離。
3. `valuation` + `data` 共用 traceable/metadata 處理抽 shared utilities。

### P3（第三波）

1. 重命名 legacy module 並移除 shim。
2. 文檔與 runbook 全面更新。

## 7. 舊路徑到新路徑（關鍵映射）

1. `fundamental/data/clients/market_data.py`
   -> `infrastructure/market_data/market_data_service.py`
2. `fundamental/data/clients/market_providers.py`
   -> `infrastructure/market_data/{yahoo_finance_provider.py, fred_macro_provider.py}`
3. `fundamental/data/clients/sec_xbrl/factory.py`
   -> `infrastructure/sec_xbrl/*`（factory + semantic owner services）
4. `fundamental/data/clients/sec_xbrl/forward_signals_text.py`
   -> `infrastructure/sec_xbrl/*`（forward signal pipeline owners）
5. `fundamental/data/ports.py`
   -> `application/ports/* + infrastructure/artifacts/*`
6. `fundamental/data/mappers.py`
   -> `application/report_projection_service.py`

## 8. 分階段遷移計畫

狀態（2026-03-01）：

1. `Phase 0-4` 核心程式碼重構已完成並可運行收斂。
2. 剩餘工作為 `P5` 非阻塞治理切片（文檔同步、guard 覆蓋補強、回歸維持）。

## Phase 0: Baseline Freeze

1. 鎖定 valuation/backtest baseline。
2. 新增 data/sec_xbrl smoke + golden tests（至少涵蓋 report factory、text signal producer）。

完成標準：

1. 既有測試全綠。
2. 有可重現 baseline。

## Phase 1: Contract Stabilization

1. 統一 Market provider contract。
2. 統一 FinancialReport canonical model + mapper 邊界。
3. 修正 valuation 既有 type drift（MC controls tuple）。

完成標準：

1. mypy/ruff 無新增型別問題。
2. domain/application 與 infrastructure 契約清晰。

## Phase 2: Service Decomposition

1. 拆 `param_builder.py`、`sec_xbrl/factory.py`、`forward_signals_text.py`。
2. 抽 shared utilities（unwrap、trace merge、metadata builder）。

完成標準：

1. 單檔不超過 500 行（例外需註記）。
2. 重複程式碼顯著下降（目標 >= 30% in duplicated paths）。

## Phase 3: Package Re-layout

1. 引入 `infrastructure/*`。
2. 將 legacy `data` 內容逐步搬遷到 `infrastructure`，最終不保留 shim import。

完成標準：

1. application 不直接 import legacy `data/*` 具體實作（僅透過 ports）。
2. CI 綠燈且運行結果無 drift。

## Phase 4: Naming Cleanup

1. 移除 `valuation/skills`。
2. 移除 legacy `data` shim。

完成標準：

1. 無 runtime 依賴 legacy 路徑。
2. 架構文檔與實際目錄一致。

## 9. 驗收門檻

1. 所有既有測試通過。
2. valuation backtest drift：`abs_tol=1e-6`, `rel_tol=1e-4`。
3. 新增 sec_xbrl regression tests（提取 + 文字訊號至少各 1 組 golden case）。
4. 不新增 `Any`。
5. 移除 import-time side effects（identity/register/model enable flags 轉 runtime config）。

## 10. 實作優先順序（建議）

1. 先做 Phase 1（契約與模型統一）避免後續搬遷反覆衝突。
2. 接著做 `factory.py` 與 `param_builder.py` 拆解（最大收益）。
3. 最後再做 package re-layout 與命名收尾。

這樣可以在風險最小的前提下，先把可維護性與演進速度拉上來。
