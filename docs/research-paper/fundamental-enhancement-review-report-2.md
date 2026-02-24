# Fundamental Agent 架構升級 Review 報告 (第二階段)

**Date**: February 24, 2026
**Subject**: 審查自 2026-02-23 以來針對 Fundamental Agent 的架構更新與優化

根據近期的 codebase 提交 (Commit: `02e2492e64f9f3be1aa9682a81b9138f6874746b`)，我們對 Fundamental Agent 進行了一次全面的代碼和架構複查。以下是針對最近的優化項目、發現的錯誤方向以及未來改進建議的詳細報告。

---

## 總結 (Executive Summary)

本次更新在**非結構化資料提取 (MD&A)** 與**宏觀數據動態化 (FRED 整合)** 取得了巨大進展，這兩個強化使得我們的系統真正具備了前瞻性 (Forward-looking) 與宏觀經濟敏感度。

然而，在**估值模型擴展 (Standard DCF)** 與**蒙地卡羅效能 (Monte Carlo Vectorization)** 上，目前的實作僅停留在「過渡性與介面層」的修改，核心的演算法與效能瓶頸並未被徹底解決（錯誤的方向 / 未完成的特性）。

---

## 1. 成功優化的亮點 (Successful Optimizations)

### ✅ 前瞻性信號與非結構化文本分析 (Forward Signals & MD&A)
- **實作觀察**: 新增了 `forward_signals_text.py`。這個模組利用 `edgar` 函式庫精準抓取 10-K (Item 7), 10-Q (Item 2), 8-K 等財報及新聞稿的「管理層討論與分析 (MD&A)」。
- **架構評價**: 這是一個**史詩級的增強**。系統現在能夠使用正規表達式與關鍵字（如 "margin expansion", "raised guidance" 等）提取管理層的預期，並轉化為定量的 `bps` 訊號。這完美解決了先前架構師提到的「純粹依賴歷史冷數據」的痛點。

### ✅ 宏觀數據的動態整合 (FRED Integration)
- **實作觀察**: 在 `docker-compose.yml` 中加入了 `FRED_API_KEY`，並在 `market_providers.py` 中看到了 FRED API 的準備。
- **架構評價**: 引入聯準會經濟數據庫 (FRED) 代表系統未來的的無風險利率 (Risk-Free Rate) 和總體經濟變量將具備機構級的精確度和實時性，進一步鞏固了我們在宏觀數據動態獲取上的優勢。

---

## 2. 錯誤的發展方向與問題 (Wrong Directions & Issues)

### ❌ DCF 模型的「假實作」 (Transitional Implementation)
- **問題描述**: 我們新增了 `dcf_standard` 和 `dcf_growth` 這兩個維度的 Valuation Skills。然而，查看它們的 `tools.py` 原始碼：
  ```python
  def calculate_dcf_standard_valuation(params: DCFStandardParams):
      # Transitional implementation:
      # reuse existing FCFF graph while keeping an explicit dcf_standard skill boundary.
      return calculate_saas_valuation(params)
  ```
- **架構評價**: 這是一個**錯誤的方向**。雖然在套件結構（Clean Architecture 邊界）上我們區分了這些技能，但在核心邏輯上，這兩個新模型依然底層呼叫的是 `calculate_saas_valuation`。這意味著：
  - 它們依然帶著 SaaS 行業特有的巨額 SBC (股權激勵) 邏輯。
  - 它們依然**缺乏嚴格的多階段穩定器 (Multi-Stage Stabilization)**（如營收增長率線性遞減、資本支出收斂至折舊、ROIC 等於 WACC 的永續期限制）。
  - 這是一種「技術債」，在 Frontend 看起來我們支援了標準 DCF，但計算出的內在價值依然是過度特化的 SaaS 倒 U 型曲線邏輯，這會對成熟企業產生嚴重的估值誤差。

### ❌ 蒙地卡羅效能瓶頸依舊 (Monte Carlo Bottleneck Remains)
- **問題描述**: 雖然 Commit 訊息提到 "enhance Monte Carlo simulations with new sampler options"，但進入 `domain/valuation/engine/monte_carlo.py` 的 Evaluation Loop 檢查：
  ```python
  for idx in range(executed_iterations, batch_end):
      ...
      outcomes[idx] = float(evaluator(inputs))
  ```
- **架構評價**: 取樣層的確使用了 NumPy，但是**求值迴圈 (Evaluator Loop) 依然是純粹的串行 Python 迴圈**。對於 10,000 次的模擬，這仍會引發 10,000 次獨立的 Python `calculate` 函式呼叫。這在高並發環境下會嚴重拖慢 Agent 的回應速度。真正的向量化 (Vectorization) 應該是 `outcomes = evaluator(inputs_matrix)`，將整個計算推入 C/NumPy 執行緒中。

---

## 3. 進一步改善的建議 (Future Improvements)

為了解決上述技術債並達到真正的企業級，建議採取以下 P0/P1 行動：

1. **[P0] 真正落實 Multi-Stage DCF 數學引擎**:
   - 必須停止使用 `calculate_saas_valuation` 作為 `dcf_standard` 的底層 Wrapper。
   - 撰寫一個全新的 `standard_dcf_graph`，該演算法必須內置**過渡期 (Transition Period)**的線性收斂數學公式（通常是第 6 至 10 年，利潤率與增長率逐步逼近永續均值）。

2. **[P1] Monte Carlo 求值層向量化 (Vectorized Evaluation)**:
   - 重構 Valuation Engine，使其支援傳入 List/Array 級別的參數。
   - 利用 `pandas` 向量化運算或 `numpy` broadcasting，改寫 FCFF 與 Equity Value 的計算流程，消滅單步 `for` 迴圈。一旦實作成功，10,000 次模擬的計算時間將從秒級降為微秒級。

3. **[P2] 利用 LLM 增強 MD&A 訊號萃取**:
   - 目前的 `forward_signals_text.py` 是基於正規表達式與關鍵字命中 (Pattern Matching)。未來可以整合一個輕量級的 SLM (Small Language Model) 進行 Semantic Analysis，這會比純關鍵字比對帶來更高的精準度（降低 False Positives）。
