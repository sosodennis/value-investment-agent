# Ticket 02: market_data 子域化

## 目標

將市場數據 providers 與 snapshot 組裝遷移到 `market_data` 子域，移除舊路徑並清除未使用 providers。

## 範圍

- 遷移 `infrastructure/market_data/**` 到 `market_data/infrastructure/**`。
- 建立 `market_data/application` 服務層，對外提供 snapshot 組裝入口。
- 更新所有 import 指向新路徑。
- 清理未被引用的 provider 或 legacy 解析器。

## 依賴

- Ticket 01 完成。

## 主要影響檔案

- 舊 `finance-agent-core/src/agents/fundamental/infrastructure/market_data/**`
- 新 `finance-agent-core/src/agents/fundamental/market_data/infrastructure/**`
- 新 `finance-agent-core/src/agents/fundamental/market_data/application/**`

## 實作步驟

1. 遷移 market_data provider 與 snapshot 組裝邏輯。
2. 建立應用層入口與 ports。
3. 更新所有 import。
4. 移除舊路徑檔案。
5. `rg` 清點未使用 provider，刪除 legacy/unused。

## 驗收標準

- 所有 market_data 只從新子域輸出。
- 舊路徑完全移除，無 compat 代碼。
- 未使用 provider 已清理。

## 驗證

- `rg "market_data"` 指向新路徑。
- 依賴 market snapshot 的流程可啟動。

## 回退策略

- git revert 或回滾至前一切片。
