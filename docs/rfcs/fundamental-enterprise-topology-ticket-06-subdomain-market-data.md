# Ticket 06: Enterprise Topology — market_data 移入 subdomains

## 目標

將 `market_data` 子域移入 `fundamental/subdomains/`，完成所有 import 更新。

## 範圍

- `fundamental/market_data/**` → `fundamental/subdomains/market_data/**`
- 更新全庫對 `src.agents.fundamental.market_data.*` 的引用。

## 依賴

- Ticket 01、02 完成。

## 主要影響檔案

- `finance-agent-core/src/agents/fundamental/market_data/**`
- `finance-agent-core/src/agents/fundamental/application/wiring.py`
- 任何引用 market_data 的應用層服務

## 實作步驟

1. 移動 `market_data` 目錄至 `subdomains/`。
2. 更新全庫 import 至 `src.agents.fundamental.subdomains.market_data.*`。
3. legacy import sweep 清除舊路徑引用。

## 驗收標準

- 無任何 `src.agents.fundamental.market_data.*` 舊路徑引用。
- 子域位於 `fundamental/subdomains/market_data/`。

## 驗證

- `rg "agents\.fundamental\.market_data"` 僅指向新路徑。

## 回退策略

- 若需回退，回滾此子域移動與 import 更新。
