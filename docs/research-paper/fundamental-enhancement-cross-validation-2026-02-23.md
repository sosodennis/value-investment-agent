# Fundamental Enhancement 報告交叉驗證（Review vs Validated）

**Date**: 2026-02-23
**Compared Files**:
- `docs/research-paper/fundamental-enhancement-review-report.md`
- `docs/research-paper/fundamental-enhancement-1-validated-report-2026-02-23.md`

---

## 核心衝突與判定

### 1) 「模型覆蓋缺口」判定衝突
- `review-report`：判定「完全正確（缺標準 DCF）」
- `validated-report`：判定「部分正確」

**交叉驗證結果**：`validated-report` 較精確。
理由：選模層已存在 `dcf_standard` / `dcf_growth`，但執行映射仍導向 `saas` calculator，屬於「語義存在、引擎未對齊」而非完全不存在。

代碼證據：
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/model_selection.py:120`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/value_objects.py:16`
- `/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/registry.py:28`

---

### 2) 「折現率已完全動態化」說法不一致
- `review-report`：偏向認定「WACC/CAPM 已動態，不是 hardcoded」
- `validated-report`：指出「部分動態，部分仍 default」

**交叉驗證結果**：`validated-report` 較精確。
理由：Bank 路徑 CAPM 參數確實動態，但 SaaS builder 仍使用 policy default 的 `wacc` / `terminal_growth`。

代碼證據：
- 動態市場資料：`/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/data/clients/market_data.py:62`
- SaaS default：`/Users/denniswong/Desktop/Project/value-investment-agent/finance-agent-core/src/agents/fundamental/domain/valuation/param_builders/saas.py:210`

---

### 3) 「是否已達企業級投行標準」口徑衝突
- `review-report`：語氣偏「已達投行級」
- `validated-report`：判定「Enterprise-ready core，但非 Institution-grade complete」

**交叉驗證結果**：`validated-report` 較穩健。
理由：仍存在資料授權單點、模型語義/引擎錯位、非結構化前瞻資料未入主流程等關鍵缺口。

---

## 不確定主張的外部驗證

### A) yfinance 是否可作企業級正式數據源？
**結論**：不宜單獨作為企業正式主源。
證據：yfinance 專案頁明確提示 Yahoo Finance API intended for personal use only，並要求遵循 Yahoo 條款。
- Source: [yfinance on PyPI](https://pypi.org/project/yfinance/)

---

### B) REIT 的 AFFO 是否標準化？
**結論**：非標準化（公司間可比性需謹慎）。
證據：Nareit 明確寫「There is no standardized definition of AFFO」。
- Source: [Nareit AFFO glossary](https://www.reit.com/glossary/adjusted-funds-operations-affo)

---

### C) MD&A 是否屬於必要前瞻訊號來源？
**結論**：是。
證據：SEC 對 Item 303 的解釋明確要求揭露已知趨勢/不確定性（reasonably likely material impact）。
- Source: [SEC Commission Statement on MD&A (2002)](https://www.sec.gov/rules-regulations/2002/01/commission-statement-about-managements-discussion-analysis-financial-condition-results-operations)

---

### D) Nearest-PSD / nearest-correlation 是否屬金融業標準技術路徑？
**結論**：是。
證據：Higham 經典論文即以金融相關矩陣修復為背景，定義 nearest correlation matrix（PSD + unit diagonal）。
- Source: [Higham 2002 paper](https://eprints.maths.manchester.ac.uk/232/1/paper3.pdf)

---

## 最終綜合判定

1. 兩份報告主方向一致，但 `validated-report` 在語義精度與風險揭露上更嚴謹。
2. `review-report` 不是錯，但有兩個口徑過強：
   1. 把「缺標準 DCF」定性為完全缺失（忽略了選模層已有 DCF 類型）。
   2. 把「折現率動態化」描述得過滿（SaaS 路徑仍有 default）。
3. 企業級結論建議採用：**「核心能力已企業級，但尚未達機構完備級」**。
