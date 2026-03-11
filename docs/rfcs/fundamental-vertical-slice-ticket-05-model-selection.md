# Ticket 05: model_selection 子域化

## 目標

將模型選擇規則、評分與解釋輸出遷移到 `model_selection` 子域，移除舊路徑。

## 範圍

- 遷移 `domain/model_selection*` 至 `model_selection/domain/**`。
- 遷移 `interface/report_projection_service.py` 至 `model_selection/interface/**`。
- 更新 DI/ports/import。
- 清理未被使用的 scoring/spec 規則。

## 依賴

- Ticket 01 完成。

## 主要影響檔案

- 舊 `finance-agent-core/src/agents/fundamental/domain/model_selection*`
- 舊 `finance-agent-core/src/agents/fundamental/interface/report_projection_service.py`
- 新 `finance-agent-core/src/agents/fundamental/model_selection/**`

## 實作步驟

1. 遷移 model selection 核心規則與 scoring。
2. 遷移 report projection service。
3. 更新 import 與 DI。
4. 刪除舊路徑檔案。
5. 清理 legacy/unused scoring 規則。

## 驗收標準

- model_selection 子域獨立可用。
- 舊路徑完全移除。
- 流程可正常取得 model selection 結果。

## 驗證

- `rg "model_selection"` 指向新子域。
- model selection 流程可完整跑通。

## 回退策略

- git revert 或回滾至前一切片。
