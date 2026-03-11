# Ticket 02: Enterprise Topology — Root application 與 workflow orchestrator 重定位

## 目標

將 cross‑subdomain orchestration 移入 root `application/`，並把 `workflow_orchestrator` 的 interface 移至 root `interface/`。

## 範圍

- 建立 `fundamental/application/` 與 `fundamental/interface/`。
- 移動：
  - `fundamental/subgraph.py` → `fundamental/application/subgraph.py`
  - `fundamental/wiring.py` → `fundamental/application/wiring.py`
  - `fundamental/workflow_orchestrator/application/` → `fundamental/application/workflow_orchestrator/`
  - `fundamental/workflow_orchestrator/interface/` → `fundamental/interface/workflow_orchestrator/`
- 更新所有呼叫端 import（含 `workflow/graph.py` 與 `workflow/nodes/fundamental_analysis/nodes.py`）。
- 移除舊 `workflow_orchestrator/` 根目錄（不保留相容層）。

## 依賴

- Ticket 01 完成（shared kernel 路徑穩定）。

## 主要影響檔案

- `finance-agent-core/src/agents/fundamental/subgraph.py`
- `finance-agent-core/src/agents/fundamental/wiring.py`
- `finance-agent-core/src/agents/fundamental/workflow_orchestrator/**`
- `finance-agent-core/src/workflow/graph.py`
- `finance-agent-core/src/workflow/nodes/fundamental_analysis/nodes.py`

## 實作步驟

1. 建立 `fundamental/application/` 與 `fundamental/interface/`。
2. 移動 `subgraph.py` 與 `wiring.py` 至 root `application/`。
3. 移動 `workflow_orchestrator/application` 至 `application/workflow_orchestrator/`。
4. 移動 `workflow_orchestrator/interface` 至 `interface/workflow_orchestrator/`。
5. 全庫更新 import 指向新路徑。
6. 刪除舊 `workflow_orchestrator/` 根目錄。
7. legacy import sweep 確保舊路徑無殘留。

## 驗收標準

- `workflow_orchestrator` 不再出現在 root 層級。
- `subgraph.py` 與 `wiring.py` 位於 root `application/`。
- 所有引用已更新且無相容層。

## 驗證

- `rg "agents\.fundamental\.workflow_orchestrator"` 僅出現於新路徑。
- `rg "agents\.fundamental\.subgraph|agents\.fundamental\.wiring"` 僅出現於新路徑。
- 跑 orchestrator 相關測試（例如 `test_fundamental_orchestrator_logging.py`）。

## 回退策略

- 若需回退，回滾本 ticket 內所有移動與 import 更新。
