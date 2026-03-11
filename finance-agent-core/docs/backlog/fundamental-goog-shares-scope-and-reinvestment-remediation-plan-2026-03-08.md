# Fundamental GOOG Shares-Scope and Reinvestment Remediation Plan (2026-03-08)

## Requirement Breakdown

1. Objective
- 修復 GOOG（Class C）估值相對主流共識顯著偏低問題，優先處理已驗證高敏感因子：
  - `shares scope`（class shares vs consolidated shares）治理
  - reinvestment/capex 路徑過度保守
- 保留 DCF 計算圖核心公式，不做「為貼價格而硬調折現率」。

2. Success Criteria
- 同一 replay case 下可輸出可審計分解：
  - `raw_shares -> governed_shares`
  - `raw_capex/wc -> guarded_capex/wc`
  - `wacc inputs (equity value/debt value)` 與來源。
- GOOG replay baseline 相對主流共識 gap 顯著收斂（目標：先收斂至少 20-30 個百分點，而非一次貼齊賣方目標）。
- 變更對 AAPL/NVDA/MSFT 回放不劣化（或在可接受閾值內）。

3. Constraints
- 直接上線，無 feature flag。
- 本輪僅後端與可觀測性欄位擴充；不改前端交互版面。
- 不引入付費供應商；保留 free-source + yfinance fallback。

4. Out of Scope
- 不重寫 DCF graph。
- 不做即時在線自動調參/訓練。
- 不把模型輸出替換為外部 target price（外部只作校準/監控錨點）。

## Technical Objectives and Strategy

1. Shares Scope Governance（P1）
- 建立「價格-股本語義一致性」策略，避免 class ticker 直接套用不一致分母。
- 核心原則：
  - `shares_scope` 顯式化（`market_class` / `filing_consolidated` / `harmonized`）。
  - `equity_market_value` 與 `shares_outstanding` 解耦治理：優先使用可審計 market-cap 路徑，避免 `current_price * wrong_scope_shares`。
  - class mismatch 觸發時輸出 machine-readable fallback reason，不做靜默切換。

2. Reinvestment/Capex Conservative Path Remediation（P1）
- 針對 GOOG 類案例新增可校準 guardrail：
  - capex rate / wc rate 不直接把單年極端值外推 10 年。
  - 加入歷史窗口平滑（例如 5Y robust median + clamp）與成熟型上限/下限。
  - 保留 `raw -> guarded` 兩段值以支持 replay 審計。

3. Consensus Anchor Reliability for Diagnostics（P2）
- 403 導致多源失效時，保持 valuation 可跑，但提升診斷可信度：
  - 明確標記 `target_consensus_applied=false`、`source_count`、`fallback_reason`。
  - 在 release/backtest 報告區分「模型偏差」與「共識來源退化」。

4. Replay-Driven Tuning Loop（P1）
- 用現有 replay/input-contract 工具作 deterministic tuning：
  - 固定 GOOG case + cohort 守門（AAPL/NVDA/MSFT）
  - 每次只調一個政策面（shares scope 或 reinvestment），避免耦合漂移。

## Involved Files

1. Shares scope / capital structure governance
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/shared/capital_structure_value_extraction_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/shared/equity_market_value_extraction_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/saas/saas.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/metadata_service.py`

2. Reinvestment guardrail
- `finance-agent-core/src/agents/fundamental/domain/valuation/policies/base_assumption_guardrail_policy.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/model_builders/dcf/dcf_variant_payload_service.py`
- `finance-agent-core/src/agents/fundamental/domain/valuation/parameterization/growth_blend_service.py` (若需與 growth 路徑協同)

3. Replay/backtest observability
- `finance-agent-core/scripts/replay_fundamental_valuation.py`
- `finance-agent-core/scripts/run_fundamental_backtest.py`
- `finance-agent-core/src/agents/fundamental/application/use_cases/run_valuation_use_case.py`

4. Market consensus diagnostics
- `finance-agent-core/src/agents/fundamental/infrastructure/market_data/market_data_service.py`
- `finance-agent-core/src/agents/fundamental/infrastructure/market_data/consensus_anchor_aggregator.py`

5. Tests / fixtures
- `finance-agent-core/tests/test_param_builder_canonical_reports.py`
- `finance-agent-core/tests/test_replay_fundamental_valuation_script.py`
- `finance-agent-core/tests/test_fundamental_backtest_runner.py`
- `finance-agent-core/tests/fixtures/fundamental_replay_inputs/*.json`

## Detailed Per-File Plan

1. `capital_structure_value_extraction_service.py` / `equity_market_value_extraction_service.py`
- 新增 shares scope resolution contract：
  - `resolved_shares_scope`
  - `resolved_equity_value_scope`
  - `scope_mismatch_detected`
- 產出 deterministic fallback reason（例如 `class_scope_mismatch`）。

2. `saas.py`
- 套用 shares scope policy：
  - 分母與 equity value 使用一致語義路徑。
  - 保留 conservative denominator 但加入 scope guard，避免 class ticker 被過度放大保守處理。
- assumptions 補充結構化語句，供 replay 抽取。

3. `base_assumption_guardrail_policy.py` + `dcf_variant_payload_service.py`
- 新增 reinvestment guardrail（capex/wc）：
  - 歷史平滑 + clamp + 成熟型 profile。
  - 輸出 `raw/guarded/reason`。

4. `metadata_service.py` + `run_valuation_use_case.py`
- 擴充 metadata/completion fields：
  - `shares_scope`
  - `equity_value_scope`
  - `scope_mismatch_detected`
  - `capex_guardrail_applied`
  - `wc_guardrail_applied`

5. `replay_fundamental_valuation.py`
- 報告新增 drift 拆解欄位：
  - shares path delta
  - reinvestment path delta
  - guarded contribution summary

6. `run_fundamental_backtest.py`
- cohort 指標新增：
  - `consensus_gap_pct`（已有則沿用）
  - `shares_scope_mismatch_rate`
  - `reinvestment_guardrail_hit_rate`

7. Tests
- 新增 GOOG class-scope regression：
  - 驗證 mismatch detect + deterministic fallback。
- 新增 reinvestment guardrail regression：
  - 單年 capex outlier 不得直接外推全期。
- 回歸 AAPL/NVDA/MSFT/GOOG replay cohort 不劣化 gate。

## Risk/Dependency Assessment

1. Functional Risk
- shares scope policy 若設計錯誤，可能把 class ticker 系統性高估或低估。
- Mitigation: 先上 metadata + replay decomposition，再切 policy。

2. Data Risk
- free consensus sources 持續 403 時，外部錨點 coverage 不穩。
- Mitigation: 將「來源退化」與「模型偏差」分離監控，不阻塞核心估值計算。

3. Migration Risk
- capital structure 路徑牽涉多模型共用元件，可能引入跨模型副作用。
- Mitigation: 分 phase，先 DCF（dcf_growth / dcf_standard），其餘模型後續評估。

4. Dependency
- 需要穩定 replay dataset（GOOG + AAPL/NVDA/MSFT）與可重現 pipeline。
- 需要已有 release gate 能承接新增欄位（本輪已具 replay gate 基礎）。

5. Rollback
- 可按 phase 回退：
  - 先回退 shares scope policy block
  - 再回退 reinvestment guardrail block
  - 保留 observability 欄位（低風險，可持續診斷）。

## Validation and Rollout Gates

1. Gate 1 (Unit/Contract)
- 新增 shares scope / reinvestment policy 單元測試全綠。
- lint/type/contract checks 全綠。

2. Gate 2 (Replay Determinism)
- GOOG replay：baseline 與 tuned 版本差異可由新欄位解釋。
- replay 報告必含 `shares_scope` 與 reinvestment guardrail diagnostics。

3. Gate 3 (Cohort Regression)
- AAPL/NVDA/MSFT/GOOG cohort 不出現新的極端漂移。
- `shares_scope_mismatch_rate`、`reinvestment_guardrail_hit_rate` 在可解釋區間。

4. Gate 4 (Consensus-relative Check)
- 在有共識覆蓋樣本中，GOOG `consensus_gap_pct` 顯著收斂。
- 若共識來源退化，報告需顯示 `coverage_degraded`，不把結果誤判為模型失敗。

5. Gate 5 (Post-deploy 24h)
- 監控：
  - `valuation_drift`
  - `shares_scope_mismatch_detected`
  - `target_consensus_applied_rate`
  - `reinvestment_guardrail_hit_rate`

## Assumptions/Open Questions

1. 本輪比較標的是 `GOOG`（Class C），不是 `GOOGL`；是否保持。
2. shares scope 預設策略是否採：
  - DCF 路徑優先 `harmonized/consolidated`，僅在可證明一致時使用 `market_class`。
3. GOOG 收斂目標是否先設「相對主流共識 gap 收斂 20-30 個百分點」作第一階段門檻。
4. 本輪是否同意只做後端與字段擴充，不改前端交互。

## Auto-Harmonize Applicability Research (2026-03-08)

1. 不適合「自動 shares harmonize」的 ticker 類型（需先進入 denylist 或 manual review）
- 多股權類別/多上市線且經濟權利或流動性語義可能不一致：例如同公司不同 class line（`GOOG/GOOGL`、`BRK.A/BRK.B` 類型）。
  - 依據：S&P、FTSE 方法論都強調多 share class 的 company-level 聚合與 line-level可投資性規則，不能只靠單一 ticker 價格直接配任意分母。
- ADR/ADS（含 ratio 變更風險）：ADR 的「每 ADR 對應普通股數量」可變，不能假設 `price * shares` 與本地普通股分母天然同語義。
  - 依據：SEC Investor Bulletin 與 Nasdaq ADR ratio-change 公告。
- Tracking stocks、SPAC units/warrants/rights、優先股等非標準普通股工具。
  - 依據：S&P eligibility 明確排除 tracking stocks、warrants、rights、units、convertibles、preferreds 等。

2. 企業級常見做法（我們建議採納）
- 先做 instrument gating，再做 harmonize：僅 `common equity` 才走自動 harmonize；其餘路徑強制 `manual_review_required`。
- 先做 security-master 正規化：以 `underlying_company_id + share_class_id + instrument_type + conversion_ratio` 決定可否自動對齊。
  - 實務可用 OpenFIGI 類欄位（如 `shareClassFIGI`、`compositeFIGI`、`securityType`）做標準化主鍵，不以 ticker 字串判斷。
- 只在「價格-分母同 scope」證據充足時啟用 harmonize；否則保守 fallback 並輸出 machine-readable reason（`class_scope_mismatch` / `adr_ratio_unverified` / `non_common_security`）。

3. 對 FB-032 的落地影響
- `S3` 期間先保持 `harmonize_when_mismatch` 現有路徑，但新增 pre-check hook（security type/scope guard）接口，避免 future regression。
- `S4` cohort gate 加上 `auto_harmonize_blocked_rate`、`manual_review_required_rate` 監控欄位（先後端與報告，前端暫不改交互）。

4. 參考資料（權威）
- [S&P Dow Jones U.S. Indices Methodology](https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-us-indices.pdf)
- [FTSE Russell U.S. Equity Indexes Guide to Calculation Methodology](https://www.lseg.com/content/dam/ftse-russell/en_us/documents/methodology-documents/us-equity-indexes-guide-to-calculation-methodology.pdf)
- [Investor.gov: American Depositary Receipts](https://www.investor.gov/introduction-investing/general-resources/news-alerts/alerts-bulletins/investor-bulletins-44)
- [Nasdaq announcement examples for ADR ratio change](https://www.nasdaq.com/articles/weibo-announces-change-ratio-its-adss-effective-march-29-2024)
- [OpenFIGI API docs (`securityType`, `shareClassFIGI`, `compositeFIGI`)](https://www.openfigi.com/api/documentation)

## Execution Progress (As of 2026-03-08)

Completed slices:
1. `S1` (medium): shares scope observability path
- `saas` payload 新增結構化 `shares_path` 診斷（`shares_scope`/`equity_value_scope`/`scope_mismatch_detected`/ratio）。
- metadata 寫入：
  - `data_freshness.shares_path`
  - `parameter_source_summary.shares_outstanding`（合併 shares scope 診斷）。
- completion fields 新增 shares scope 訊號，並將 `shares_scope_mismatch` 納入 degrade reasons。
- replay report 新增：
  - `baseline_shares_path`
  - `replayed_shares_path`
- 測試與 lint 全綠（targeted + related suites）。
2. `S2` (medium): shares scope policy governance
- DCF variant 引入 deterministic policy mode：
  - `harmonize_when_mismatch`（預設）
  - `conservative_only`（可配置）
- 在 `scope_mismatch_detected=true` 且 market shares 可用且非 stale 時，
  將分母 harmonize 到 market-class shares，並寫回：
  - `shares_outstanding_source=market_data_scope_harmonized`
  - `shares_path.scope_policy_mode/scope_policy_resolution`
  - `scope_mismatch_resolved=true`
- completion/degrade 規則更新：若 mismatch 已 `resolved`，不再標記
  `shares_scope_mismatch` degraded。
- 測試與 lint 全綠（targeted + related suites）。
3. `S3` (medium): reinvestment/capex guardrail calibration
- `dcf_variant_payload_service` 新增 reinvestment guardrail（`capex_rates` / `wc_rates`）：
  - profile 化配置（`dcf_growth` / `dcf_standard`）
  - historical anchor（從 report 歷史 capex/wc rate 取 robust median）
  - `raw -> guarded` 套用與 trace input 同步更新。
- assumptions 新增 machine-readable 記錄：
  - `base_reinvestment_guardrail applied (... metric=capex_rates|wc_rates, anchor, anchor_samples, reasons)`
- replay 報告新增 reinvestment drift 診斷：
  - `baseline/replayed_capex_rates_summary`
  - `baseline/replayed_wc_rates_summary`
  - `capex_year1/yearN_delta`, `wc_year1/yearN_delta`
  - `baseline/replayed_capex_guardrail`, `baseline/replayed_wc_guardrail`。
- valuation diagnostics / assumption breakdown 擴充：
  - `base_capex_guardrail_*`
  - `base_wc_guardrail_*`
  - `base_guardrail_hit_count` 現支援 growth/margin/capex/wc 聚合。
- 測試與 lint 全綠（83 passed，ruff all checks passed）。
4. `S4` (small): cohort replay + backtest gate 收斂驗證
- backtest runtime metrics 擴充：
  - `base_capex_guardrail_applied`
  - `base_wc_guardrail_applied`
  - `shares_scope_mismatch_detected`
  - `shares_scope_mismatch_resolved`

## Enterprise Validation Addendum (2026-03-09)

1. Shares-scope 治理依據（非貼價調參）
- S&P Dow Jones 方法論指出多股權類別若以單一 class 價格配總股數會造成權重失真，需按 line-level 可投資股本處理。
- FTSE Russell 方法論同樣以 security-level `price x available shares`（float-adjusted）計算，不以混合語義分母直接乘價。
- 因此本輪 `harmonized_market_class` + mismatch ratio gate 是先修正語義一致性，再做參數治理。

2. Reinvestment clamp 依據（企業級現金流一致性）
- Damodaran 估值框架：`Expected growth in EBIT = Reinvestment rate * Return on capital`；
  終值期的 reinvestment 不應在正增長假設下無約束掉到近零。
- Damodaran `Current Data` 提供按行業分組的 `Capital Expenditures` / `Working Capital` / `Growth-Reinvestment` 資料集，適合作為 guardrail 參數的定期校準基準（本輪先用公司級 SEC 證據落地，行業面板作下一輪雙週更新輸入）。

3. Company evidence 對照（GOOG/Alphabet）
- Alphabet 2024 Form 10-K：`Consolidated revenues 350,018`；`capital expenditures 52.5B`，對應 capex intensity 約 `15.0%`。
- Alphabet 2023 Form 10-K（同份報告中的對照年度）：`Consolidated revenues 307,394`；`capital expenditures 32.3B`，對應 capex intensity 約 `10.5%`。
- 本輪 severe clamp `capex_terminal_lower = max(14%, year1*1.25)`、`wc_terminal_lower = max(2.5%, year1*0.35)` 是在上述區間下的保守下界治理，不是外部 target-price 反推。

4. 實務落地規則（避免濫用）
- 只在以下同時成立時觸發 severe clamp：
  - `dcf_growth`
  - `scope_policy_resolution=harmonized_market_class`
  - `scope_mismatch_ratio >= 45%`
  - `target_premium <= 30%`
  - 共識品質 degraded（fallback 或 degraded bucket）
- 其餘案例維持原 guardrail，不將 GOOG 特例擴散到全市場。
- backtest summary 指標新增：
  - `reinvestment_guardrail_hit_rate`
  - `shares_scope_mismatch_rate`（僅計 unresolved mismatch）。
- monitoring gate 新增可配置閾值：
  - `--min-reinvestment-guardrail-hit-rate`
  - `--max-shares-scope-mismatch-rate`
- runbook、report service、runner 測試同步更新。

Remaining slices:
1. 無（`FB-032` 本計劃範圍切片完成）
