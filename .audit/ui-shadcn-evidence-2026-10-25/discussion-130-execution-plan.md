## 決定：逐頁執行 shadcn/ui 重構

依本討論採用的 shadcn/ui、語義 tokens 和頁面建議，逐頁替換現有呈現元件；執行追蹤放在 parent issue [#150](https://github.com/sosodennis/value-investment-agent/issues/150)。範圍是 `/`、`/login`、`/register`、`/workspace`、`/settings/llm`、`/settings/search` 和 `/technical-observability`。

- 先完成共享 primitives、主題和 app shell：[#151](https://github.com/sosodennis/value-investment-agent/issues/151)。
- #151 VERIFIED 後，以兩個隔離 worktree 並行處理頁面。Lane A：[#152](https://github.com/sosodennis/value-investment-agent/issues/152)、[#153](https://github.com/sosodennis/value-investment-agent/issues/153)、[#154](https://github.com/sosodennis/value-investment-agent/issues/154)、[#156](https://github.com/sosodennis/value-investment-agent/issues/156)。Lane B：[#155](https://github.com/sosodennis/value-investment-agent/issues/155)、[#157](https://github.com/sosodennis/value-investment-agent/issues/157)、[#158](https://github.com/sosodennis/value-investment-agent/issues/158)。
- 最後由 integration owner 完成 [#159](https://github.com/sosodennis/value-investment-agent/issues/159)：刪除已無呼叫者的舊 UI 元件，並驗收七個 routes。

所有頁面遵守本討論與 `docs/frontend-guideline.md`：保留 auth、REST/SSE、parser/view-model 和 workflow contracts；不偽造即時金融資料；沿用專用金融圖表和 schema-driven form engine。每個 issue 都要檢查 diff、測試、Docker health 和實際行為，標記 VERIFIED 後才 merge 和 close。
