# Fundamental AAPL Consensus-Anchor Remediation Plan (2026-03-07)

## Debug Review (agent-debug-review-playbook)

### Findings

1. `P1` Cross-source consensus anchor 在實跑中未生效，`target_mean_price` 實際回退到 `yfinance` 單一來源。
- Impact:
  - AAPL 比較主流共識時，anchor 來源失真，導致「模型是否偏離主流」判斷不可靠。
- Evidence:
  - `/Users/denniswong/Desktop/Project/value-investment-agent/docs/logs/fa-aapl.log:786` (`target_mean_price.source=yfinance`)
  - `/Users/denniswong/Desktop/Project/value-investment-agent/docs/logs/fa-aapl.log:796`
  - `/Users/denniswong/Desktop/Project/value-investment-agent/docs/logs/fa-nvda.log:759`
  - `/Users/denniswong/Desktop/Project/value-investment-agent/docs/logs/fa-nvda.log:769`
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py:52`

2. `P2` Multi-source 失敗可觀測性不足：已收集 `source_warnings`，但主要 runtime log 未輸出，難以判斷失敗根因（fetch blocked / parse drift / insufficient sources）。
- Impact:
  - 現場排錯成本高，且容易把問題誤判為估值策略本身。
- Evidence:
  - `source_warnings` 有寫入 snapshot，但 `fundamental_market_data_fetched` 僅輸出 `key_market_inputs`。
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py:261`
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py:285`
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/metadata_service.py:118`

3. `P2` Free consensus provider parser 對頁面結構漂移敏感，缺乏 fixture 回歸保護。
- Impact:
  - 網站小幅改版即可觸發 parse miss，最終退回 yfinance，弱化 cross-source 設計。
- Evidence:
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/tipranks_provider.py:25`
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/investing_provider.py:26`
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/marketbeat_provider.py:26`
  - 現有測試偏向 synthetic datums，不覆蓋實頁 HTML 變體。
  - `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_consensus_anchor_aggregator.py:14`

4. `P2` AAPL 估值中心仍明顯偏保守：`replayed_intrinsic_value=203.47`，相對主流免費來源中位數約 `296.08`（2026-03-07）低約 `31.3%`。
- Impact:
  - 以「主流共識區間」作為比較基準時，AAPL 案例無法通過可用性期待。
- Evidence:
  - replay artifact: `/tmp/fundamental-replay-inputs/aapl.report.replay.latest.json`
  - consensus references (2026-03-07 snapshot): TipRanks / Investing / MarketBeat / StockAnalysis.

### Assumptions/Open Questions

1. 本輪修復目標是「讓 AAPL 比較主流共識時不再因來源失效而偏差放大」，不是把模型硬貼 sell-side 目標價。
2. 直接上線，無 feature flag（沿用既有決策）。
3. 本輪只做後端與日志/metadata 可觀測性擴充，不改前端交互版面。

### Applied Changes

1. 無（本文件為 debug + planning artifact）。

### Validation

1. 檢視最新 AAPL/NVDA log：確認 `target_mean_price` 來源皆為 `yfinance`。
2. 檢視 market data path：確認 cross-source aggregate 已接線但可退回 fallback。
3. 跑現有 consensus 相關測試：`10 passed`（表示邏輯可跑，但不等同實網解析穩定）。

## Requirement Breakdown

1. 目標
- 修復共識提取鏈路，讓 `target_mean_price` 優先使用 `free_consensus_aggregate`（可用時）。
- 在失敗/退回情況下，提供機器可讀降級訊號，避免「靜默 fallback」。
- 以主流共識區間作為外部比較錨點，降低 AAPL 類案例偏保守風險。

2. 成功標準
- AAPL 實跑 completion fields 出現 `target_consensus_source_count>=2` 且 `target_mean_price.source=free_consensus_aggregate`（在來源可用時）。
- 若來源不足，`is_degraded=true` 並輸出明確 `degrade_reasons`（例如 `target_consensus_insufficient_sources`）。
- replay/backtest 可量化 `consensus_gap_pct`，AAPL 案例由約 `-31.3%` 顯著收斂（以既定門檻評估）。

3. 既有約束
- 不改 DCF 計算圖核心公式。
- 保留現有 assumptions / snapshot traceability。
- 不依賴付費資料供應商。

4. Out of Scope（本輪不做）
- 不引入新的付費共識來源（FactSet/Bloomberg/LSEG）。
- 不重構整個 SEC text / XBRL 信號管線。
- 不做前端交互改版，只擴充字段。
- 不做在線自動重訓或自動調參。

## Technical Objectives and Strategy

1. `Consensus Ingestion Hardening`
- 強化 TipRanks / Investing / MarketBeat parser，加入多 pattern fallback 與 HTML fixture 回歸測試。
- 保留 `yfinance` 作兜底，但要求 fallback 明確可觀測。

2. `Degrade Signaling`
- 在 market data fetched / valuation completed 事件中加上 consensus 聚合狀態欄位：
  - `target_consensus_applied`
  - `target_consensus_source_count`
  - `target_consensus_sources`
  - `target_consensus_fallback_reason`
  - `target_consensus_warnings`
- 同步寫入 snapshot metadata 與 completion fields，支持 replay 與 post-mortem。

3. `AAPL Bias Remediation (Parameter Layer, 非公式改寫)`
- 先確保共識 anchor 生效，再調整 `dcf_standard` 下與 AAPL 相關的基底參數策略：
  - short-term consensus decayed window（已採 3 年）保持；
  - 針對 mature profile 校準 growth/margin guardrail 映射幅度，避免過度保守。
- 校準依據使用 replay + backtest cohort，而非單票手工調參。

## Involved Files

1. 共識抓取與聚合
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/free_consensus_web_parser.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/tipranks_provider.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/investing_provider.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/marketbeat_provider.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/consensus_anchor_aggregator.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py`

2. Metadata / completion / degrade signaling
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/metadata_service.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_flow.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/application/services/valuation_update_service.py`

3. 動態參數（AAPL 偏保守修復）
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/policies/base_assumption_guardrail_policy.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/dcf/dcf_standard.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/dcf/dcf_variant_payload_service.py`

4. 測試與回放工具
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_consensus_anchor_aggregator.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_fundamental_market_data_client.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_fundamental_orchestrator_logging.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/tests/test_replay_fundamental_valuation_script.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/scripts/replay_fundamental_valuation.py`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/scripts/run_fundamental_backtest.py`

## Detailed Per-File Plan

1. `free_consensus_web_parser.py`
- 新增 bounded diagnostics helper（pattern hit/miss count、html snippet hash），避免泄漏原文且提升可觀測。

2. `tipranks_provider.py` / `investing_provider.py` / `marketbeat_provider.py`
- 擴充解析 pattern（先 JSON key，再可見文本 fallback），並回傳結構化 warning code。
- 將 analyst count 抽取與 target value 抽取分離記錄，便於定位 coverage vs parse 問題。

3. `consensus_anchor_aggregator.py`
- 將 `insufficient_sources`、`filtered_by_analyst_count`、`stale_filtered` 轉為 machine-readable reason keys。
- `source_detail` 保持 `source_count/sources/analyst_count_total`，確保 completion parser 可提取。

4. `market_data_service.py`
- 在 `fundamental_market_data_fetched` log fields 增加：
  - `source_warnings`（去重後）
  - `target_consensus_applied`（bool）
  - `target_consensus_fallback_reason`（若回退）
- 若 consensus aggregate 未生效且 `target_mean_price` 回退 yfinance，附加 quality flag（例如 `target_consensus_fallback`）。

5. `metadata_service.py`
- 將 `source_warnings` 納入 `data_freshness.market_data`，供 completion/degrade 流程消費。

6. `run_valuation_flow.py` / `valuation_update_service.py`
- completion fields 增補 consensus degrade 專用欄位。
- 將 consensus fallback 納入 `is_degraded` 判定（條件式，不影響完全不可用以外的主流程返回）。

7. `base_assumption_guardrail_policy.py` + `dcf_standard` path
- 在 consensus anchor 修復後，再做成熟型（AAPL）guardrail 幅度校準：保留方向、降低過度保守扣分幅度。
- 變更需帶 `raw -> guarded -> calibrated` 三段數值審計欄位。

8. 測試
- 新增 provider fixture 測試（模擬頁面變體）。
- 擴充 orchestrator/completion log 測試，確保 fallback reason 可機器讀取。
- replay/backtest case 增加 AAPL consensus-gap 回歸基線。

## Risk/Dependency Assessment

1. 功能風險
- parser 強化後仍受網站反爬/地區封鎖影響；需保持 deterministic fallback。

2. 數據風險
- free source 數據更新節奏與口徑不一致；需以 cross-source median 抑制單源偏差。

3. 運維風險
- 若新增降級規則過於敏感，可能提高 `is_degraded` 比率；需先定義告警門檻。

4. 依賴
- 需要穩定的 replay artifact 與 backtest DCF cohort。
- 需要 fixture 管理機制，避免測試依賴實網。

5. 回退策略
- parser/aggregation 層可單獨回退（保持 yfinance fallback）。
- guardrail 校準映射 artifact 可版本回退。

## Validation and Rollout Gates

1. Gate 1（Unit/Contract）
- provider parser fixture 測試全綠；aggregator reason key 合約穩定。

2. Gate 2（Integration）
- AAPL/NVDA 實跑 log 出現可判讀 consensus status（applied 或 fallback + reason）。

3. Gate 3（Replay）
- 以同一 replay input 重播，確認輸出可重現且 `consensus_source_count` 可追溯。

4. Gate 4（Backtest）
- `consensus_gap_distribution.available_count` 達最小樣本門檻。
- AAPL cohort 的 `consensus_gap_pct` 相對基線明顯改善或至少不劣化。

5. Gate 5（Post-Deploy 24h）
- 監控：
  - `target_consensus_applied_rate`
  - `target_consensus_fallback_rate`
  - `valuation_degrade_rate`
  - `consensus_gap_distribution`（有 coverage 時）

## Assumptions/Open Questions

1. 是否確認本輪將 `target_consensus_fallback` 納入 `is_degraded=true`（建議：是，但僅在 target anchor 被使用於監控/校準路徑時）？
2. provider fixture 的頁面樣本是否可放在 repo（去識別化後）？
3. AAPL bias 修復本輪是否只調 `dcf_standard` profile，不動 `dcf_growth`（建議：是，隔離影響面）？

## Execution Progress (As of 2026-03-11)

Completed slices:
1. `S1` (medium): free-consensus parser drift-hardening + fixture regression baseline
- Provider fallback pattern hardening:
  - `tipranks_provider.py`: text fallback patterns for average/high/low target and analyst-count phrases.
  - `investing_provider.py`: text fallback patterns for average/high/low target phrases.
  - `marketbeat_provider.py`: added consensus text fallback pattern (`Consensus Price Target`).
- Added fixture-backed regression HTML samples:
  - `tests/fixtures/free_consensus/tipranks_page_text_variant.html`
  - `tests/fixtures/free_consensus/investing_search_variant.html`
  - `tests/fixtures/free_consensus/investing_page_text_variant.html`
  - `tests/fixtures/free_consensus/marketbeat_search_variant.html`
  - `tests/fixtures/free_consensus/marketbeat_page_text_variant.html`
- Extended provider tests (`tests/test_free_consensus_providers.py`) with fixture-driven variant coverage for TipRanks/Investing/MarketBeat text-fallback parsing.
- Validation evidence:
  - `ruff check` (provider modules + test file) passed.
  - targeted pytest bundle passed: `23 passed`.
2. `S2` (medium): target-consensus warning code standardization and propagation
- Added machine-readable `target_consensus_warning_codes` in market snapshot contract and runtime log fields.
- `market_data_service.py` now normalizes warning/fallback signals into stable codes (for example: `insufficient_sources`, `provider_blocked`, `provider_blocked_http`, `provider_governance_review_required`, `single_source_consensus`).
- Metadata/completion propagation wired:
  - `metadata_service.py`: includes `target_consensus_warning_codes` under `data_freshness.market_data` and `parameter_source_summary.market_data_anchor`.
  - `run_valuation_flow.py`: emits `target_consensus_warning_codes` in valuation completion fields.
- Test coverage updates:
  - `test_fundamental_market_data_client.py`: asserts warning-code propagation for aggregate, insufficient-sources fallback, blocked-provider fallback, and single-source degraded scenarios.
  - `test_fundamental_orchestrator_logging.py`: asserts completion field includes warning codes on fallback-degraded path.
- Validation evidence:
  - `ruff check` (changed runtime + tests) passed.
  - targeted pytest bundle passed: `27 passed`.
3. `S3` (small): replay report warning-code evidence fields
- `replay_fundamental_valuation.py` 新增 target-consensus warning-code replay evidence：
  - `baseline_target_consensus_warning_codes`
  - `replayed_target_consensus_warning_codes`
  - `baseline/replayed_target_consensus_warning_code_count`
  - `target_consensus_warning_codes_added`
  - `target_consensus_warning_codes_removed`
- warning-code extraction 支援 `data_freshness.market_data` 與 `parameter_source_summary.market_data_anchor` 來源，避免 metadata path 差異造成 replay 契約缺洞。
- 測試更新：`test_replay_fundamental_valuation_script.py` 新增 warning-code 差異驗證（added/removed + counts）。
- Validation evidence:
  - `ruff check` (replay script + tests) passed.
  - targeted pytest bundle passed: `16 passed`.
4. `S4` (medium): backtest warning-code distribution and monitoring gate wiring
- Backtest contract/runtime 擴展：
  - `BacktestCase` 新增 `target_consensus_warning_codes`。
  - case loader/runtime 會將 warning codes 寫入 case metrics，供 cohort summary 消費。
- Backtest report summary 新增：
  - `consensus_warning_code_distribution`（`available_count/code_case_counts/code_case_rates`）
  - `consensus_provider_blocked_rate`
  - `consensus_parse_missing_rate`
- Monitoring gate 新增參數（`run_fundamental_backtest.py`）：
  - `--max-consensus-provider-blocked-rate`
  - `--max-consensus-parse-missing-rate`
  - `--min-consensus-warning-code-count`
- release gate shell pass-through 新增對應 env：
  - `FUNDAMENTAL_MAX_CONSENSUS_PROVIDER_BLOCKED_RATE`
  - `FUNDAMENTAL_MAX_CONSENSUS_PARSE_MISSING_RATE`
  - `FUNDAMENTAL_MIN_CONSENSUS_WARNING_CODE_COUNT`
- 測試更新：
  - `test_fundamental_backtest_report_service.py` 覆蓋 warning-code 分佈與 rate。
  - `test_fundamental_backtest_runner.py` 新增 provider_blocked rate gate breach 測試，並覆蓋 case-loader/runtime warning-code 傳遞。
- Validation evidence:
  - `ruff check` (backtest runtime/report/script + tests) passed.
  - targeted pytest bundle passed: `16 passed`.
5. `S5` (small): gate-profile threshold closure for warning-code monitoring gates
- Gate profile source of truth now includes warning-code monitoring thresholds for all profiles:
  - `max_consensus_provider_blocked_rate`
  - `max_consensus_parse_missing_rate`
  - `min_consensus_warning_code_count`
- Profile resolver/validator wiring completed:
  - `resolve_fundamental_gate_profile.py` exports the three env vars
    (`FUNDAMENTAL_MAX_CONSENSUS_PROVIDER_BLOCKED_RATE`,
    `FUNDAMENTAL_MAX_CONSENSUS_PARSE_MISSING_RATE`,
    `FUNDAMENTAL_MIN_CONSENSUS_WARNING_CODE_COUNT`).
  - `validate_fundamental_gate_profiles.py` treats the new keys as required thresholds
    (`min_consensus_warning_code_count` as int-like).
- Test coverage update:
  - `test_resolve_fundamental_gate_profile_script.py` now asserts exported env values for new keys.
- Validation evidence:
  - `ruff check` (profile scripts + tests) passed.
  - targeted pytest bundle passed: `11 passed`.
6. `S6` (medium): release snapshot + CI governance wiring for warning-code thresholds/evidence
- `build_fundamental_release_gate_snapshot.py` now ingests warning-code gate thresholds and persists them under `thresholds`:
  - `max_consensus_provider_blocked_rate`
  - `max_consensus_parse_missing_rate`
  - `min_consensus_warning_code_count`
- Snapshot summary extraction now carries warning-code governance evidence:
  - `consensus_provider_blocked_rate`
  - `consensus_parse_missing_rate`
  - `consensus_warning_code_distribution` (`available_count/code_case_counts/code_case_rates`)
- `validate_fundamental_release_gate_snapshot.py` now validates the above summary fields as required snapshot contract.
- CI workflow wiring (`monorepo-contract-gates`) updated:
  - snapshot build step now passes new threshold args.
  - release summary step now prints the new threshold values into `GITHUB_STEP_SUMMARY`.
- Test coverage update:
  - `test_build_fundamental_release_gate_snapshot_script.py`
  - `test_validate_fundamental_release_gate_snapshot_script.py`
- Validation evidence:
  - `ruff check` (snapshot scripts + tests) passed.
  - targeted pytest bundle passed: `11 passed`.
