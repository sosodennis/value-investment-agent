# Ticket 01: Shared Kernel 與垂直切片骨架

## 目標

建立垂直切片的基礎結構與 shared kernel，確保 `TraceableField/Provenance` 有唯一來源，並移除舊路徑定義。

## 範圍

- 新增 `fundamental/shared/contracts/traceable.py`，成為唯一 Traceable/Provenance 定義位置。
- 建立所有子域骨架與 `application/domain/infrastructure/interface` 目錄。
- 更新全庫對 Traceable/Provenance 的 import 指向 shared kernel。
- 移除舊路徑內的 traceable 定義與相容層。

## 依賴

- 無前置依賴。

## 主要影響檔案

- 新增 `finance-agent-core/src/agents/fundamental/shared/contracts/traceable.py`
- 新增 `finance-agent-core/src/agents/fundamental/core_valuation/`
- 新增 `finance-agent-core/src/agents/fundamental/financial_statements/`
- 新增 `finance-agent-core/src/agents/fundamental/forward_signals/`
- 新增 `finance-agent-core/src/agents/fundamental/model_selection/`
- 新增 `finance-agent-core/src/agents/fundamental/market_data/`
- 新增 `finance-agent-core/src/agents/fundamental/artifacts_provenance/`
- 新增 `finance-agent-core/src/agents/fundamental/workflow_orchestrator/`
- 移除舊 Traceable/Provenance 定義檔案與引用

## 實作步驟

1. 建立 shared kernel 檔案並遷移 Traceable/Provenance 定義。
2. 建立子域目錄骨架與最低限度的 `__init__.py`。
3. 全庫更新 import 指向 shared kernel。
4. 刪除舊路徑中 Traceable/Provenance 定義。
5. 搜索並清除 compat/legacy/import shim。

## 驗收標準

- Traceable/Provenance 只存在於 `fundamental/shared/contracts/traceable.py`。
- 全庫無任何舊路徑 traceable import。
- 子域骨架已建立，無相容層或 re-export 留存。

## 驗證

- `rg "TraceableField|Provenance"` 應只指向 shared kernel 定義。
- 基本 lint/typecheck 可執行。

## 回退策略

- 如需回退，使用 git revert 或回滾至重構前版本。
