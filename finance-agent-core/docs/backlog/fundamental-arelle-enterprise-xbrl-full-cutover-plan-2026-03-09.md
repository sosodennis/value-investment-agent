# Fundamental Arelle-First Enterprise XBRL Full-Cutover Plan (2026-03-09)

## Requirement Breakdown

1. Objective
- 一次性把 SEC/XBRL 解析能力升級為企業級，長期由 Arelle 主導。
- 解決 AMZN 類「找不到 XBRL 對應 tags」問題，特別是 extension concept 對標準概念映射。
- 在不依賴付費授權的前提下（預算偏 `0 license + engineering`），建立可持續的高覆蓋與高可審計解析管線。

2. Success Criteria
- `tax_rate` / `income_before_tax` 類關鍵估值輸入缺失率顯著下降並達到可接受上限（由 cohort gate 固化）。
- `financial_reports` 每個關鍵字段均有可追溯 provenance（XBRL/Computed/Manual）與解析路徑診斷。
- 新管線在全量切換後可穩定支援回放與 release gate，不依賴舊解析路徑。

3. Constraints
- 直接全量切換，不做 rollback path。
- 不需要兼容舊數據契約。
- 長期主路徑固定 Arelle，不引入高額授權引擎。
- 必須納入 performance 設計（filing package cache + concept 映射 cache）。

4. Out of Scope
- 不引入 Bloomberg/FactSet/LSEG 類高授權資料供應商。
- 不做前端交互改版。

## Technical Objectives and Strategy

1. Arelle-first 解析主路徑
- 以 Arelle 讀取 EX-101.SCH/LAB/PRE/CAL/DEF + instance，建立 taxonomy-aware concept graph。
- 從「固定 tag regex」升級為「標準概念 + extension anchoring + linkbase 關係」多訊號解析。

2. Extension-to-Canonical 映射層
- 新增 extension anchor 服務，把 issuer extension concept 映射到 canonical field key（例如 `income_before_tax`）。
- 映射優先序：
  - issuer anchor rule
  - industry anchor rule
  - global canonical rule
- 無法確定映射時，輸出 machine-readable unresolved reason，禁止靜默命中。

3. DQC/EFM 企業級品質閘門
- 導入 DQC/EFM 分級策略（建議）：
  - `Block`：EFM 致命錯誤、DQC 對估值關鍵字段的重大錯誤（符號/尺度/context mismatch/計算關係破壞）。
  - `Warn`：非關鍵欄位或低影響一致性告警。
- 估值阻斷採「關鍵字段 + 關鍵規則」組合條件，不以全部 DQC 告警一刀切阻斷。

4. Performance-first 設計
- `L1` 進程內快取：concept resolution 與 field mapping 結果。
- `L2` Redis 快取：`filing accession + taxonomy version + field_key` 級別結果。
- `L3` artifact 持久化快取：解析後 canonical financial payload 與 diagnostics。
- 批次解析與預熱：
  - 對熱門 ticker 預熱最近 5 年 filings。
  - 對 cohort release tickers 執行 nightly cache warm-up。

## Involved Files

1. Application wiring and provider contracts
- `finance-agent-core/src/agents/fundamental/application/ports.py`
- `finance-agent-core/src/agents/fundamental/application/factory.py`
- `finance-agent-core/src/agents/fundamental/wiring.py`

2. SEC/XBRL infrastructure
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/provider.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/financial_payload_service.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/extractor.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/mapping.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/base_model_field_extraction_service.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/mappings/base_income_fields.py`

3. Valuation dependency interfaces
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/saas/saas.py`
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_flow.py`

4. New modules (planned)
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/engine_contracts.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/arelle_engine.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/provider_router.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/anchor/extension_anchor_service.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/quality/dqc_efm_gate_service.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/cache/filing_cache_service.py`

## Detailed Per-File Plan

1. `ports.py` / `factory.py` / `wiring.py`
- 升級 payload provider contract，納入 `financial_reports + diagnostics + quality_gates`。
- 以 Arelle provider 為唯一生產路徑注入。

2. `provider.py` / `financial_payload_service.py`
- 新增標準化 pipeline：
  - fetch filing package
  - parse taxonomy and facts
  - resolve extension anchors
  - run DQC/EFM gates
  - emit canonical payload + diagnostics

3. `extractor.py`
- 保留現有搜尋工具函式可重用部分，但核心 fact extraction 改走 Arelle graph 查詢。
- 實作 filing package 本地/Redis 雙層快取。

4. `mapping.py` / `base_model_field_extraction_service.py` / `base_income_fields.py`
- 從 tag-first 改為 canonical-concept-first。
- 增加 candidate ranking features：
  - presentation role proximity
  - calculation relationship consistency
  - label similarity
  - anchor confidence score

5. `saas.py` / `run_valuation_flow.py`
- 同步調整「缺失輸入」政策與品質閘門對齊，避免出現可算但被 missing-metric 阻斷的策略衝突。
- 對 DQC/EFM `Block` 等級錯誤直接阻斷估值，並回傳明確 error code。

## Risk/Dependency Assessment

1. Functional risk
- 全量切換且不保留舊路徑，早期缺陷會直接影響估值成功率。
- 緩解：先完成 golden cohort shadow-run 驗證，再在同一版本切主路徑。

2. Performance risk
- Arelle 在大規模解析下延遲上升。
- 緩解：三層快取、預熱策略、批次並行控制、解析結果 artifact 化。

3. Quality risk
- DQC/EFM 規則如果不分級，可能造成過度阻斷。
- 緩解：嚴格分級矩陣與關鍵字段清單。

4. Dependency
- 依賴 Arelle 執行穩定性、Redis 可用性、artifact 存儲可用性。

## Validation and Rollout Gates

1. Gate 1: Parsing Contract
- canonical payload schema 與 provenance contract 全綠。

2. Gate 2: Golden Cohort Accuracy
- `AMZN/AAPL/MSFT/GOOG/NVDA/JPM` 關鍵字段命中率與缺失率達標。

3. Gate 3: Quality Gate
- DQC/EFM 分級執行正確，`Block` 與 `Warn` 分流與 error code 對齊。

4. Gate 4: Performance Gate
- 熱快取與冷快取延遲統計達標（P50/P90/P99 門檻固化到 release gate）。

5. Gate 5: Release Gate Integration
- replay/backtest/release checklist 全部改用新解析契約，無舊路徑依賴。

## Assumptions/Open Questions

1. 已確認：Arelle 為長期主路徑，且不考慮回退舊路徑。
2. 已確認：不要求舊數據兼容。
3. 建議確認：DQC/EFM `Block` 的關鍵字段範圍第一版是否先限於估值必需欄位（revenue, operating_income, pre-tax income, tax expense, debt, cash, shares）。
4. 建議確認：performance 目標值（例如 cold P90、warm P90）是否採 `cohort-based` 還是 `all-run global` 指標。

## Implementation Tickets (S1-S8)

### FB-035-S1 Contract Cutover and Wiring Baseline
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 完成新解析契約切換，讓 `financial_reports + diagnostics + quality_gates` 成為唯一上游輸入形狀。
- Scope:
  - `finance-agent-core/src/agents/fundamental/application/ports.py`
  - `finance-agent-core/src/agents/fundamental/application/factory.py`
  - `finance-agent-core/src/agents/fundamental/wiring.py`
  - `finance-agent-core/src/agents/fundamental/interface/parsers.py`
- Deliverables:
  - 新 provider contract 生效。
  - 舊 payload shape 移除，不保留兼容分支。
- Exit:
  - fundamental workflow smoke run 可正常進入 valuation。
  - contract/parser 單元測試全綠。
- Dependency: none.
- Estimate: 1.5-2.0d.

### FB-035-S2 Arelle Engine Integration (Facts + Linkbases)
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 建立 Arelle 解析引擎，完整讀取 EX-101 套件並輸出標準化 fact rows。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/engine_contracts.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/arelle_engine.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/extractor.py`
- Deliverables:
  - Arelle engine 對單一 filing 輸出 `facts + presentation + calculation + definition + labels` 統一結構。
  - edgartools 僅保留 filing metadata/fetch 輔助，不再承擔核心語義解析。
- Exit:
  - AMZN 最新 10-K 能完成 Arelle 解析，不報結構錯誤。
  - 基礎解析測試與 fixture 測試全綠。
- Dependency: `FB-035-S1`.
- Estimate: 2.5-3.0d.

### FB-035-S3 Performance Foundation (L1/L2/L3 Cache)
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 上線企業級快取架構，控制 Arelle 全量切換後延遲。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/cache/filing_cache_service.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/financial_payload_service.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/provider.py`
- Deliverables:
  - `L1` process cache、`L2` Redis cache、`L3` artifact cache。
  - cache key 規範：`cik/accession/taxonomy_version/field_key`。
  - cold/warm 命中率與延遲診斷欄位。
- Exit:
  - warm path P90 顯著優於 cold path（門檻寫入 release gate 設定）。
  - cache 命中率可在 artifacts/logs 中審計。
- Dependency: `FB-035-S2`.
- Estimate: 2.0-2.5d.

### FB-035-S4 Extension Anchor Resolver and Canonical Mapping
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 建立 extension concept 到 canonical field 的企業級映射與置信度評分。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/anchor/extension_anchor_service.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/mapping.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/mappings/base_income_fields.py`
- Deliverables:
  - issuer/industry/global 三層 anchor rule registry。
  - unresolved reason code（禁止 silent fallback）。
- Exit:
  - AMZN `income_before_tax` 命中率改善，未命中時產出 machine-readable 原因。
  - mapping regression 測試（AMZN/AAPL/MSFT/GOOG/NVDA/JPM）全綠。
- Dependency: `FB-035-S2`.
- Estimate: 2.5-3.0d.

### FB-035-S5 DQC/EFM Severity Gate Enforcement
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 落地 `Block/Warn` 分級閘門，將關鍵質量錯誤納入估值阻斷條件。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/quality/dqc_efm_gate_service.py`
  - `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_flow.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/financial_payload_service.py`
- Deliverables:
  - DQC/EFM 錯誤分級映射與 critical-field policy（第一版）。
  - `FUNDAMENTAL_XBRL_QUALITY_BLOCKED` 類型 error contract（或同級明確碼）。
- Exit:
  - critical 錯誤會阻斷估值；non-critical 只告警且可繼續。
  - quality gate 單元測試與契約測試全綠。
- Dependency: `FB-035-S2`, `FB-035-S4`.
- Estimate: 2.0-2.5d.

### FB-035-S6 Field Extraction Refactor (Concept-First Ranking)
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 將現有 field extraction 從 tag-first 升級為 concept-first + 多訊號排序。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/base_model_field_extraction_service.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/base_model_mapping_resolver_service.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/field_resolution_utils.py`
- Deliverables:
  - ranking features: presentation proximity / calculation consistency / label similarity / anchor confidence。
  - provenance 補充 `resolution_stage` 與 `confidence`。
- Exit:
  - 核心字段缺失率達標並可審計原因。
  - extraction regression 測試與 replay case 全綠。
- Dependency: `FB-035-S4`.
- Estimate: 2.5-3.0d.

### FB-035-S7 Valuation Policy Alignment with New Quality Contract
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 對齊 missing-input 政策與 quality gate，消除「可算但被缺失策略終止」衝突。
- Scope:
  - `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/saas/saas.py`
  - `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_flow.py`
  - `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/shared/missing_metrics_service.py`
- Deliverables:
  - 缺失策略與 `Block/Warn` gate 統一。
  - assumptions/metadata 明確輸出 fallback 與 gate decision。
- Exit:
  - AMZN case 不再出現策略自相矛盾錯誤。
  - valuation regression（AAPL/MSFT/GOOG/NVDA/AMZN）全綠。
- Dependency: `FB-035-S5`, `FB-035-S6`.
- Estimate: 1.5-2.0d.

### FB-035-S8 Release Gate, Performance Gate, and Operational Hardening
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 將新解析契約、品質分級與性能門檻接入 release/backtest/replay 的最終治理路徑。
- Scope:
  - `finance-agent-core/scripts/replay_fundamental_valuation.py`
  - `finance-agent-core/scripts/run_fundamental_backtest.py`
  - `finance-agent-core/scripts/run_fundamental_release_gate.sh`
  - `finance-agent-core/docs/fundamental_backtest_runbook.md`
- Deliverables:
  - release gate 新增 quality + performance blocker。
  - cohort 報告新增 `quality_block_rate`、`cache_hit_rate`、`cold/warm latency`。
  - 運維 runbook 更新為 Arelle-only 流程。
- Exit:
  - `AMZN/AAPL/MSFT/GOOG/NVDA/JPM` cohort release gate pass。
  - 全鏈路 artifact 可重放並可審計。
- Evidence (2026-03-10):
  - 6 檔 cohort config（`min_cases=6`, `min_unique_tickers=6`）實跑通過：
    - `finance-agent-core/reports/fundamental_live_replay_cohort_run_s8_6tickers_v2.json`
    - `finance-agent-core/reports/fundamental_replay_manifest_live_s8_6tickers_v2.json`
    - `finance-agent-core/reports/fundamental_replay_checks_report_live_s8_6tickers_v2.json`
    - `finance-agent-core/reports/fundamental_replay_cohort_gate_s8_6tickers_v2.json`
  - manifest / gate 均確認 `AAPL, AMZN, GOOG, JPM, MSFT, NVDA` 六檔、`issues=[]`、`gate_passed=true`。
- Dependency: `FB-035-S1` to `FB-035-S7`.
- Estimate: 2.0-2.5d.

## Arelle-Only Hard Cutover Addendum (2026-03-10)

### Requirement Breakdown

1. Objective
- 將目前「Arelle 優先 + legacy parser fallback」改為「Arelle-only」強制路徑，確保生產解析與治理策略一致。

2. Success Criteria
- `sec_xbrl/extractor` 不再引用 legacy `edgar.xbrl.xbrl.XBRL` 解析路徑。
- Arelle runtime 缺失、bundle 缺失、候選解析失敗時，輸出明確 machine-readable error，並終止該 filing 解析，不自動降級 legacy。
- 既有 S2/S3/S5/S8 契約與 release-gate 測試保持綠燈。

3. Constraints
- 不新增 rollback path。
- 不保留 legacy compatibility branch。
- 變更需可由現有 release/replay gates 直接審計。

4. Out of Scope
- 不改動 valuation model policy（僅影響 XBRL 提取入口）。
- 不引入雙引擎路由策略（保持單一路徑）。

### Technical Objectives and Strategy

1. Runtime Gate Hardening
- 於 extractor 層面把 Arelle 視為必要依賴，將 unavailable/parse/bundle 問題轉為 fail-fast 路徑。

2. Fallback Removal
- 移除 `_build_dataframe_from_filing_attachments` 中 legacy parser 分支與相關 linkbase 套用函式，保留 Arelle bundle + candidate 驗證。

3. Dependency Explicitness
- 在專案依賴契約中明確宣告 Arelle runtime，避免「代碼已切換但環境未安裝」的灰色狀態。

### Involved Files

1. `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/extractor.py`
2. `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/arelle_engine.py`
3. `finance-agent-core/tests/test_sec_xbrl_arelle_engine.py`
4. `finance-agent-core/pyproject.toml`
5. `finance-agent-core/docs/backlog/fundamental-master-backlog.md`

### Detailed Per-File Plan

1. `extractor.py`
- 移除 legacy parser import 與 fallback execution。
- 將 fallback function 語義改為 Arelle candidate resolver；當全部 candidate 無效時回傳 `None`，由上層既有 schema gate 統一報錯。

2. `arelle_engine.py`
- 保持現有 `ArelleEngineUnavailableError` / `ArelleEngineParseError` 契約，作為 extractor fail-fast 分流基礎。

3. `test_sec_xbrl_arelle_engine.py`
- 移除「Arelle unavailable 時回退 legacy」測試。
- 新增「Arelle unavailable 時不回退且回傳不可用」測試，確保硬切不回歸。

4. `pyproject.toml`
- 宣告 Arelle runtime 依賴，與 Arelle-only 目標對齊。

### Risk/Dependency Assessment

1. Runtime Risk
- 若部署環境未安裝 Arelle，financial health 會 fail-fast。
- 緩解：依賴契約宣告 + CI/部署前 health check。

2. Contract Risk
- 既有依賴 fallback 的測試或操作劇本可能失效。
- 緩解：同步更新測試與 backlog/runbook 證據，保持 error contract 可觀測。

### Validation and Rollout Gates

1. Unit/Contract Gates
- `tests/test_sec_xbrl_arelle_engine.py`
- `tests/test_sec_xbrl_financial_payload_service.py`
- `tests/test_fundamental_interface_parsers.py`

2. Governance Gates
- `tests/test_run_fundamental_live_replay_cohort_gate_script.py`
- `tests/test_fundamental_release_gate_script.py`

3. Lint Gate
- `ruff check` 針對改動檔案全綠。

### Assumptions/Open Questions

1. 已確認：接受 Arelle runtime 缺失時直接 fail-fast（不再自動降級）。
2. 假設：部署與 CI 會按依賴契約安裝 Arelle runtime。

### FB-035-S9 Arelle-Only Runtime Enforcement (No Legacy Parser Fallback)
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 將 SEC/XBRL 解析入口升級為 Arelle-only，移除 legacy parser fallback。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/extractor.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/arelle_engine.py`
  - `finance-agent-core/tests/test_sec_xbrl_arelle_engine.py`
  - `finance-agent-core/pyproject.toml`
- Deliverables:
  - fallback path 移除並以可審計 error contract fail-fast。
  - 測試覆蓋 unavailable/invalid candidate 的非降級行為。
  - 依賴契約顯式聲明 Arelle runtime。
- Exit:
  - `extractor.py` 不再調用 legacy parser。
  - 目標測試組合與 ruff 全綠。
- Evidence (2026-03-10):
  - `extractor.py` 已移除 legacy parser 路徑（不再 import/調用 `edgar.xbrl.xbrl.XBRL`）。
  - `pyproject.toml` 已顯式加入 `arelle-release` 依賴，且環境驗證 `ARELLE_INSTALLED=True`。
  - 驗證結果：
    - `ruff check`: `extractor.py`, `test_sec_xbrl_arelle_engine.py`, `pyproject.toml` 全綠。
    - `pytest`:
      - `tests/test_sec_xbrl_arelle_engine.py` -> `4 passed`
      - `tests/test_sec_xbrl_arelle_engine.py` + `tests/test_sec_xbrl_financial_payload_service.py` + `tests/test_fundamental_interface_parsers.py` + `tests/test_run_fundamental_live_replay_cohort_gate_script.py` + `tests/test_fundamental_release_gate_script.py` -> `35 passed`
- Dependency: `FB-035-S1` to `FB-035-S8`.
- Estimate: 0.5-1.0d.

## Arelle Enterprise Validation Hardening Addendum (2026-03-10)

### Requirement Breakdown

1. Objective
- 將目前 Arelle 解析從「facts extraction 能跑」提升到「企業級可審計驗證執行」。
- 對齊官方實務：Arelle validation plugin orchestration（EFM/EDGAR/DQC）+ 版本治理 + 性能治理。

2. Success Criteria
- Arelle runtime 輸出包含結構化 validation issues（來源、嚴重度、規則碼、關鍵概念/欄位）。
- quality gate 以官方 validation 輸出為主來源，不再只依賴本地推導。
- release gate 可審計 SEC/DQC 規則版本、阻斷率、延遲與快取命中率。

3. Constraints
- 不引入舊路徑兼容分支。
- 不新增付費授權引擎。
- 保持 Arelle-only 生產路徑。

4. Out of Scope
- 不調整估值模型公式本體（只處理 XBRL 質量與提取治理層）。

### Implementation Tickets (S5-S8, Wave-2)

### FB-036-S5 Arelle Validation Runtime Contract and Metadata Baseline
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 在 Arelle engine contract 層加入企業級 validation metadata/issue 輸出骨架。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/engine_contracts.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/arelle_engine.py`
  - `finance-agent-core/tests/test_sec_xbrl_arelle_engine.py`
- Deliverables:
  - `ArelleParseResult` 擴展 `validation_issues/runtime_metadata/parse_latency_ms`。
  - metadata 至少包含 `mode/disclosure_system/plugins/packages/arelle_version/validation_enabled`。
- Exit:
  - contract + engine 測試全綠，且不引入 legacy compatibility path。
- Progress (2026-03-10):
  - 已完成 contract baseline slice：`ArelleParseResult` 新增 `validation_issues/runtime_metadata/parse_latency_ms`，並接入 extractor 成功日志欄位。
  - 已完成 baseline closure：provider contract 與 parse metadata 測試維持全綠，且無 legacy compatibility path 回引。
- Dependency: `FB-035-S9`.
- Estimate: 1.0-1.5d.

### FB-036-S6 EFM/DQC Plugin Orchestration and Issue Normalization
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 以 Arelle plugin 執行結果作為品質閘門主來源，完成 issue 標準化。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/arelle_engine.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/quality/dqc_efm_gate_service.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/financial_payload_service.py`
- Deliverables:
  - plugin execution profile（facts_only / efm_validate / efm_dqc_validate）。
  - 統一 issue schema（`code/source/severity/field_key/message/blocking`）。
- Exit:
  - EFM/DQC issue 能進入 payload diagnostics 並被 gate 消費。
- Progress (2026-03-10):
  - 已完成 engine profile + normalization baseline：Arelle runtime 支援 validation mode/profile，並將 `model_xbrl.errors` 標準化為 `validation_issues` 輸出到 `ArelleParseResult`。
  - 已完成 payload wiring baseline：extractor 將 `validation_issues` 寫入 `filing_metadata.arelle_validation_issues`，financial payload diagnostics 合併為 `dqc_efm_issues` 並供 quality gate 消費。
  - 已完成 orchestration closure：validation mode 會啟動 Arelle PluginManager/PackageManager 載入 plugins/packages（含 mode default plugins），載入失敗 fail-fast；issue schema 以 `normalize_dqc_efm_issue` 統一為 `code/source/severity/field_key/message/blocking`，並覆蓋 diagnostics + gate 消費路徑。
- Dependency: `FB-036-S5`.
- Estimate: 2.0-2.5d.

### FB-036-S7 Runtime Concurrency and Taxonomy/Package Cache Hardening
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 補齊 Arelle 運行時併發與快取治理，控制企業化驗證後延遲抬升。
- Scope:
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/providers/arelle_engine.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/cache/filing_cache_service.py`
  - `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/financial_payload_service.py`
- Deliverables:
  - Arelle runtime 串行/隔離策略（避免 thread-unsafe 競態）。
  - taxonomy/report-package 快取鍵與預熱策略。
- Exit:
  - cohort warm path latency 與 cache hit 指標可觀測且達門檻。
- Progress (2026-03-10):
  - 已完成 runtime isolation baseline：Arelle runtime 新增 `FUNDAMENTAL_XBRL_ARELLE_RUNTIME_ISOLATION`（預設 `serial`）與全局 parse lock，並輸出 `runtime_isolation_mode/runtime_lock_wait_ms` metadata。
  - 已完成 taxonomy/package cache key baseline：cache key 引入 `build_arelle_taxonomy_cache_token(...)`，將 validation mode/disclosure/plugins/packages/arelle version 納入 taxonomy token；diagnostics 新增 `arelle_runtime` 延遲與 lock wait 統計摘要。
  - 已完成 prewarm strategy baseline：`run_fundamental_live_replay_cohort_gate.py` 新增可選 prewarm stage（`enable_prewarm` / `FUNDAMENTAL_LIVE_REPLAY_ENABLE_PREWARM`），在 replay checks 前按 manifest 解析 ticker+years 先行觸發 `fetch_financial_payload` 暖快取；prewarm 結果（requested/succeeded/failed/cache_hit_after_prewarm_rate）寫入 run artifact 且預設 non-blocking。
  - 已完成 runtime gate-threshold closure：`run_fundamental_replay_checks.py` 新增 `arelle_parse_latency`/`arelle_runtime_lock_wait` case+summary 指標，`validate_fundamental_replay_cohort_gate.py` 與 `run_fundamental_live_replay_cohort_gate.py` 接入對應 P90 門檻（CLI + config/env），並透過 gate profile 映射（`FUNDAMENTAL_MAX_REPLAY_ARELLE_PARSE_LATENCY_P90_MS`、`FUNDAMENTAL_MAX_REPLAY_ARELLE_RUNTIME_LOCK_WAIT_P90_MS`）納入 release governance。
- Dependency: `FB-036-S6`.
- Estimate: 2.0-2.5d.

### FB-036-S8 Release Governance for Regulatory Version Drift
- Priority: `P0`
- Status: `Done` (2026-03-10)
- Goal: 將 SEC EFM / DQC 版本漂移納入 release gate 阻斷治理。
- Scope:
  - `finance-agent-core/scripts/run_fundamental_release_gate.sh`
  - `finance-agent-core/scripts/run_fundamental_replay_checks.py`
  - `finance-agent-core/docs/fundamental_backtest_runbook.md`
- Deliverables:
  - 規則版本快照與 drift 檢查（含錯誤碼）。
  - cohort gate 報告新增 validation block rate / rule-version evidence。
- Exit:
  - 版本漂移可被 CI/release gate 明確阻斷或告警（按 profile）。
- Progress (2026-03-10):
  - 已完成 replay-checks 規則證據契約：新增 `validation_rule_runtime`（`mode/disclosure/plugins/packages/arelle_version/signature`）與 `validation_rule_actual_signature/expected_signature`，並輸出 `validation_rule_drift_count/detected/error_code`。
  - 已完成 cohort gate/runner/profile 治理接線：`validate_fundamental_replay_cohort_gate.py`、`run_fundamental_live_replay_cohort_gate.py`、`resolve/validate_fundamental_gate_profile.py` 接入 `max_validation_rule_drift_count` 與 env key `FUNDAMENTAL_MAX_REPLAY_VALIDATION_RULE_DRIFT_COUNT`（預設 `0`）。
  - 已完成 release governance artifact 接線：snapshot builder/validator 與 CI workflow summary 納入新閾值與 replay drift evidence 欄位，runbook 同步更新。
  - 驗證完成：`ruff check` + 7-file targeted pytest bundle 全綠（`42 passed`）。
- Dependency: `FB-036-S7`.
- Estimate: 1.5-2.0d.
