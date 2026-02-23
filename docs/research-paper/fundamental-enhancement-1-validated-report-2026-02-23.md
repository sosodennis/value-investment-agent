# Fundamental Enhancement-1 外部驗證報告（嚴格交叉審查）

**Date**: 2026-02-23
**Target**: `docs/research-paper/fundamental-enhancement-1.md`
**Scope**: 逐條比對「架構師觀點」vs「現有代碼」vs「外部一手來源」

---

## 1) 結論摘要

整體判定：架構師的方向大多正確，但不是「完全正確」。

- 已被你們代碼實作或超前的部分：`MarketDataClient` 動態抓取、time-alignment guard、Monte Carlo 的相關性抽樣與 nearest-PSD 修正、審計邊界檢查。
- 仍然成立的關鍵缺口：
  1. **模型語義與執行引擎不一致**（`dcf_standard/dcf_growth` 最終仍路由到 `saas` 引擎）。
  2. **單一市場數據來源風險**（目前主要依賴 yfinance，且 yfinance 官方聲明為 personal use）。
  3. **前瞻非結構化資料尚未進入估值主流程**（MD&A / earnings call / SaaS 專有指標）。

---

## 2) 逐條驗證（Verdict Matrix）

### A. 「目前是企業級骨架，但落地前需補強 resilience/guardrails」
**Verdict: 部分正確（Mostly true）**

代碼側證據（已做）：
- 估值審計規則已落地：`audit_saas_params/audit_bank_params` 有硬邊界（如 terminal growth、WACC/COE 下限）。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/skills/auditor/rules.py:38`
- XBRL 提取層有維度/期間/單位過濾與 rejection telemetry。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/extractor.py:185`

外部驗證：
- SEC 官方持續提示結構化申報錯誤與 filer reminders，表示資料品質風險客觀存在。
  [SEC staff statement (2024-02-21)](https://www.sec.gov/newsroom/whats-new/osd-announcement-022124)
  [SEC EDGAR Filer Manual list of reminders](https://www.sec.gov/submit-filings/filer-support-resources/edgar-filer-manual/list-edgar-filer-manual-filing-applications-and-filer-resources)

---

### B. 「Monte Carlo 若是純 Python 迴圈，企業級會卡效能」
**Verdict: 部分正確（Partially true）**

代碼側證據：
- 抽樣端已向量化（`numpy` + 多變量常態 + Copula-style 映射 + correlation diagnostics）。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/monte_carlo.py:253`
- 但 evaluator 仍是逐迭代 Python call。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/monte_carlo.py:97`

判定：
- 架構師說「可能成瓶頸」成立；但說成「純 Python MC」不精確，因為你們抽樣核心已是 NumPy 向量化。

---

### C. 「相關性矩陣需要 PSD 修正，否則會崩潰」
**Verdict: 正確，而且你們已實作（True + already implemented）**

代碼側證據：
- 已有 `clip/higham/error` policy、eigen floor、repair diagnostics。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/monte_carlo.py:267`

外部驗證：
- Higham 的 nearest correlation matrix 是業界與學術標準。
  [Higham (2002) - Computing the nearest correlation matrix](https://eprints.maths.manchester.ac.uk/232/1/paper3.pdf)
- NumPy 官方文件也要求 covariance 要 PSD（否則屬 invalid）。
  [NumPy multivariate_normal docs](https://numpy.org/doc/stable/reference/random/generated/numpy.random.multivariate_normal.html)

---

### D. 「模型覆蓋不足：缺標準 DCF / SOTP / NAV / rNPV」
**Verdict: 部分正確（Partially true）**

代碼側證據：
- 選模層確實有 `DCF_STANDARD` / `DCF_GROWTH`。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/model_selection.py:120`
- 但執行映射把這兩者都導向 `saas` calculator（語義與引擎不一致）。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/value_objects.py:16`
- `SkillRegistry` 目前沒有獨立 generic DCF / SOTP / NAV / rNPV calculator。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/registry.py:28`

外部驗證：
- 金融機構估值方法確實依行業差異；金融業常見 FCFE/股利框架。
  [Damodaran notes: Financial service firms & FCFE](https://pages.stern.nyu.edu/~adamodar/pdfiles/eqnotes/eqfin.pdf)
- 生技在研發管線估值常用 rNPV（風險調整 NPV）。
  [SpringerPlus review on rNPV in biotech/pharma](https://springerplus.springeropen.com/articles/10.1186/s40064-016-2893-6)

---

### E. 「動態市場與前瞻資料不足，折現率可能硬編碼」
**Verdict: 部分正確（Partially true, with outdated assumptions）**

代碼側證據（已做）：
- `MarketDataClient` 已抓 `current_price/market_cap/shares_outstanding/beta/risk_free_rate/consensus_growth`，含 retry+cache+fallback。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/data/clients/market_data.py:62`
- `time_alignment_guard` 已落地（warn/reject）。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builder.py:440`

代碼側證據（仍缺）：
- SaaS builder 目前 `wacc` 與 `terminal_growth` 還是 policy default。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py:210`

外部驗證：
- yfinance 官方聲明僅供 personal use，企業級需注意資料授權與穩定性。
  [yfinance PyPI legal disclaimer](https://pypi.org/project/yfinance/)

---

### F. 「REIT 應從 FFO 進一步走向 AFFO，且假設不可硬寫死」
**Verdict: 大方向正確；你們已部分落地（Largely true + partially implemented）**

代碼側證據：
- 估值圖已計算 maintenance capex 與 AFFO。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/engine/graphs/reit_ffo.py:1`
- `maintenance_capex_ratio` 已參數化，可由 market snapshot override。
  `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/reit.py:139`

外部驗證：
- Nareit 明確指出 AFFO 沒有統一定義（公司間不可直接橫比）。
  [Nareit glossary - AFFO](https://www.reit.com/investing/reit-glossary)

---

### G. 「應加強 MD&A/非結構化前瞻資訊」
**Verdict: 正確（True）**

代碼側觀察：
- 目前主流程已具 consensus growth，但尚未見到 MD&A / earnings call 文本抽取進入 param builder 的正式計算依賴。

外部驗證：
- SEC Item 303 對 MD&A 的要求本來就包含已知趨勢、不確定性與前瞻資訊。
  [17 CFR §229.303 (Item 303)](https://www.law.cornell.edu/cfr/text/17/229.303)

---

## 3) 對「是否已達企業級」的最終判定

**判定：已達「企業級基礎版（Enterprise-ready core）」但未達「機構級完備版（Institution-grade complete）」**。

你們在以下方面已超出一般團隊：
- Correlation-aware MC + PSD repair + diagnostics
- time-alignment guard
- traceable assumptions / provenance
- model-specific param builders（bank/reit/saas）

但若目標是 buy-side / risk committee 級別，仍需補：
1. **模型語義一致性**：把 `dcf_standard/dcf_growth` 從「命名」升級為「獨立引擎」。
2. **資料治理**：引入企業授權資料源（至少雙供應商）與 source confidence。
3. **前瞻資料管線**：把 MD&A / call transcript 的結構化輸出接進參數層。
4. **性能路線圖**：保留現有抽樣內核，逐步把 evaluator 轉 batch/vectorized。

---

## 4) 建議的下一步（按優先級）

1. **P0**: 修正 `model_selection -> calculator` 映射語義錯位（避免 DCF 名稱誤導）。
2. **P0**: 將 SaaS/Standard DCF 的 `wacc`、`terminal_growth` 改為 market-aware + policy clamp。
3. **P1**: 落地第二資料源與來源置信度欄位（含授權狀態）。
4. **P1**: 新增 MD&A/earnings call extraction output contract（先不進 MC，先進 assumptions）。
5. **P2**: 推進 evaluator 批量化，建立 iteration vs latency 壓測曲線。
