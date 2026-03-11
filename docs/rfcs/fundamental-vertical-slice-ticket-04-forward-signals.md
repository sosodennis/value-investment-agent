# Ticket 04: forward_signals 子域化

## 目標

將前瞻信號抽取、FinBERT、校準與信號政策遷移到 `forward_signals` 子域，移除舊路徑與兼容邏輯。

## 範圍

- 遷移 `forward_signals_text.py`、`finbert_direction.py`、signal scoring/calibration。
- 更新依賴與 contracts。
- 清理舊 signal pipeline 或 compat code。

## 依賴

- Ticket 01 完成。
- Ticket 03 之後進行更安全。

## 主要影響檔案

- 舊 `finance-agent-core/src/agents/fundamental/infrastructure/sec_xbrl/forward_signals_*`
- 舊 `finance-agent-core/src/agents/fundamental/domain/valuation/policies/forward_signal_*`
- 新 `finance-agent-core/src/agents/fundamental/forward_signals/**`

## 實作步驟

1. 遷移信號抽取與 scoring/calibration 邏輯到子域。
2. 更新 contracts 與 ports。
3. 刪除舊路徑與 compat。
4. 清理 legacy signal helpers。

## 驗收標準

- forward_signals 完全子域化，舊路徑移除。
- 估值流程可取得信號輸出。

## 驗證

- `rg "forward_signals"` 只指向新子域路徑。
- 信號輸出結構與流程一致。

## 回退策略

- git revert 或回滾至前一切片。
