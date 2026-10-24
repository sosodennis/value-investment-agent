# 企業級 Technical Analysis (TA) Agent 評估與升級藍圖

## 1. 執行摘要 (Executive Summary)

本報告針對 `finance-agent-core/src/agents/technical` 模組進行了深度的靜態代碼分析，並結合華爾街量化機構（如 AQR、Two Sigma 等）與 Marcos López de Prado 在《Advances in Financial Machine Learning》中提出的高階特徵工程標準，對當前的實作進行了「企業級成熟度」評估。

**整體方向評估：正確且極具潛力**
當前系統採用了「神經符號 (Neuro-Symbolic)」架構，這是一個非常優秀的設計模式：
1. **Symbolic (符號邏輯/演算法)：** 利用明確的數學公式（如分數階微分 Fractional Differentiation、經典指標）來捕捉市場的物理特徵，保證了數學上的嚴謹性與可重現性。
2. **Neuro (神經網絡/LLM)：** 將確定性的統計訊號（Semantic Tags 如 `SETUP_PERFECT_STORM_SHORT`, `SMART_MONEY_EXITING`）交由 LLM 生成人類可讀的解讀，並設有 Guardrail（防護欄）防止 LLM 產生幻覺。

這種結合了「量化嚴謹性」與「AI 解釋性」的架構，完全符合現代企業級輔助交易系統的發展方向。

然而，在**細節實作（Implementation Details）**與**穩健性（Robustness）**上，目前的代碼仍有明顯的「實驗室原型」痕跡，特別是在型態識別（Pattern Detection）模組中大量使用了硬編碼（Hardcoded）的靜態閾值，這在面對不同波動率特性的資產（如加密貨幣 vs. 公用事業股）或極端市場狀態（閃崩、黑天鵝）時，將會產生大量的假訊號（False Positives）或直接失效。

---

## 2. 當前實作的弱點分析 (Vulnerability & Gap Analysis)

經過代碼審查，以下是阻礙當前系統達到「企業級」標準的主要痛點：

### 2.1 致命弱點：靜態閾值與硬編碼 (Static Thresholds & Magic Numbers)
在 `pattern_detection_service.py` 中，算法高度依賴絕對的靜態百分比來定義支撐/壓力與趨勢：
*   **支撐/壓力位分群 (Clustering)：**
    ```python
    tolerance_pct: float = 0.02
    bin_size = max(abs(last_price) * tolerance_pct, 1e-6)
    ```
    *問題：* 2% 的容差對於 S&P 500 ETF (SPY) 來說可能極大（包含數個月的波動），但對於高波動科技股（如 TSLA）或加密貨幣來說卻太小。這會導致在低波動市場無法識別精細的支撐，而在高波動市場識別出過多無意義的雜訊。
*   **價格接近度 (Proximity Flags)：**
    ```python
    proximity_pct: float = 0.015
    tolerance = abs(last_price) * proximity_pct
    ```
    *問題：* 同樣的問題，固定 1.5% 的接近度缺乏動態適應能力。
*   **趨勢線斜率 (Trendline Slope)：**
    ```python
    slope_threshold: float = 0.0005
    ```
    *問題：* 斜率的絕對值會隨著資產價格的絕對大小和 timeframe 而劇烈變化，使用一個魔術數字（0.0005）來區分趨勢和盤整（Sideways）是不科學的。

### 2.2 演算法缺陷：缺乏市場狀態過濾 (Missing Market Regime Filter)
目前的 `signal_fusion` 和指標計算將所有市場視為同質。但在真實交易中，指標的有效性取決於 **市場狀態 (Market Regime)**：
*   在**趨勢市場 (Trending Regime)** 中，均線（SMA/EMA）和 MACD 突破非常有效，但 RSI 的超買/超賣會持續給出錯誤的反轉訊號。
*   在**盤整市場 (Mean-Reverting/Sideways Regime)** 中，RSI 和 Bollinger Bands 的邊界回歸非常準確，但均線交叉會產生大量的「雙面耳光（Whipsaws）」虧損。
*   *現狀：* 系統缺乏對大盤或個股目前處於何種 Regime（高/低波動、趨勢/盤整）的自動識別，這會導致 Semantic Tags 在不適合的環境下給出錯誤的置信度。

### 2.3 數據維度缺失：機構級籌碼指標 (Missing Institutional Indicators)
雖然系統正確地將非量價數據（新聞、基本面）剝離，但在純 TA 領域，仍缺少機構常用的兩個關鍵視角：
1.  **Volume Profile (籌碼分佈 / VPVR)：** 目前系統只有基於時間的成交量（MFI, OBV），缺乏基於**價格**的成交量分佈。Volume Profile 是識別真實「機構建倉區 (Value Area)」和「流動性真空區 (Liquidity Voids)」的黃金標準，比單純找歷史價格高低點（Peak/Trough）的支撐壓力要準確得多。
2.  **Order Flow Imbalance (微觀結構 / 選用)：** 雖然 L2 數據對輔助系統來說可能過於龐大，但由高低收盤價推導的 Tick Volume 或買賣力量失衡（如 VWAP 偏離度進階分析）可以顯著增強短線突破的勝率。

---

## 3. 企業級升級藍圖 (Enterprise Upgrade Blueprint)

為了將這個 Agent 從「優秀的原型」提升到「可靠的企業級輔助交易系統」，建議採取以下三階段的升級：

### Phase 1: 波動率自適應重構 (Volatility-Adjusted Refactoring)
**目標：消除所有靜態閾值，使系統對所有資產類別「免調參 (Parameter-less)」。**

1. **引入 ATR (Average True Range) 作為基礎動態標尺：**
   *   修改 `pattern_detection_service.py`。不再使用 `tolerance_pct = 0.02`。
   *   *企業級解法：* 計算過去 14 天的 ATR（或使用 GARCH 預測波動率）。將支撐/壓力的容差設定為 ATR 的一個倍數。
   *   *範例：* `bin_size = max(current_atr * 0.5, 1e-6)`。這表示支撐區間的厚度會隨著市場近期的波動率自動膨脹或收縮。
2. **動態斜率閾值：**
   *   將 `slope_threshold` 改為透過統計檢驗（如線性迴歸的 R-squared 或 p-value）來確定趨勢的顯著性，而不是依賴斜率的絕對值。
   *   *企業級解法：* 如果斜率的 t-stat 顯著且 R² > 0.6，才標記為 `UPTREND` 或 `DOWNTREND`，否則為 `SIDEWAYS`。

### Phase 2: 導入市場狀態識別 (Market Regime Identification)
**目標：讓 Agent 知道「現在該用什麼武器」，提高 Semantic Tags 的準確率。**

1. **開發 Regime Filter 模組：**
   *   實作一個隱馬可夫模型 (Hidden Markov Model, HMM) 或基於 ADX (Average Directional Index) 與 Historical Volatility 的啟發式分類器。
   *   將當前市場分類為：`BULL_TREND`, `BEAR_TREND`, `HIGH_VOL_CHOP` (高波動震盪), `QUIET_MEAN_REVERSION` (低波動盤整)。
2. **條件式訊號融合 (Conditional Signal Fusion)：**
   *   修改 `policy_service.py`。當識別到 `HIGH_VOL_CHOP` 時，系統應自動**降低**所有突破訊號（Breakout）的權重，並增加 RSI/Bollinger 極端值的反轉權重。
   *   當處於強趨勢時，抑制反轉訊號，防止出現過早摸頂/抄底的錯誤建議。

### Phase 3: 引入高級流動性視角 (Advanced Liquidity Profiling)
**目標：與華爾街機構看齊，提供真正具有深度的輔助圖表數據。**

1. **實作 Volume Profile (VPVR)：**
   *   在 `features` 模組中新增 `volume_profile_service.py`。
   *   將一段時間內的成交量分配到各個價格區間（Price Bins），找出 Point of Control (POC, 成交最密集價位) 以及 Value Area High/Low (包含 70% 總成交量的區間)。
2. **增強 Support / Resistance 的邏輯：**
   *   將現有的 `find_peaks` (價格幾何極值) 與 Volume Profile 的 POC (真實籌碼堆積區) 進行交集驗證。
   *   只有當一個幾何低點同時也是籌碼密集區時，才賦予其最高的 `confidence_score`。

---

## 4. 結論 (Conclusion)

目前的 `technical` Agent 在架構設計（Neuro-Symbolic）、高階特徵工程（Fracdiff）與防護欄設計上已經具備了極高的水準，甚至超越了許多市面上的開源專案。

只要針對 **「靜態閾值動態化 (ATR-based)」** 與 **「市場狀態感知 (Regime Filter)」** 這兩個痛點進行重構，並補足 **Volume Profile**，這個系統就能完全達到甚至超越企業級的輔助交易標準，為交易員提供高度穩健、抗雜訊且統計顯著的洞察。
