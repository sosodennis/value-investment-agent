# FA Agent Feature Enhancement Plan (Enterprise-Grade)

**Date**: 2026-02-23
**Input Basis**:
1. `docs/research-paper/fundamental-enhancement-cross-validation-2026-02-23.md`
2. `docs/research-paper/fundamental-enhancement-1-validated-report-2026-02-23.md`
3. `docs/research-paper/fundamental-enhancement-review-report.md`

---

## 1. 目標與結論

本計畫目標是把 `finance-agent-core/src/agents/fundamental` 從「企業級核心可用」提升到「機構級可審計、可擴展、可治理」。

已確認的核心事實：
1. 目前已具備強基礎：`CalculationGraph`、`param_builders` 分層、MC 相關性 + nearest-PSD、time alignment guard、assumption/provenance。
2. 當前主要缺口不是單點 bug，而是「架構語義一致性 + 資料治理 + 前瞻訊號入模」。
3. 優先順序應先處理根因：`model selection` 與 `calculator mapping` 的語義錯位。

---

## 2. 設計原則（Enterprise 標準）

1. **Model Risk Governance First**
   所有模型都要可追溯、可驗證、可挑戰（effective challenge）。
2. **Data Contract Before Data Source**
   先定義資料品質契約，再接資料供應商。
3. **No Silent Degradation**
   禁止靜默降級到高風險假設。
4. **Deterministic Core + Probabilistic Overlay**
   先確保 deterministic 估值穩定，再疊加 MC 與敏感度。
5. **Auditable Outputs**
   前端顯示的每個數字都要有來源、時點、假設、風險標記。

---

## 3. 目標架構（落地後）

### 3.1 模型層
1. `model_selection` 只決定語義模型。
2. `model_router` 做一對一映射到 `calculator`。
3. 每個模型有獨立：
   - `param_builder`
   - `schema`
   - `auditor`
   - `tool`

### 3.2 資料層
1. `MarketDataClient` 升級為 provider-agnostic facade。
2. 每個值附帶資料品質欄位：
   - `source`
   - `as_of`
   - `staleness_seconds`
   - `license_tier`
   - `confidence`
   - `quality_flags`

### 3.3 估值層
1. Deterministic 引擎永遠先跑並輸出固定卡片。
2. MC 作為可配置 overlay，輸出分佈 + diagnostics。
3. Sensitivity report 與 distribution_summary 同級輸出。

### 3.4 治理層
1. 所有高風險假設寫入 assumption_breakdown。
2. time-alignment、psd_repaired、fallback path 全部顯示在報表。

---

## 4. Workstreams（詳細落地方案）

## WS-1 模型語義一致性與覆蓋擴充（P0）

**目標**：修復 `dcf_standard/dcf_growth -> saas` 的語義錯位，建立可持續擴充的模型矩陣。

**實作**：
1. 新增 `calculator_model_type`：
   - `dcf_standard`
   - `dcf_growth`
2. 新增獨立 skill：
   - `valuation_dcf_standard`
   - `valuation_dcf_growth`
3. 從 `saas` 移除通用 DCF 職責，保留 SaaS 專屬假設。
4. `registry.py` / `value_objects.py` / `services.py` 同步改為一對一映射。

**驗收標準**：
1. `selected_model=dcf_standard` 不再落到 `saas`。
2. 單元測試覆蓋 model route matrix 100%。
3. `trace` 與 `assumptions` 顯示正確模型名稱。

---

## WS-2 資料治理與多來源策略（P0-P1）

**目標**：把資料供應從「可抓」提升到「可治理」。

**實作**：
1. 定義 `MarketDatum` contract：
   - `value`
   - `source`
   - `as_of`
   - `quality_flags`
   - `license_note`
2. Provider 抽象層：
   - `YahooProvider`（現有）
   - `MacroProvider`（FRED for risk-free series）
3. 速率與抓取政策：
   - SEC 依 fair-access（10 req/s 上限）做 limiter。
4. fallback policy 升級：
   - 低可信值進入 `high_risk_assumption`，禁止靜默當正常值。

**驗收標準**：
1. 每個市場欄位都有 `source + as_of + quality_flags`。
2. API 回傳可看見資料授權/來源說明。
3. 沒有任何 silently default 的高風險 fallback。

---

## WS-3 假設引擎與參數防護（P0）

**目標**：統一假設生成規範，消除跨行業硬編碼偏差。

**實作**：
1. SaaS `wacc` 與 `terminal_growth` 改為 market-aware：
   - `risk_free + beta * ERP` 為基準
   - 再套政策邊界 clamp
2. Growth blender 持續使用 context-aware weights，新增 `confidence_score`。
3. REIT `maintenance_capex_ratio` 保持可參數化，不落硬寫死。
4. Bank 路徑保留 CAPM 與 RoRWA outlier guards。

**驗收標準**：
1. SaaS 路徑不再只依賴 policy default WACC。
2. assumption_breakdown 顯示每個假設來源和 clamp 原因。
3. 極端輸入不會產生經濟學不可解結果（如 `g >= r` 未處理）。

---

## WS-4 Monte Carlo 企業級升級（P1）

**目標**：提高收斂效率、可重現性與解釋力。

**實作**：
1. 保留既有：
   - correlation groups
   - Gaussian-copula style transform
   - nearest-PSD (`clip/higham`)
2. 新增 sampler strategy：
   - pseudo-random（default）
   - LHS / Sobol（QMC）
3. diagnostics 擴充：
   - `sampler`
   - `effective_sample_size`
   - `convergence_history`
4. 批量求值接口（vectorized evaluator）：
   - 不改 DAG 定義
   - 增加 model-specific batch adapter

**驗收標準**：
1. 同樣誤差下，QMC 模式 iterations 顯著下降。
2. 相同 seed 結果可重現（可審計）。
3. diagnostics 欄位完整且前端可顯示。

---

## WS-5 前瞻非結構化訊號（P1）

**目標**：把 MD&A / earnings call 的前瞻資訊結構化，納入 assumption layer。

**實作**：
1. 新增 `ForwardSignalExtractor`：
   - MD&A trend extraction
   - guidance extraction
   - uncertainty flags
2. 輸出結構：
   - `signal_name`
   - `signal_value`
   - `confidence`
   - `evidence`
3. 僅影響 assumptions，不直接覆蓋硬財務欄位。

**驗收標準**：
1. 缺少 forward signal 時可退化，不影響主流程。
2. 每個信號有 evidence pointer，避免黑箱。
3. auditor 可檢查 signal 可信度與覆蓋率。

---

## WS-6 輸出契約、UI 與審計可見性（P1）

**目標**：讓使用者和審計都可直接看到「結果是如何來的」。

**實作**：
1. 固定顯示 deterministic 卡片：
   - `equity_value`
   - `intrinsic_value`
   - `upside_potential`
2. MC 區塊顯示：
   - P5/P25/P50/P75/P95
   - current vs distribution position
   - diagnostics（iterations, early stop, window, psd_repaired）
3. assumption_breakdown 新增：
   - `time_alignment_status`
   - `data_quality_flags`
   - `risk_level`

**驗收標準**：
1. 即使 MC 關閉，deterministic 結果仍固定可見。
2. MC 開啟時分佈與診斷完整呈現。
3. 高風險假設在 UI 可見且有明確標籤。

---

## WS-7 驗證、回測與品質閘門（P1-P2）

**目標**：建立可量化品質標準，避免「看起來可用」但不可控。

**實作**：
1. 測試分層：
   - unit（參數、矩陣、邊界）
   - integration（端到端單 ticker）
   - regression（多 ticker 快照）
2. 回測輸出：
   - JSON + Markdown 摘要 + drift table
3. 品質閾值：
   - valuation sanity checks
   - missing ratio threshold
   - correlation error threshold

**驗收標準**：
1. 每次改動都能產出 regression 報表。
2. 漂移超閾值自動標紅。
3. 回測報表可直接進審計材料。

---

## 5. 實施時程（無 feature flags / 灰度前提）

### Phase 1（Week 1-2）
1. WS-1 模型映射修正
2. WS-3 SaaS 假設動態化
3. WS-6 契約欄位補齊

### Phase 2（Week 3-4）
1. WS-2 資料治理 contract + provider facade
2. WS-4 MC sampler strategy + diagnostics 擴充

### Phase 3（Week 5-6）
1. WS-5 前瞻訊號 extraction pipeline
2. WS-7 regression + drift reporting

---

## 6. TODO / Enhancement Backlog（延後實現）

1. **HITL 全部整合**（按你要求，暫時列 TODO，不納入本輪主實作）。
2. **Fallback 政策升級**：若估值落到「行業均值」或同等低可信度替代值，必須：
   - 標記 `high_risk_assumption=true`
   - 觸發人工審批
   - 不可默默進入最終計算結果
3. **全域敏感度分析（Sobol/Shapley）與交互作用分解**（後續研究項）。

---

## 7. 企業級參考標準（外部）

1. 模型風險治理：Federal Reserve SR 11-7
   https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm
2. SEC EDGAR 存取與公平使用（速率政策）
   https://www.sec.gov/edgar/searchedgar/accessing-edgar-data.htm
3. MD&A 前瞻揭露原則（Item 303 解釋）
   https://www.sec.gov/rules-regulations/2002/01/commission-statement-about-managements-discussion-analysis-financial-condition-results-operations
4. FRED API（宏觀利率等官方數據接口）
   https://fred.stlouisfed.org/docs/api/fred/series/series_observations.html
5. NumPy multivariate normal（PSD 要求）
   https://numpy.org/doc/stable/reference/random/generated/numpy.random.Generator.multivariate_normal.html
6. Higham nearest correlation matrix
   https://eprints.maths.manchester.ac.uk/232/1/paper3.pdf
7. REIT AFFO 非標準化聲明（需來源註記）
   https://www.reit.com/glossary-detail/adjusted-funds-operations-affo
8. SciPy QMC（Sobol/LHS）
   https://docs.scipy.org/doc/scipy/reference/stats.qmc.html
