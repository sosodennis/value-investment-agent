# Fundamental 估值分佈呈現 UI/UX 外部驗證（2026-02-20）

## 1. 問題
在 `fundamental` 估值輸出中，蒙地卡羅分佈結果應該優先用哪種呈現：
- A. 鐘形曲線（分佈圖）
- B. 三情境卡片（Bear / Base / Bull）

## 2. 外部來源（網路驗證）
1. Bank of England, Ben Bernanke Review（2024）
   - [Forecasting and monetary policy making at the Bank of England](https://www.bankofengland.co.uk/report/2024/forecasting-and-monetary-policy-making-at-the-bank-of-england)
2. UK Analysis Function（ONS/Civil Service）
   - [Showing uncertainty](https://analysisfunction.civilservice.gov.uk/policy-store/showing-uncertainty/)
3. Nature Scientific Reports（2022）
   - [Visualizing uncertainty in model predictions with an interactive exploration tool](https://www.nature.com/articles/s41598-022-12195-4)
4. Publications Office of the European Union
   - [Data visualisation guide: uncertainty and confidence intervals](https://data.europa.eu/apps/data-visualisation-guide/uncertainty-and-confidence-intervals)

## 3. 交叉驗證結論

### 結論 A：只用單一圖形不夠，分層呈現更穩健
- Bernanke Review 指出 fan chart 類型在實務上對溝通效果有限，建議輔以替代情境敘述。
- ONS 指南也強調不確定性資訊要依受眾能力分層，不宜只靠一種視覺型式。

### 結論 B：三情境卡片的可讀性更高，適合預設第一層
- 三情境（悲觀/基準/樂觀）可快速建立決策框架，對非量化使用者更友善。
- 對產品流程而言，也更符合「先可理解，再可深入」的互動順序。

### 結論 C：分佈圖仍有必要，但應作為第二層細節
- Nature 研究顯示，相較單點估計，呈現分佈可改善使用者在不確定情境下的判斷。
- EU 指南建議在顯示區間與不確定性時，需搭配清晰註解與一致視覺編碼，避免誤讀。

## 4. 推薦 UI/UX 方案（最終）
採用 **Hybrid（混合式）**：
1. 第一層（預設）：三情境卡片（Bear/Base/Bull + 對應價格）。
2. 第二層（按需展開）：鐘形分佈曲線，標示 P5/P50/P95。
3. 文案提示：曲線區塊標註「用於觀察尾部風險」，避免被誤解為精確預測。

## 5. 已落地的前端調整
- 檔案：`/Users/denniswong/Desktop/Project/value-investment-agent/frontend/src/components/agent-outputs/FundamentalAnalysisOutput.tsx`
- 變更：
  - 以三情境卡片為主要預設視圖。
  - 新增 `Show Curve / Hide Curve` 交互，將鐘形曲線改為按需展開。
  - 保留 P5/P50/P95 參考線與 Tooltip，支援尾部風險閱讀。

## 6. 決策
本次外部驗證結果支持：
- **不是「鐘形曲線 vs 三卡片」二選一**，
- 而是 **「三卡片優先 + 曲線進階」** 的分層設計，整體可讀性與專業性最佳。
