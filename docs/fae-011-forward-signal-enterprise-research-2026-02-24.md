# FAE-011 調研與落地範圍（Enterprise Baseline vs. Our Scope）

日期：2026-02-24
對應 Ticket：FAE-011（Forward signal contract：MD&A / earnings call -> assumptions）

---

## 1) 結論先行

FAE-011 的方向是正確的，但企業級實作不只是「加一個文字信號欄位」。
最小合規且可審計的做法應包含：

1. 信號必須結構化（值、信心、證據、來源、時間）。
2. 信號只能透過 policy 影響 assumptions，不能直接覆寫硬財務欄位。
3. 每個信號都要可追溯到公開披露來源與片段（evidence）。
4. 需要可觀測診斷（採納/拒絕原因、影響幅度、風險等級）。

我們本次建議的 FAE-011 實作範圍會做到上述 1-4，但不做 HITL workflow（依既定 TODO）。
另外本階段採用 **edgartools + SEC 公開來源**，不引入商業 API。

---

## 2) 外部基準：企業級通常怎麼做（已查證）

## A. 監管披露語義（為什麼 MD&A/公開電話會議可用）

1. SEC Regulation S-K Item 303（MD&A）要求披露管理層視角下的流動性、資本資源、經營結果，且包含已知趨勢與不確定性。
來源：
- [17 CFR 229.303 (LII)](https://www.law.cornell.edu/cfr/text/17/229.303)
- [SEC 2002 MD&A Commission Statement](https://www.sec.gov/rules-regulations/2002/01/commission-statement-about-managements-discussion-analysis-financial-condition-results-operations)

2. SEC 2020 MD&A modernization（Release 33-10890）確認 MD&A 的原則導向與資訊價值。
來源：
- [SEC Final Rule 33-10890](https://www.sec.gov/rules-regulations/2020/11/managements-discussion-analysis-selected-financial-data-supplementary-financial-information)

## B. 公開資訊與選擇性揭露風險（Reg FD）

1. Reg FD 要求重大非公開資訊若被對外揭露，故意揭露需同步公開，非故意需 promptly 公開。
來源：
- [17 CFR 243.100 (Reg FD)](https://www.law.cornell.edu/cfr/text/17/243.100)

2. 8-K Item 2.02 的 C&DI 指出，對 earnings call 的資訊可透過公開方式（例如網頁可取得 transcript）滿足公開揭露要求。
來源：
- [SEC C&DI, Form 8-K Compliance & Disclosure Interpretations](https://www.sec.gov/rules-regulations/staff-guidance/compliance-disclosure-interpretations/form-8-k-compliance-disclosure-interpretations)

## C. 模型風險治理（金融機構企業級核心）

1. SR 11-7 / OCC 2011-12 定義 model risk，要求模型有健全治理、驗證、用途邊界與持續監控。
來源：
- [Federal Reserve SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)
- [OCC 2011-12 (model risk management)](https://occ.gov/news-issuances/bulletins/2011/bulletin-2011-12.html)

2. BCBS 239 要求風險資料的 accuracy/integrity、adaptability、reporting accuracy。這直接對應我們的 evidence/provenance 與 assumption diagnostics。
來源：
- [BCBS 239 (Principles for effective risk data aggregation and risk reporting)](https://www.bis.org/publ/bcbs239.pdf)

## D. 資料管線可行性與限制

1. SEC 提供 EDGAR full-text search / API 能力，足夠做 MD&A 與 8-K 文字提取。
來源：
- [SEC Filings search tools](https://www.sec.gov/search-filings)
- [SEC EDGAR full text search](https://www.sec.gov/edgar/search-and-access)

2. SEC Fair Access 提醒 automated request 節流（常見實務上限 10 req/s）。
來源：
- [SEC: Accessing EDGAR Data](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

---

## 3) 由外部基準推導出的 FAE-011 企業級設計原則

1. `Source-of-truth priority`：優先採用 issuer 公開披露（10-K/10-Q/8-K、官方 IR 公開資料），次要來源只作輔助。
2. `Policy-mediated influence`：forward signal 不可直接覆寫財報硬數；只能產生 bounded assumption adjustment。
3. `Evidence-first`：每個 signal 都要有 evidence（原文片段、來源 URL、as_of、段落定位）。
4. `Risk-tagged`：低信心或來源品質低的信號必須帶高風險標記。
5. `Auditability`：輸出層需可追到「哪些信號被採納、影響幾 bps、為何拒絕」。

---

## 4) 我們目前狀態（repo）與缺口

目前已具備：

1. assumptions 分層與 growth blend 基礎（`assumptions.py`）。
2. assumption_breakdown / data_freshness / risk flags 在 preview contract 已可顯示。
3. MC diagnostics、time alignment guard、provenance 相關能力已在主流程。

主要缺口（FAE-011 要補）：

1. 尚無 `forward_signal` 的正式 contract。
2. 尚無「signal -> bounded assumption adjustment」的 policy engine。
3. 尚無結構化 evidence packet 進入 assumption_breakdown。
4. 尚無 forward signal 採納/拒絕診斷欄位。

---

## 5) FAE-011 我們建議做到的程度（可落地版本）

## In Scope（本次實作）

0. 資料來源邊界：僅使用 `edgartools` + SEC 公開資料（10-K/10-Q/8-K），不接商業 transcript API。

1. 新增 forward signal contract（至少含）：
- `signal_id`
- `source_type`（`mda`, `earnings_call`, `press_release`, `news`）
- `metric`（`growth_outlook`, `margin_outlook`, `capex_outlook`, `credit_cost_outlook`）
- `direction`（`up`, `down`, `neutral`）
- `value`（建議用 bps 或 normalized score）
- `confidence`（0-1）
- `as_of`
- `evidence`（`text_snippet`, `source_url`, `doc_type`, `period`）

2. assumptions 層新增 policy：
- 只產生 `adjustment_growth` / `adjustment_margin` 這類「調整量」。
- 設 hard bounds（例如 growth 調整 ±300 bps）。
- 低信心（例 `<0.55`）標記 `high_risk_assumption`，可納入但降權。

3. 輸出可視化與審計欄位：
- assumption_breakdown 增加 `forward_signal_summary`。
- 顯示採納數、拒絕數、總影響（bps）、最高風險來源。

4. 日誌事件：
- `forward_signal_policy_applied`
- `forward_signal_rejected`
- `forward_signal_missing`

## Out of Scope（本次不做）

1. HITL 審批狀態機與人工審批 UI（依你既定 TODO）。
2. 商業 transcript provider 接入與端到端 transcript 爬蟲平台化。
3. 直接把 forward signal 併入 MC 隨機變數（先進 assumptions，再到後續 enhancement）。

---

## 6) 建議實作藍圖（對應檔案）

1. `finance-agent-core/src/agents/fundamental/domain/valuation/assumptions.py`
- 新增 `ForwardSignal` / `ForwardSignalEvidence` dataclass 或 pydantic model。
- 新增 `apply_forward_signals_to_assumptions(...)`。
- 新增 `ForwardSignalPolicyResult`（採納/拒絕/調整量/風險標記）。

2. `finance-agent-core/src/agents/fundamental/interface/contracts.py`
- 新增 preview contract 欄位：
  - `forward_signal_summary`
  - `forward_signal_risk_level`
  - `forward_signal_evidence_count`

3. `finance-agent-core/src/agents/fundamental/application/orchestrator.py`
- 在計算前組裝 forward signal payload（可先吃 state 中既有 research/debate 輸出）。
- 統一記錄 policy log event。

4. `finance-agent-core/src/agents/fundamental/application/fundamental_service.py`
- 將 `ForwardSignalPolicyResult` 寫入 `assumption_breakdown`。
- 將高風險信號與拒絕原因回傳到 preview。

5. `finance-agent-core/src/agents/fundamental/data/clients/sec_xbrl/**`（邊界約束）
- 不修改既有 XBRL 財務欄位提取與 mapping 流程（zero-intrusion）。
- Forward signal 作為旁路訊號，僅進 assumptions policy。

---

## 7) 驗收標準（建議）

1. 合約層：輸出 JSON 含 `forward_signal_summary`，且欄位型別穩定。
2. 邏輯層：forward signals 只影響 assumptions，不覆蓋 `financial_reports` 原值。
3. 風險層：低信心信號必有高風險標記，並帶 evidence。
4. 可觀測性：log 能看到採納/拒絕統計與總調整 bps。
5. 回歸層：無 forward signal 時行為與現狀一致（退化安全）。

---

## 8) 建議里程碑（FAE-011 內部拆分）

1. FAE-011A（0.8d）：Contract + DTO + parser schema。
2. FAE-011B（1.0d）：Policy engine + assumptions integration。
3. FAE-011C（0.7d）：orchestrator/service 接線 + logs + tests。

總計：2.5d（與原 ticket 估時一致）。

---

## 9) 待你 review 的決策點

1. `confidence` 門檻預設值是否用 `0.55`（低於即高風險）？
2. 本版先只允許影響 `growth/margin`，還是加上 `capex/credit_cost`？
3. evidence 是否要求最少 1 條 snippet + URL 才可採納？

---

## 10) 參考來源（本次調研）

1. SEC Item 303（MD&A）：[17 CFR 229.303](https://www.law.cornell.edu/cfr/text/17/229.303)
2. SEC 2002 MD&A statement：[SEC Commission Statement](https://www.sec.gov/rules-regulations/2002/01/commission-statement-about-managements-discussion-analysis-financial-condition-results-operations)
3. SEC MD&A final rule 33-10890：[SEC Rule Page](https://www.sec.gov/rules-regulations/2020/11/managements-discussion-analysis-selected-financial-data-supplementary-financial-information)
4. Reg FD：[17 CFR 243.100](https://www.law.cornell.edu/cfr/text/17/243.100)
5. 8-K C&DI：[SEC Form 8-K C&DIs](https://www.sec.gov/rules-regulations/staff-guidance/compliance-disclosure-interpretations/form-8-k-compliance-disclosure-interpretations)
6. Model risk governance：[FRB SR 11-7](https://www.federalreserve.gov/supervisionreg/srletters/sr1107.htm)
7. OCC 對應發布：[OCC Bulletin 2011-12](https://occ.gov/news-issuances/bulletins/2011/bulletin-2011-12.html)
8. Risk data governance：[BCBS 239](https://www.bis.org/publ/bcbs239.pdf)
9. EDGAR search/access：[SEC search filings](https://www.sec.gov/search-filings)
10. EDGAR API/fair access：[SEC APIs & fair access](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)
