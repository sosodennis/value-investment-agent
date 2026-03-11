# Ticket 03: financial_statements 子域化

## 目標

將 XBRL 解析、財報 canonicalization 與 diagnostics 遷移到 `financial_statements` 子域，移除舊路徑。

## 範圍

- 遷移 `infrastructure/sec_xbrl/**` 到 `financial_statements/infrastructure/**`（不含 forward_signals）。
- `interface/parsers.py` 移到 `financial_statements/interface/parsers.py`。
- 更新 ports/contracts/import。
- 清理未使用的 XBRL helpers。

## 依賴

- Ticket 01 完成。

## 主要影響檔案

- 舊 `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/**`
- 新 `finance-agent-core/src/agents/fundamental/financial_statements/infrastructure/**`
- 舊 `finance-agent-core/src/agents/fundamental/interface/parsers.py`
- 新 `finance-agent-core/src/agents/fundamental/financial_statements/interface/parsers.py`

## 實作步驟

1. 遷移 XBRL extraction 與 report canonicalization 邏輯。
2. 更新 parser 合約與 import。
3. 移除舊路徑。
4. 清理 legacy/unused XBRL helpers。

## 驗收標準

- 財報相關邏輯只存在於 `financial_statements` 子域。
- 舊 `sec_xbrl` 路徑移除，無 compat 代碼。
- parser 合約可被上層流程正常使用。

## 驗證

- `rg "sec_xbrl"` 指向新路徑。
- financial health 流程可正常解析報表。

## 回退策略

- git revert 或回滾至前一切片。
