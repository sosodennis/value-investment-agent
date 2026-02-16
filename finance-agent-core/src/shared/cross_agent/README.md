# shared/cross_agent

## 職責定位

`cross_agent` 放的是**跨 2 個以上 agent 共用**、且仍保持業務中立的能力。

它是 agent 之間協作的「交換層」，不是任何單一 agent 的內部實作區。

## 可以放什麼

1. 跨 agent 共用的中立 domain model（例如 `CompanyProfile`）。
2. 跨 agent 共用的 data/application base（例如 generic typed port base）。
3. 跨 agent 協作時的中立 policy/helper（不含單一 agent 決策規則）。

## 不可以放什麼

1. 單一 agent 專用語義（只被一個 agent 使用就不應放這裡）。
2. 直接 import `src/agents/<name>/...` 的型別或 contracts。
3. 顯示層/UI 導向 formatter 或 API-specific DTO。

## 升格規則（避免 shared 膨脹）

1. 至少被 2 個以上 agent 使用。
2. 語義中立，不綁單一 agent。
3. 變更頻率相對穩定，不是短期實驗碼。

## 依賴規則

1. `cross_agent` 不應依賴任一 `src/agents/*`。
2. 可以依賴 `shared/kernel`。
3. interface/infrastructure 可依賴 `cross_agent`，反向不成立。

## 例子（概念）

1. `market_identity`：公司身份資料（ticker/name/sector/industry）。
2. `typed_artifact_port`：跨 agent 統一 artifact 讀寫入口（generic base）。
