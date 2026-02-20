# `fundamental` 重構 Sprint Tickets（可直接執行）

日期：2026-02-20
來源計畫：`/Users/denniswong/Desktop/Project/value-investment-agent/docs/research-paper/fundamental-enterprise-implementation-plan-2026-02-20.md`
估時單位：人日（Ideal Engineering Days）

## Sprint 規劃總覽

- Sprint 1（第 1-2 週）：市場資料接入 + 參數層基礎改造
- Sprint 2（第 3-4 週）：模型圖升級 + 蒙地卡羅核心
- Sprint 3（第 5 週）：整合測試 + 回測 + 文件化

總估時：約 `33` 人日（不含 TODO Enhancement）。

---

## Sprint 1（第 1-2 週）

| Ticket | 標題 | Priority | 估時 | 依賴 |
|---|---|---:|---:|---|
| FA-101 | 定義 `MarketSnapshot` schema 與 `MarketDataPort` | P0 | 1.0 | - |
| FA-102 | 實作 `market_data.py`（retry/backoff/timeout/error taxonomy） | P0 | 2.0 | FA-101 |
| FA-103 | 實作單位清洗與欄位正規化（含 `risk_free_rate`） | P0 | 1.0 | FA-102 |
| FA-104 | 實作快取層（短 TTL）與快取命中紀錄 | P1 | 1.0 | FA-102 |
| FA-105 | `param_builder` 接入 market data shares 優先序 | P0 | 1.5 | FA-101 |
| FA-106 | 移除/禁用 `market_cap / current_price` 反推股數路徑 | P0 | 0.5 | FA-105 |
| FA-107 | shares 來源 provenance 與差異告警閾值 | P1 | 1.0 | FA-105 |
| FA-108 | `GrowthBlender` 初版（context-aware 權重） | P0 | 2.0 | - |
| FA-109 | 均值回歸 guardrail（可配置） | P0 | 1.0 | FA-108 |
| FA-110 | Sprint 1 測試（unit + integration smoke） | P0 | 2.0 | FA-103, FA-107, FA-109 |

Sprint 1 小計：`13.0` 人日

### Ticket 驗收標準（Sprint 1）

`FA-101`
- `MarketSnapshot` 包含 `current_price`, `shares_outstanding`, `beta`, `risk_free_rate`, `consensus_growth_rate`, `target_mean_price`, `as_of`, `provider`。
- `data/ports.py` 有對應 interface，型別完整。

`FA-102`
- API 失敗分類至少含：`rate_limit`, `timeout`, `schema_missing`, `unknown`。
- 具 retry/backoff，錯誤訊息可觀測。

`FA-103`
- 利率統一轉為小數（例如 `4.25 -> 0.0425`）。
- 主要欄位缺失時不拋未處理 exception。

`FA-104`
- 同一 ticker 在 TTL 內重查命中快取。
- 可記錄 cache hit/miss。

`FA-105`
- shares 優先取 `market_data.shares_outstanding`。
- 無值時退回 XBRL `EntityCommonStockSharesOutstanding`。

`FA-106`
- 程式中不存在有效路徑會以 `market_cap / current_price` 反推股數。

`FA-107`
- 輸出可看出 shares 來源（live vs filing）。
- 來源差異超過閾值時有 warning。

`FA-108`
- 權重不再固定，會依情境改變。
- 權重與輸入來源可追溯。

`FA-109`
- Guardrail 可配置，非硬編碼固定值。

`FA-110`
- 新增單元測試與最小整合測試全數通過。

---

## Sprint 2（第 3-4 週）

| Ticket | 標題 | Priority | 估時 | 依賴 |
|---|---|---:|---:|---|
| FA-201 | `bank_ddm` 改為策略化 COE 輸入（先 CAPM） | P0 | 1.5 | FA-103 |
| FA-202 | `reit_ffo` 擴充 AFFO 近似與 `maintenance_capex_ratio` | P0 | 1.5 | FA-109 |
| FA-203 | `registry.py` 增加模型參數策略註冊位 | P1 | 1.0 | FA-201, FA-202 |
| FA-204 | 新增 `engine/monte_carlo.py`（Distribution + truncation） | P0 | 2.0 | - |
| FA-205 | 相關性抽樣（corr->cov + multivariate normal） | P0 | 2.0 | FA-204 |
| FA-206 | 共變異數 PSD 檢查與失敗保護 | P0 | 1.0 | FA-205 |
| FA-207 | seed 管理與可重現性控制 | P0 | 1.0 | FA-204 |
| FA-208 | 收斂診斷（分位數穩定性） | P1 | 1.5 | FA-205 |
| FA-209 | 串接 orchestrator（分佈輸出） | P0 | 1.5 | FA-205, FA-207 |
| FA-210 | Sprint 2 測試（模型 + MC 核心） | P0 | 2.5 | FA-201..FA-209 |

Sprint 2 小計：`15.5` 人日

### Ticket 驗收標準（Sprint 2）

`FA-201`
- `bank_ddm` 不再依賴硬編碼 COE。
- CAPM 路徑有 traceable input/provenance。

`FA-202`
- `maintenance_capex_ratio` 可配置，預設值由設定注入。
- AFFO 近似路徑可追溯。

`FA-203`
- 新策略可在 registry 註冊，不需改主流程分支。

`FA-204`
- 支援 `normal/triangular/uniform`，每種都可設 `min_bound/max_bound`。

`FA-205`
- 可輸入 correlation matrix 並完成抽樣。
- 抽樣結果維度、順序、命名一致。

`FA-206`
- 非合法協方差時能回傳明確錯誤或安全降級。

`FA-207`
- 固定 seed 的結果可重現。

`FA-208`
- 提供最小收斂指標（如 P50/P95 波動幅度）供判斷是否加大迭代。

`FA-209`
- 估值輸出包含 `P5/P50/P95`, `mean`, `iterations`, `seed`, `assumption_version`。

`FA-210`
- `saas/bank/reit_ffo` 至少各 1 組 E2E 情境通過。

---

## Sprint 3（第 5 週）

| Ticket | 標題 | Priority | 估時 | 依賴 |
|---|---|---:|---:|---|
| FA-301 | 擴充 output contract / mapper / view model | P0 | 1.5 | FA-209 |
| FA-303 | 回測腳本與基準資料集（最小版本） | P1 | 1.5 | FA-209 |
| FA-304 | Regression 測試與報表產出 | P1 | 1.0 | FA-303 |
| FA-305 | 文件化（runbook + 假設規格 + 測試說明） | P0 | 0.5 | FA-304 |

Sprint 3 小計：`4.5` 人日

### Ticket 驗收標準（Sprint 3）

`FA-301`
- 新欄位至少包含：`distribution_summary`, `assumption_breakdown`, `data_freshness`。

`FA-303`
- 可重跑固定樣本集，輸出新舊模型比較數據。

`FA-304`
- 產生最小 regression 報表（偏差、區間寬度、失敗案例）。

`FA-305`
- 文檔可支援新成員從 0 到可執行驗證流程。

---

## 優先級定義

- `P0`：核心路徑，缺一不可，直接阻斷企業級目標。
- `P1`：強烈建議本期完成，影響穩定性與可維運性。
- `P2`：可延後，不影響主流程可用。

---

## 建議執行順序（跨 Sprint 關鍵路徑）

1. FA-101 -> FA-102 -> FA-103 -> FA-105 -> FA-106
2. FA-108 -> FA-109 -> FA-202
3. FA-204 -> FA-205 -> FA-206 -> FA-207 -> FA-209 -> FA-301

---

## TODO Enhancement（延後實作，保留在 backlog）

| Ticket | 標題 | Priority | 估時 | 說明 |
|---|---|---:|---:|---|
| FA-901 | 行業均值 fallback 的高風險審批閘門 | P1 | 1.0 | 若 fallback 到行業均值，必須標記高風險並強制 HITL 審批，不可默默進最終計算。 |
| FA-902 | HITL 整合（審批頁欄位與人工覆核 workflow） | P1 | 1.5 | 將高風險假設、來源與審批決策串進 HITL 節點，並支援明確拒絕/退回。 |
