# Fundamental Refactor 經驗總結與跨 Agent 套用手冊

日期: 2026-02-28
範圍: `finance-agent-core/src/agents/fundamental`（可跨 agent 復用）
狀態: Draft for review

## 1. 目的

本文件總結 fundamental refactor 過程中反覆出現的實作問題，並轉成可執行的 guardrails，供後續 `news/debate/technical/intent` 等 agent 重構時直接套用。

目標：

1. 降低架構與職責歧義。
2. 避免 fallback 與 compatibility 分支長期滯留。
3. 提升可維護性與可讀性。
4. 提供「輕量但可落地」的重構操作標準。

## 2. 這次重構中反覆出現的錯誤

## 2.1 Canonical Contract Owner 不清楚

現象：

1. 同一概念（例如 `FinancialReport`）在 `infrastructure/interface/domain` 各自演化。
2. canonical 欄位（如 `industry_type`、`extension_type`）混入 source-specific label（如 `Financial Services`、`Financial`、`Real Estate`）。

影響：

1. shape drift、coercion 分支增加、行為不可預期。
2. adapter 與 contract 邊界模糊，導致「看似 canonical、實則仍需 parser 補正」。
3. source label alias 規則若放在 domain shared module，容易造成 layer 邊界污染。

避免方式：

1. 每個核心契約只允許一個 canonical owner。
2. 其他層只做 projection/mapping，不重新定義語義。
3. 用測試鎖定 owner 的 strict contract。
4. canonical 欄位只允許 canonical token；來源標籤僅限 infrastructure routing 內部使用。
5. source label alias 正規化 helper 應放在 infrastructure/interface 邊界，不放 domain shared semantics。

## 2.2 Compatibility 分支累積

現象：

1. 為遷移方便保留舊入口，最後變成永久複雜度。

影響：

1. parser 分支膨脹，review 成本高，維護風險上升。

避免方式：

1. compatibility 必須有移除計畫與目標批次。
2. call site 與測試遷移完成後立即移除。
3. 每批移除都寫進 execution tracker。
4. 僅做 re-export 的 one-hop alias module（例如 `financial_payload_provider.py`）應優先移除，避免雙路徑長期並存。

## 2.3 Silent Fallback / 隱式推斷

現象：

1. 缺欄位時用弱訊號補值（如 `industry_type -> extension_type`）。

影響：

1. 隱性行為多，輸出在不同路徑不一致。

避免方式：

1. canonical contract 優先 strict，不做靜默推斷。
2. 若過渡期必須 fallback，僅限 adapter 邊界且明確排程移除。
3. 補上「應該報錯」的負向測試。

## 2.4 Layer 邊界滲漏

現象：

1. domain/application 混入 infrastructure 關注（env、source 特定邏輯、副作用）。

影響：

1. 測試困難、耦合升高、變更風險大。

避免方式：

1. domain 保持 deterministic、無副作用。
2. application 只做 orchestration。
3. infrastructure 只做來源整合與 adapter 責任。

## 2.5 命名與實際責任不一致

現象：

1. concrete class 用 `*Port` 命名、`tools.py` 混責任、超大 `Factory`。
2. package 命名在同一 bounded context 內重複前綴（例如 `valuation/models/valuation_*`）。
3. policy 模組使用過度泛化檔名（如 `rules.py`），難以由檔名理解責任範圍。
4. 跨模型共用 policy 被放在 `models/*` 底下，owner 邊界不清楚（model vs policy）。
5. runtime package 內殘留 `_template` 與 `SKILL.md` 等樣板/提示文件，增加結構噪音。

影響：

1. 心智模型錯誤，模組被誤用。

避免方式：

1. 強制 suffix 語義：`Provider/Service/Repository/Client/Factory/Mapper/Port`。
2. concrete 類別不得命名為 `*Port`。
3. oversized class 依責任拆分。
4. package 命名避免 context stutter，子 package 只保留 capability token（例如 `dcf_standard`，不要 `valuation_dcf_standard`）。
5. policy 類檔案使用語義化檔名（例如 `valuation_audit_policy.py`），避免 generic `rules.py`。
6. 跨模型 policy 以 `domain/.../policies/*_policy.py` 作為 canonical owner，避免掛在 `models/*` 子樹。
7. 將 runtime 共用基底模型改為語義化 owner（例如 `base_valuation_params.py`），避免 `_template` 目錄。
8. prompt/spec 文檔（如 `SKILL.md`）移出 runtime source tree，避免與可執行代碼混放。
9. 同一模型家族的參數契約檔名統一為 `contracts.py`，避免 `schemas.py/contracts.py` 並存造成語義漂移。

## 2.6 God Module 與型別契約重複

現象：

1. 同檔案同時放 orchestration、contracts、helpers、policies。
2. 重複定義 `TraceInput`、tuple signature 等型別契約。
3. entrypoint 主檔同時承載 model registry cache 與 builder context wiring，主檔語義密度過高。

影響：

1. 主檔語義密度過高，型別不一致風險增加。

避免方式：

1. 共用 contracts/types 集中到 owner module。
2. orchestrator 檔案只保留流程拼裝。
3. callable signature 與 payload protocol 統一管理。
4. registry/cache wiring 與依賴組裝抽到 dedicated `*_service.py`，避免主檔同時負責流程與 wiring。
5. `orchestrator.py` 的 `run_*` 主流程應拆到 `application/use_cases/*`，orchestrator 僅保留 capability container + delegation。
6. 同一模型家族（如 DCF standard/growth）若計算流程高度重疊，應抽到 `domain/.../calculators` 共用 owner，模型檔只保留 variant policy 與 graph 綁定。
7. 若多個 calculator 反覆出現同一 runtime support（`_unwrap`、`_apply_trace_inputs`、upside 計算），應集中到 shared support module，不可在各 model 重複維護。
8. 當 calculators owner 穩定後，應移除 model package 的 calculator 相容層，並讓 registry/call sites 直接引用 `domain/.../calculators/*_calculator.py`。

## 2.7 Legacy Import 回流

現象：

1. 已移除的 package path 又在 runtime import 出現。

影響：

1. 隱性回歸與啟動期故障。

避免方式：

1. 建立 AST 層級 import hygiene guard。
2. 明確封鎖 legacy prefix。
3. 將此類回歸視為 blocking issue。

## 2.8 邊界測試不對稱

現象：

1. 複雜路徑調整後，缺少同等級 contract regression 測試。

影響：

1. refactor 信心依賴人工推理，不可持續。

避免方式：

1. 每批切片固定做：
   `lint + targeted tests + expanded regression`。
2. 優先覆蓋跨邊界路徑（source -> canonical -> domain input）。

## 2.9 敘述字串驅動控制流（Narrative String Coupling）

現象：

1. 用 `assumptions` 或 log 字串內容來決定實際流程分支（例如依字串片段決定 `shares_source`）。

影響：

1. 控制邏輯依賴文案，重構文案或 i18n 時容易產生隱性回歸。
2. 測試會被迫綁定字串細節，降低可維護性與可讀性。

避免方式：

1. policy/service 應回傳 typed decision（例如 bool/enum/explicit source flag）。
2. human-readable 文案僅用於解釋，不可作為控制流輸入。
3. 對 typed decision 加上回歸測試，避免字串耦合回流。

## 2.10 Mapping Registry 單檔壅塞（Catalog Monolith）

現象：

1. `mappings/base.py` 類型檔案同時承載大量 mapping catalog 定義，單檔過大且責任混雜（core/debt/income/cash-flow）。

影響：

1. reviewer 難以快速定位某一族 mapping 的 owner 與變更邊界。
2. 小改動也會造成高噪音 diff，回歸風險評估成本高。

避免方式：

1. 依語義切分 mapping owner modules（例如 `base_core_fields.py`、`base_debt_fields.py`、`base_income_fields.py`、`base_cash_flow_fields.py`）。
2. `base.py` 僅保留 thin registration orchestration，不再承載大段 mapping literals。
3. 變更後補 mapping/resolver 路徑回歸測試，確保註冊行為不漂移。

## 2.11 隱性 Utility 相容契約（Hidden Utility Compatibility Contract）

現象：

1. 大檔拆分時，其他模組仍直接呼叫 owner 內的 static/private utility（例如 `SECReportExtractor._statement_matches`）。

影響：

1. 拆分後若未同步遷移呼叫點或保留 wrapper，會在 runtime 觸發 `AttributeError`。
2. 這類錯誤通常在整合測試才暴露，修復成本高於編譯期錯誤。

避免方式：

1. 拆分前先盤點跨模組 utility 呼叫關係（`rg` 檢查 `Class._method` 形式）。
2. 若同批不打算改所有 call sites，入口 owner 保留 thin wrapper（僅 delegate，不承載新邏輯）。
3. 以 targeted regression 測試覆蓋該 utility 的實際呼叫鏈（例如 resolver ranking path）。

## 2.12 Strict/Relaxed 分支重複（Fallback Branch Duplication）

現象：

1. 同一 builder 內同時維護 strict 與 relaxed 版本的大段 extraction 程式碼（欄位清單、label、組裝流程高度重複）。

影響：

1. 任一欄位調整需改兩份，容易產生 strict/relaxed 行為漂移。
2. fallback 邏輯與業務組裝混在同一檔案，降低可讀性與測試聚焦度。

避免方式：

1. 將 extraction 主流程抽成單一 owner service（一次定義欄位抽取與組裝）。
2. strict/relaxed 僅透過 config transformation（例如 `relax_statement_filters`）切換，不複製流程碼。
3. builder 入口只保留 orchestration（strict 嘗試 -> relaxed retry -> diagnostics）。

## 2.13 Domain Policy Monolith（Assumptions 混責任）

現象：

1. 單一 `assumptions.py` 同時承載 growth blend、manual defaults、forward-signal policy 與 parsing helper。

影響：

1. policy owner 不清楚，review 難以定位變更影響範圍。
2. 同檔修改頻率過高，容易造成無關 policy 互相干擾。

避免方式：

1. 依 capability 拆成 `domain/.../policies/*_policy.py`（例如 growth/manual/forward-signal）。
2. call sites 一次遷移，避免新增長期 compatibility façade。
3. 測試按 policy 群組分層（growth tests / forward-signal tests / builder integration tests）。

## 2.14 Stateful Inference Monolith（推理生命週期與流程混檔）

現象：

1. 單一推理模組同時處理 model load/warmup/cache/concurrency、prefilter、batch inference、stats shaping。

影響：

1. 一處改動容易牽動 cache 命中率、批次策略與回退邏輯，回歸風險高。
2. 測試難以定位責任，無法針對純函式步驟做精準驗證。

避免方式：

1. 保留一個薄 orchestrator owner 管 lifecycle（載入、warmup、cache、lock、fallback 入口）。
2. 將 prefilter 規則、inference batching/cache-key/prediction、stats 組裝拆到獨立 `*_service.py` / `*_stats.py`。
3. 對拆分後 owner 套用 targeted regression（circuit-breaker、pipeline、import hygiene）。

## 2.15 Deterministic Engine Monolith（契約與演算法混檔）

現象：

1. 單一 deterministic engine 檔案同時承載 dataclass contracts、流程編排、抽樣/矩陣修復/統計細節。

影響：

1. contract 變更與演算法變更互相干擾，review 難以聚焦。
2. engine entrypoint 無法保持薄化，維護成本隨演算法複雜度快速上升。

避免方式：

1. 將 contracts 下沉到 `*_contracts.py`（config/spec/result owner 明確）。
2. engine 主檔只保留 orchestration（batch loop、early-stop、final assembly）。
3. 抽樣、PSD 修復、統計診斷分拆到獨立 owner services，並保持 targeted regression。

## 2.16 Statement Builder Mixed Concerns（XBRL catalog + extraction + derived 混檔）

現象：

1. 同一 builder 檔案同時承載 concept config catalog、來源欄位 extraction、以及 derived ratio 計算。

影響：

1. concept 變更與政策計算變更 diff 互相干擾，review 成本高。
2. 單檔修改頻率過高，容易引入無關回歸。

避免方式：

1. `*_config_service.py` 專職 concept/config bundle owner。
2. `*_component_extraction_service.py` 專職 source field extraction 與直接 computed field。
3. `*_derived_metrics_service.py` 專職 ratio/derived policy 計算。
4. builder 入口僅負責 orchestration + final assembly，不承載配置字典與公式細節。

## 2.17 Text Pipeline Processor Monolith（record 預處理與 metric 聚合混檔）

現象：

1. 同一 text pipeline 模組同時處理 record 預處理（focus/8-K/FLS/doc metadata）與 metric hit 聚合/evidence 合併。

影響：

1. FLS/預處理調整與 pattern/evidence 政策調整互相耦合，回歸風險高。
2. pipeline entrypoint 無法保持薄化，diagnostics 觀測難以定位責任來源。

避免方式：

1. `record_processor_preparation_service.py` owner record-level preparation 與 FLS 路由輸入。
2. `record_processor_metric_service.py` owner metric-level hit aggregation 與 evidence merge policy。
3. pipeline 主檔僅保留 batch orchestration + diagnostics accumulation，不承載細節規則。

## 2.18 Policy Parse+Score Monolith（payload parsing 與 scoring 決策混檔）

現象：

1. 單一 policy 檔案同時處理外部 payload parsing/validation 與權重/風險標記/scoring 決策。

影響：

1. schema 調整與政策調整互相耦合，review 與測試定位困難。
2. policy entrypoint 容易變成高密度主檔，降低可維護性。

避免方式：

1. parser owner（例如 `*_parser_service.py`）負責 schema filtering 與 typed contract 轉換。
2. scoring owner（例如 `*_scoring_service.py`）負責 acceptance/weight/risk-tag 決策。
3. policy entrypoint 只保留 public exports 與薄 orchestrator 角色。

## 2.19 Use-Case Mixed Flow Monolith（context 載入、計算執行、完成欄位混檔）

現象：

1. 單一 `run_*` use-case 同時處理 state/artifact 解析、calculator 執行、completion telemetry 欄位組裝。

影響：

1. 一次變更容易跨越多種責任，review 與回歸定位成本高。
2. use-case 主檔難以維持 orchestration-only 角色，造成可讀性下降。

避免方式：

1. context service 拆出 runtime/state/artifact resolution 與前置驗證。
2. execution service 拆出 param build + calculator invocation + result parsing。
3. completion-fields service 拆出 logging/telemetry 欄位組裝。
4. `run_*` 主檔只保留 node-level branching、error mapping、state update routing。

## 2.20 Catch-All Helpers Monolith（`pipeline_helpers.py` 式雜燴模組）

現象：

1. 單一 `helpers.py` 同時承載 scalar coercion、text normalization、evidence snippet、SEC URL 建構、filing 讀取 fallback 等跨能力邏輯。

影響：

1. 無法從模組名推斷責任 owner，review 與故障定位需要掃整檔。
2. 任一子能力變更都會放大 diff 範圍，增加非關聯回歸風險。

避免方式：

1. 拆為 capability owners（例如 `pipeline_scalar_service.py`、`pipeline_evidence_service.py`、`pipeline_filing_metadata_service.py`、`pipeline_filing_access_service.py`、`pipeline_text_normalization_service.py`）。
2. call sites 直接依賴語義 owner，不保留長期 catch-all re-export 模組。
3. 入口 orchestration 檔案僅 import 所需 owner，不再依賴 `helpers` 聚合桶。

## 2.21 Model Selection Monolith（catalog/signals/scoring/reasoning 混檔）

現象：

1. 同一 `model_selection.py` 同時承載契約 dataclass、模型 catalog、signals 抽取、spec scoring、reasoning 文本組裝。

影響：

1. 調整某一 scoring 規則時，會連帶增加 catalog 或 reasoning diff 噪音。
2. 測試難以分層，容易只驗整體流程而忽略 scoring/signal owner 的精準覆蓋。

避免方式：

1. `model_selection_contracts.py`：只放 dataclass/type alias/scoring weights。
2. `model_selection_spec_catalog.py`：只放 model specs/catalog。
3. `model_selection_signal_service.py`：只放 signals extraction。
4. `model_selection_scoring_service.py`：只放 spec scoring policy。
5. `model_selection_reasoning_service.py`：只放 reasoning 文本組裝。
6. `model_selection.py` 僅保留 thin entrypoint + logging + owner delegation。

## 2.22 Backtest Runner Monolith（dataset/runtime/drift/report 混檔）

現象：

1. 單一 `backtest.py` 同時處理 dataset/baseline 讀取、runtime case execution、drift comparison、report/baseline payload 輸出。

影響：

1. 調整 drift tolerance 或 runtime metric extraction 時，容易牽動不相關的 I/O/report 邏輯。
2. 測試粒度被迫過粗，難以分離「執行錯誤」與「比較錯誤」來源。

避免方式：

1. `backtest_contracts.py`：契約 dataclass owner。
2. `backtest_io_service.py`：dataset/baseline 讀取與型別 coercion owner。
3. `backtest_runtime_service.py`：case execution + metric extraction owner。
4. `backtest_drift_service.py`：baseline comparison + drift detection owner。
5. `backtest_report_service.py`：report/baseline payload 組裝 owner。
6. `backtest.py` 保留 thin API entrypoint，僅 re-export 對外函式。

## 2.23 DCF Variant Calculator Monolith（validation/distribution/result-assembly 混檔）

現象：

1. 單一 `dcf_variant_calculator.py` 同時承載 projection validation、Monte Carlo distribution 設定與 batch evaluator、result detail 組裝。

影響：

1. Monte Carlo policy 調整與結果欄位調整互相耦合，review 與回歸定位成本高。
2. dcf growth/standard 共用入口難以維持薄化，主檔責任過重。

避免方式：

1. `dcf_variant_contracts.py`：shared protocol/policy 契約 owner。
2. `dcf_variant_validation_service.py`：projection validation 與 converged-series coercion owner。
3. `dcf_variant_distribution_service.py`：Monte Carlo distribution + batch evaluator owner。
4. `dcf_variant_result_service.py`：raw inputs/static inputs/detail fields 組裝 owner。
5. `dcf_variant_calculator.py`：僅保留 orchestration entrypoint 與錯誤映射。

## 2.24 Implementation Wrapper Residue（`utils.py` / class static utility wrappers）

現象：

1. canonical entrypoint 仍依賴 `utils.py` 這類歷史聚合模組作為中介。
2. service utility 函式被包在 class static methods 上提供外部呼叫（例如 `Class._period_sort_key`）。

影響：

1. implementation owner 邊界不清楚，容易形成長期 compatibility residue。
2. 呼叫端與 class 形成不必要耦合，阻礙後續 capability owner 拆分。

避免方式：

1. 將 `utils.py` 遷移到語義化 owner module（例如 `financial_payload_service.py`），並原子遷移 call sites 後刪除舊檔。
2. resolver/consumer 直接依賴 capability service（例如 `period_sort_key(...)`、`statement_matches(...)`），不再依賴 class static wrapper。
3. class 僅保留該 class 真正擁有的行為，不作為 utility 轉發容器。

## 2.25 Capability Package Split Residue（`x_builder*.py` + `x_builders/*` 並存）

現象：

1. 同一 bounded capability 同時分散在 root-prefixed modules（例如 `param_builder_*.py`）與 sibling package（例如 `param_builders/*`）。
2. 外部 call sites 難以判斷 canonical owner，導致新增功能時容易放錯層。

影響：

1. discoverability 下降，review/debug 需要跨兩套命名規則掃描。
2. 邊界語義不清，後續跨 agent 套用時容易複製結構反模式。

避免方式：

1. 收斂到單一 capability package（例如 `domain/.../parameterization/*`）。
2. package 內再分 `orchestration/shared/model_builders` 等語義子模組，不在 package 外保留同族前綴檔案。
3. call sites 只依賴 canonical package 路徑，完成遷移後刪除舊路徑，不保留長期 compatibility 別名。

## 2.26 Inner Package Naming Stutter（canonical package 內重複能力前綴）

現象：

1. 已收斂到 canonical capability package 後，內部檔名仍維持重複能力前綴（例如 `parameterization/param_builder_*.py`）。

影響：

1. package 邊界已清楚但檔名仍冗長，降低可掃描性。
2. 新增模組時易把 capability token 當作命名模板，導致長期命名噪音。

避免方式：

1. package 內檔名改為 owner-semantic（例如 `contracts.py`、`types.py`、`orchestrator.py`、`registry_service.py`）。
2. capability token 只保留在 package path，不重複出現在每個 module filename。
3. 搬遷後原子更新 call sites，不保留 compatibility alias/shim。

## 2.27 Model Builder Flat-Package Saturation（model builders 單層平鋪）

現象：

1. `model_builders` 在單層目錄平鋪過多模型檔案與共用服務，模型邊界與共用邊界混在同一層。

影響：

1. 變更影響面不易判斷，review 時需跨大量同層檔案掃描。
2. 新增模型時容易複製 shared 邏輯到 model 檔案，造成重複。

避免方式：

1. 依模型拆子 package（例如 `model_builders/bank/*`、`model_builders/saas/*`、`model_builders/reit/*`）。
2. 將跨模型重用邏輯集中到 `model_builders/shared/*`。
3. parent package 僅保留 dispatch/context/export 邊界（例如 `payload_dispatch_service.py`、`context.py`、`__init__.py`）。

## 2.28 Policy Capability Mixing in One Module（獨立 policy 能力混檔）

現象：

1. 同一 `policy_service.py` 同時承載 forward-signal parsing/adjustment 流程與 data-freshness/time-alignment guard 邏輯。
2. 模組同時包含 payload normalization、risk decision 後處理、freshness policy guard，責任跨能力混雜。

影響：

1. policy owner 邊界不清晰，review 難以隔離改動影響面。
2. 一個能力的改動容易牽動不相干能力（例如調整 forward signal policy 時誤傷 time-alignment guard）。

避免方式：

1. 依能力拆 owner service（例如 `forward_signal_parser_service.py`、`forward_signal_adjustment_service.py`、`time_alignment_guard_service.py`）。
2. `policy_service.py` 僅保留薄 entrypoint/re-export，不再承載混合實作。
3. orchestration call sites 保持穩定入口，能力邏輯在 owner service 內演進。

## 2.29 Application Wiring Leakage & Import-Time Registry Bootstrap

現象：

1. application `orchestrator/factory` 直接 import concrete infrastructure adapters（repository/provider/service）。
2. infrastructure mapping registry 在模組 import 時自動執行 `register_all_*` bootstrap。

影響：

1. application layer 邊界被 concrete 依賴污染，跨 agent 套用時容易把 wiring 與 use-case 混在同一層。
2. import-time side effect 造成啟動與測試的隱性全域狀態，降低可測試性與可預測性。

避免方式：

1. application 僅依賴 ports/contracts，concrete assembly 收斂到 composition/wiring module。
2. registry bootstrap 改為顯式或 lazy accessor（例如 `get_mapping_registry()`），不在 import 階段執行。
3. workflow nodes 依賴 wiring module 提供 runtime，而非直接從 application 模組抓 concrete singleton。

## 2.30 Generic Domain Root Modules（`models.py` / `services.py` / `rules.py`）

現象：

1. 成熟 bounded context 仍保留 generic root modules（例如 `domain/models.py`、`domain/services.py`、`domain/rules.py`）。
2. 同檔承載多能力 owner（enum/type helpers、financial math、health projection、output extraction）導致模組語義模糊。

影響：

1. discoverability 下降；新同事難以從檔名判斷能力 owner。
2. call sites 容易持續依賴 generic bucket，導致後續拆分成本上升。

避免方式：

1. 以 capability owner 命名收斂（例如 `valuation_model.py`、`financial_math_service.py`、`financial_health_service.py`、`valuation_output_service.py`）。
2. 同批原子遷移 call sites 後刪除 generic modules，不保留 compatibility shim。
3. 新增 review checklist gate，禁止在成熟 domain package 回流 generic root module 命名。

## 2.31 Flat Capability Cluster at Package Root（以 `backtest_*` 為例）

現象：

1. 同一 bounded capability 已拆為多個 owner modules（contracts/io/runtime/drift/report），但仍平鋪在 parent package root。
2. 檔名依賴 `<capability>_*` 前綴維持可辨識，形成長期路徑噪音與邊界模糊。

影響：

1. parent package 掃描成本提高，容易與其他能力（例如 registry/report_contract/parameterization）混視。
2. 後續新增能力 owner 容易繼續平鋪，放大命名 stutter 與維護負擔。

避免方式：

1. 當同一能力達到 4+ 緊耦合 owner modules，升級為 dedicated subpackage（例如 `domain/valuation/backtest/*`）。
2. 子 package 內使用語義檔名（`contracts.py`、`io_service.py`、`runtime_service.py`、`drift_service.py`、`report_service.py`）。
3. 若需要遷移穩定性，可在 parent 保留薄入口 module；完成 call-site 遷移後移除。

## 2.32 External Parser Empty Facts（XBRL 有 filing 但 facts 空表）

現象：

1. SEC filing 與 instance 檔存在，HTTP 200 正常，但 `facts.to_dataframe()` 回傳空表（`row_count=0` 或缺必要欄位）。
2. 系統若直接降級年份，會誤判為「該年度無財報」。

影響：

1. 財報年份 coverage 被動縮水（例如 2025/2024/2022，缺 2023）。
2. 分析結果雖可完成，但資料完整性與可解釋性下降。

避免方式：

1. 在 infrastructure adapter 層對 facts dataframe 做 schema + row-count 驗證（至少 `concept/value/period_key` 且 `row_count>0`）。
2. primary parser 回空時，於同一 filing 啟動「forced instance fallback」解析（優先 instance datafile，再套用同 filing linkbase）。
3. 僅當同 filing fallback 仍失敗才進入跨年份 fallback。
4. 對 fallback 全鏈路打結構化事件（started/candidate_failed/candidate_invalid/succeeded），避免只記錄模糊 exception 字串。

## 2.33 External SDK Large-Payload Timeout（檔案存在但讀取超時）

現象：

1. 同一 SEC filing URL 可用（HTTP 200），但在某些 run 會出現 `ReadTimeout`。
2. 失敗通常集中在大型 `.txt` filing 內容讀取階段，而非 ticker/filing 查找階段。

影響：

1. 年度報表被跳過（例如 2023 timeout 後回退到 2022），造成 coverage 降低。
2. 容易被誤判為「頻率限制」或「資料不存在」。

避免方式：

1. 將 external SDK（例如 edgartools）的 HTTP timeout 設定集中在 infrastructure runtime config owner（不得散落在各 adapter 呼叫點）。
2. timeout 預設值需對大型 payload 具容忍度（例如 45 秒），並允許 env 覆蓋，且設定最小下限防止誤設過小值。
3. retry/backoff 與 timeout 需協同設計：先確保單次請求有足夠 read window，再使用 retry 吸收偶發抖動。
4. 觀測上區分 `ReadTimeout` 與 `429/rate-limit`，避免把網路抖動誤判為限流問題。

## 2.34 LLM Transport Transient Failures（incomplete chunked read / peer closed）

現象：

1. LLM API 已回應 `HTTP 200`，但在讀取 response body 時發生 `incomplete chunked read` 或 `peer closed connection`。
2. 若節點直接捕捉例外並降級，工作流會把可恢復的傳輸故障誤當成業務失敗。

影響：

1. Debate/analysis 類長回應節點容易在中後段失敗，造成最終 verdict 缺失。
2. 圖層 retry policy 無法生效（例外被節點內部吞掉）。

避免方式：

1. 在 application owner 層引入小型、可觀測的 LLM retry service，針對 transport transient errors 先重試再降級。
2. retry service 必須是單一 owner（policy + retryable 判定 + backoff），不得在各 node 分散重複實作。
3. retry 僅覆蓋 network/transient 類錯誤；schema/contract 錯誤應立即失敗，避免掩蓋真正缺陷。
4. retry 事件要打結構化 log（operation/attempt/retry_in_seconds/exception）。

## 3. 後續重構的防呆規則

硬規則（Hard Rules）：

1. canonical contract 不允許 hidden fallback。
2. concrete class 不允許 `*Port` 命名。
3. compatibility 分支沒有移除計畫就不得引入。
4. 不得新增 legacy package import。
5. 不得跨 layer 直接繞過 ports/contracts。
6. interface parser 對 canonical 欄位不得做 source label 正規化（應直接拒絕，包含 `industry_type` 與 `extension_type`）。
7. 不得以 `assumptions`/log 等敘述字串做流程分支判斷；控制流必須依賴 typed decision 欄位。
8. 同一 bounded context 的 domain model contract module 命名必須一致（預設 `contracts.py`）。
9. 同一模型家族不得長期維持 copy-paste calculator；需收斂為 shared calculator owner + thin variant wrappers。
10. 同一 bounded context 內不得重複實作 calculator runtime support 函式；必須集中到單一 owner module。
11. 不得長期保留 `models/*/calculator.py` 作為 compatibility 轉發層；成熟階段應刪除並直接依賴 calculators canonical owner。
12. 大型 mapping registry catalog 不得持續維持單檔壅塞；必須按語義 owner 拆分，entrypoint module 僅保留註冊編排。
13. 模組拆分若涉及跨模組 utility 調用，必須「同批遷移 call sites」或「保留薄 wrapper」二選一，不可直接移除入口符號。
14. 同一能力的 strict/relaxed fallback 分支不得長期維持重複流程碼；需收斂為單一 extraction owner + config transformation。
15. domain policy 不得維持混責任 monolith（如單檔 assumptions 匯集多能力）；需拆為 capability-based policy owners 並原子遷移 call sites。
16. stateful inference owner 不得混放 lifecycle/cache 與 pure prefilter/batching/stats 流程；需拆分為薄 orchestrator + 功能 owner services。
17. 大型 deterministic engine 不得混放 contracts + orchestration + low-level math；需拆為 `*_contracts.py` + thin engine + domain services。
18. financial statement builder 不得混放 concept catalog + extraction + derived metrics；需拆為 config/component/derived owners + thin builder entrypoint。
19. text-signal pipeline processor 不得混放 record preparation + metric aggregation/evidence policy；需拆為 preparation owner + metric owner + thin pipeline entrypoint。
20. policy 模組不得混放 payload parsing + scoring/risk 決策；需拆為 parser owner + scoring owner + thin policy entrypoint。
21. application `run_*` use-case 不得混放 context loading + calculator execution + completion-field shaping；需拆為 context/execution/completion owners + thin use-case entrypoint。
22. 不得引入 catch-all `helpers.py` 聚合模組承載跨能力邏輯；必須以 capability owner module 直接承載並由 call sites 直接依賴。
23. domain model-selection 不得混放 contracts/catalog/signals/scoring/reasoning；需拆為 capability owners + thin `model_selection.py` entrypoint。
24. domain valuation backtest 不得混放 dataset I/O、runtime execution、drift comparison、report shaping；需拆為 capability owners + thin `backtest.py` entrypoint。
25. DCF variant calculator 不得混放 validation、Monte Carlo distribution、result assembly；需拆為 capability owners + thin `dcf_variant_calculator.py` entrypoint。
26. 不得保留 implementation compatibility residue（`utils.py` 聚合桶或 class static utility wrappers）；需改為 capability service 直接依賴並移除舊入口。
27. 同一 bounded capability 不得長期分散於 root-prefixed modules 與 sibling package（例如 `x_builder*.py` + `x_builders/*`）；需收斂為單一 canonical capability package 並完成 call sites 原子遷移。
28. canonical capability package 內不得維持 module-name stutter（重複能力 token，例如 `parameterization/param_builder_*.py`）；需改為 package-scoped semantic owner module names（`contracts.py`、`orchestrator.py`、`*_service.py`）。
29. model-builder 類型能力包不得長期維持單層平鋪；需收斂為 `per-model subpackages + shared subpackage + parent dispatch/context` 形態，並完成 call sites 原子遷移。
30. policy-oriented capability packages 不得在單一模組混放獨立 policy 能力（例如 forward-signal adjustment 與 time-alignment guard）；需拆為 capability owner services，並保持 `policy_service.py` 薄入口。
31. application 層不得直接 import concrete infrastructure adapters；concrete wiring 必須放在 composition/wiring module，application 僅依賴 ports/contracts。
32. infrastructure registry/catalog 不得在 import-time 自動 bootstrap 註冊；必須改為顯式或 lazy accessor 初始化。
33. 成熟 domain bounded context 不得保留 generic root modules（`models.py` / `services.py` / `rules.py`）；必須收斂為語義化 capability owner 模組並原子遷移 call sites。
34. 同一成熟能力不得長期維持 flat `<capability>_*` 檔案群平鋪於 package root；達到 4+ owner modules 時必須升級為 dedicated subpackage，並收斂為 capability-internal semantic filenames。
35. external SDK HTTP runtime config（timeout/verify/proxy）不得散落在多個 adapter 呼叫點；必須集中於單一 infrastructure config/service owner，並提供安全預設值與可控覆蓋。
36. LLM node 若在內部捕捉例外並回傳降級結果，必須先經過單一 owner 的 transient retry flow；不得直接把 transport 抖動映射為業務錯誤。

預設慣例（Default Conventions）：

1. 一次只做小切片。
2. 每切片都跑同一套三段驗證。
3. 每切片都回填 tracker 並做對齊檢查。
4. 文檔 owner 與實際代碼 owner 同步更新。

## 4. 輕量跨 Agent 重構流程

1. 盤點當前 owner 與 legacy 路徑。
2. 定義 canonical owner 與 layer 邊界。
3. 以小切片改造，保留可回退能力。
4. 每切片固定跑 `lint + targeted + expanded`。
5. tracker 記錄結果、對齊與偏離原因。
6. 完成遷移後立即移除過渡相容層。

## 5. 這種做法有效嗎？會不會增加認知負荷？

結論：

1. 有效，但前提是「輕量且可執行」。
2. 若寫成抽象大文檔、沒有對應檢查，會增加認知負荷。

如何避免過重：

1. 保持高訊號短規則（1 頁可掃完）。
2. 能程式化的規則盡量轉為測試或 lint guard。
3. 優先 checklist，而不是長篇敘述。
4. 文件作為決策輔助，不作為額外流程負擔。

實務判準：

1. 若 reviewer 5 到 10 分鐘內可套用 checklist，則降低負荷。
2. 若每個 PR 都需要長時間解讀文件，代表文件已過重，應立即精簡。

## 6. 對其他 Agent 的套用建議

1. 先套同一份 owner/boundary checklist。
2. 早期就加 import hygiene guard，防 legacy 回流。
3. 採用同一遷移序列：
   `owner 明確化 -> fallback 邊界化 -> fallback 移除`。
4. 使用同格式 tracker，固定記錄對齊檢查與偏離原因。

## 7. 強制機制：每批 Refactor 的 Lessons Review Gate

為了避免經驗文檔過期，後續 fundamental 與其他 agent refactor 採用以下強制機制：

1. 每一批 refactor 完成後，必須 review 本文檔一次。
2. 每一批都必須在 execution tracker 留下 `Lessons Review` 紀錄，格式為：
   `updated` 或 `no_update`，且要附原因。
3. 若發現新反模式、新風險或新 guardrail，必須在同一批更新本文檔，不可延後。
4. 若該批沒有新發現，也必須寫明 `no_update` 與判定理由，避免默認跳過。
5. PR/交付關卡：沒有 `Lessons Review` 紀錄的批次，視為未完成。

建議記錄格式（可直接複製到 tracker）：

1. `Lessons Review: updated`
   - `新增/修正文檔章節：...`
   - `原因：本批新增了可複用的問題模式或防呆策略`
2. `Lessons Review: no_update`
   - `原因：本批僅為命名/搬移/型別收斂，未引入新類型問題`
