# Ticket 01: Enterprise Topology — Shared Kernel 轉移至 domain/shared

## 目標

將 Fundamental 的 shared kernel 收斂至 `fundamental/domain/shared/`，並清除所有舊路徑引用。

## 範圍

- 建立 `fundamental/domain/` 與 `fundamental/domain/shared/`。
- 將 `fundamental/shared/contracts/traceable.py` 移至 `fundamental/domain/shared/contracts/traceable.py`。
- 全庫更新 `src.agents.fundamental.shared.*` 相關 import 至新路徑。
- 刪除舊 `fundamental/shared/` 目錄（不保留相容層）。

## 依賴

- 無前置依賴。

## 主要影響檔案

- `finance-agent-core/src/agents/fundamental/shared/**` → `finance-agent-core/src/agents/fundamental/domain/shared/**`
- 所有引用 `src.agents.fundamental.shared.*` 的檔案（含其他 agent，例如 `debate`）

## 實作步驟

1. 建立 `fundamental/domain/shared/contracts/` 與對應 `__init__.py`。
2. 移動 `traceable.py` 並調整 `__init__.py` export。
3. 全庫替換 import 路徑至 `src.agents.fundamental.domain.shared.*`。
4. 移除 `fundamental/shared/` 舊目錄。
5. 執行 legacy import sweep，確保舊路徑無殘留。

## 驗收標準

- 全庫不再引用 `src.agents.fundamental.shared.*`。
- shared kernel 僅存在於 `fundamental/domain/shared/`。
- 無相容層或 re-export。

## 驗證

- `rg "agents\.fundamental\.shared"` 無結果。
- 目標子集測試（若有）：與 traceable 有關的測試。

## 回退策略

- 若需回退，回滾本 ticket 內所有移動與 import 更新。
