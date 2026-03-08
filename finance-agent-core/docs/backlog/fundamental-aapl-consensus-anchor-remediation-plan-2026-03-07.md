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
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_use_case.py`
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

6. `run_valuation_use_case.py` / `valuation_update_service.py`
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
