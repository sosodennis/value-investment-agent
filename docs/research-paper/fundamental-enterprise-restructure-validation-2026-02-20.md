# `finance-agent-core/src/agents/fundamental` 企業級重構方案外部驗證報告

日期：2026-02-20
範圍：針對你提出的 6 個核心問題與重構主張，對照公開權威資料（監管、學術、產業機構、主流實務）進行驗證。

## 1) 總結判定

結論不是「完全正確」，而是「方向正確，但有幾個關鍵細節需要修正」。

| 問題 | 架構師主張 | 驗證結果 |
|---|---|---|
| 1 | 需補動態市場資料與前瞻共識 | 正確（高可信） |
| 2 | 歷史 CAGR 外推有後視鏡偏誤，需融合/均值回歸 | 正確（高可信），但固定權重需校準 |
| 3 | Shares Outstanding 需用最新值，不能只靠 XBRL | 正確（高可信），但反推股數有技術風險 |
| 4 | 金融/REIT hard-code 需去除，改動態計算 | 部分正確：方向對，部分公式過於剛性 |
| 5 | Yahoo Finance 可對應抓取關鍵欄位 | 部分正確：欄位多數可取，但穩定性/授權/單位需加防護 |
| 6 | 升級 Monte Carlo 是企業級關鍵 | 正確（高可信），但目前示意版未達企業級控制標準 |

---

## 2) 逐題驗證

## 問題 1：是否需要「動態市場資料 + 前瞻資料」？

### 驗證
- SEC 10-K/10-Q 是定期揭露，不是即時流資料；財報有申報週期與時滯。
  來源：SEC Investor.gov（10-K/10-Q 說明）
- 企業估值實務中，前瞻假設若只用歷史會失真，需納入外部預期與情境。
  來源：McKinsey 對高增長估值與假設偏誤的討論

### 判定
`正確`。僅靠 XBRL 歷史值不足以支持即時估值決策。

### 修正建議
- 新增 `MarketDataClient` 是合理且必要。
- 但要把「資料時點」與「來源可信度」放入 provenance（例如 quote timestamp、provider、latency）。

---

## 問題 5：Yahoo Finance 欄位映射是否成立？

### 驗證
- Yahoo 的 `financialData`/相關模組常見欄位包含 `currentPrice`、`targetMeanPrice`、`revenueGrowth` 等。
  來源：Yahoo Query 文件
- `yfinance` 官方 README 明確提醒：API 非官方、僅供研究/教育，並提示需遵守 Yahoo 使用條款。
  來源：`yfinance` GitHub README

### 判定
`部分正確`。你列的大多欄位「通常可抓到」，但不能把其視為穩定契約。

### 需要修正的點
- 欄位可用性會依 ticker、市場、時間變化，必須做 schema 驗證與 null/型別防護。
- `^TNX` 類指標的單位/換算不可硬寫，應做單位檢查與來源比對。
- 生產環境不宜單點依賴 Yahoo；至少要有 fallback provider（例如官方債券殖利率源、商業資料源）。

---

## 問題 3：Shares Outstanding 時差問題是否嚴重？

### 驗證
- SEC/XBRL 的 shares 資訊是「申報時點/報告時點」揭露，不等於當下交易日最新股本。
  來源：SEC Data Quality 說明（shares outstanding 標籤語意）
- 市值的基本公式為 `Market Cap = Price × Shares Outstanding`，可作 fallback 反推。
  來源：Investor.gov 詞彙表

### 判定
`正確`。若只用財報股數，回購/增發期間會造成每股價值偏差。

### 需要修正的點
- `market_cap / current_price` 反推股數可能混入「稀釋口徑差異、盤中價格波動、不同供應商定義差」。
- 建議優先序：`live sharesOutstanding` > `最新 filing/cover page shares` > `反推`，並加入容差檢查（例如與上期差異超過閾值則觸發告警）。

---

## 問題 2：Growth rate 後視鏡偏誤與 Blender 設計

### 驗證
- 分析師預測存在系統性偏誤，且具景氣循環偏差（景氣差時過度樂觀、復甦時又偏保守）。
  來源：Bank of England Working Paper 648
- 長期估值若不做競爭與均值回歸，容易高估持續高成長/高回報。
  來源：McKinsey（ROIC 長期回歸）
- 「融合分析師預測與模型」有文獻支持能改善準確度。
  來源：Eastern Economic Journal（analyst + model 組合）

### 判定
`正確（方向）`，但你提出的固定權重 `30/50/20` 不是通用最優。

### 需要修正的點
- 權重應該做產業/市場 regime 校準（rolling backtest），不建議全市場固定常數。
- 「歷史 CAGR > 30% 就強制均值回歸」可當 guardrail，但應改為可配置規則（依產業波動與競爭結構調整）。

---

## 問題 4：銀行與 REIT 特化 hard-code

### 銀行（Bank DDM / Residual Income）

#### 驗證
- 金融機構估值常以股東權益與股利/殘餘收益視角，且 `cost of equity` 是核心。
  來源：Damodaran《Valuing Financial Service Firms》
- CAPM 在銀行研究中是常見估計法之一。
  來源：NY Fed Staff Report 854

#### 判定
`部分正確`。移除硬編碼很正確；把 CAPM 納入可追溯節點也正確。
但 CAPM 應是「預設方法之一」，不是唯一方法（可擴充多因子/隱含成本資本）。

### REIT（FFO -> AFFO）

#### 驗證
- Nareit 明確指出 FFO 是非 GAAP 補充指標，不等同可分配現金流；AFFO 亦屬調整概念且業界無單一定義。
  來源：Nareit FAQ 與 Glossary

#### 判定
`部分正確`。升級到 AFFO 方向非常對；但 `Maintenance CapEx = Depreciation * 0.8` 缺乏通用標準，不能當硬規則。

### 需要修正的點
- REIT 的維持性資本支出應做「可配置假設 + 來源註記 + 敏感度區間」，而非固定單一係數。
- 對銀行成本資本保留 model registry（CAPM / multifactor / implied COE），由審核層決定採用方案。

---

## 問題 6：蒙地卡羅升級是否是正確方向？

### 驗證
- IFRS 13 的公平價值框架支持期望現金流與機率加權技術。
  來源：IFRS 13 Illustrative Examples
- ASC 820 實務（Deloitte 說明）也明確包含 Monte Carlo simulation 作為可用估值技術之一。
  來源：Deloitte Fair Value Measurement Roadmap

### 判定
`正確（高可信）`。從單點估值升級到分佈估值是企業級能力的關鍵。

### 需要修正的點（目前示意碼尚未達企業級）
- 只做獨立抽樣不夠：需要參數相關性（correlation matrix / copula）。
- 需要分佈邊界控制（例如 growth、margin、rate 的經濟合理區間）。
- 需要可重現性（seed 管理）、收斂診斷、尾部檢查、性能優化（向量化或批次運行）。
- 報告輸出應包含 `P5/P50/P95`、輸入敏感度分解與假設版本號。

---

## 3) 對你目前重構計畫的最終評語

你的架構師方案可作為「企業級升級藍圖」，但若要說「完全正確」還不夠精確。
最關鍵的修正有 4 點：

1. `Yahoo` 只能當資料源之一，不能當唯一真相來源（授權、可用性、欄位漂移）。
2. `risk-free` 與其他市場欄位要做單位/時點正規化，不可硬編碼換算。
3. 銀行 CAPM 與 REIT 維持性 CapEx 都應採「可配置策略」，非單一硬規則。
4. Monte Carlo 必須加入相關性、治理與診斷，才符合企業級風控要求。

---

## 4) 參考來源（外部驗證）

- SEC Investor.gov: How to Read a 10-K/10-Q
  https://www.sec.gov/answers/reada10k.htm
- SEC Data Quality (shares outstanding 標籤語意提醒)
  https://www.sec.gov/data-research/structured-data/sec-data-quality-monitoring#3.1.7
- yfinance README（非官方/條款提醒）
  https://github.com/ranaroussi/yfinance
- Yahoo Query docs（Yahoo finance modules/fields）
  https://yahooquery.dpguthrie.com/guide/ticker/modules/
- Investor.gov（Market Capitalization 定義）
  https://www.investor.gov/introduction-investing/investing-basics/glossary/market-capitalization
- Nareit Glossary（AFFO）
  https://www.reit.com/what-reit/glossary-terms
- Nareit REIT Industry FAQs（FFO 限制）
  https://www.reit.com/data-research/reit-industry-faqs
- NY Fed Staff Report 854（CAPM 在銀行資本成本研究）
  https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr854.pdf
- Damodaran（Valuing Financial Service Firms）
  https://pages.stern.nyu.edu/~adamodar/pdfiles/papers/finfirm09.pdf
- Bank of England WP 648（分析師預測偏誤）
  https://www.bankofengland.co.uk/-/media/boe/files/working-paper/2017/analyst-forecast-errors-and-macroeconomic-risk-an-overlooked-source-of-analyst-forecast-biase.pdf
- Eastern Economic Journal（組合分析師預測與模型）
  https://link.springer.com/article/10.1057/eej.2015.13
- McKinsey（高成長與長期回歸估值討論）
  https://www.mckinsey.com/capabilities/strategy-and-corporate-finance/our-insights/valuing-high-growth-tech-companies
  https://www.mckinsey.com/capabilities/strategy-and-corporate-finance/our-insights/are-you-doing-the-right-kind-of-valuation
- IFRS 13 Illustrative Examples（機率加權/期望現金流）
  https://www.ifrs.org/content/dam/ifrs/publications/html-standards/english/2025/issued/ifrs13-ie.html
- Deloitte ASC 820 Roadmap（Monte Carlo simulation 技術）
  https://dart.deloitte.com/USDART/home/publications/deloitte/fair-value-measurement-roadmap/chapter-12-valuation-techniques/12-7-scenario-based-techniques
