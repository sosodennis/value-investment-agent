# shared/kernel

## 職責定位

`kernel` 放的是**最底層、最穩定、可被全專案引用**的基礎能力。

它不承載任何特定 agent 的業務語義，也不應依賴外部 provider/client。

## 可以放什麼

1. 基礎型別與常數（例如 JSON type aliases、contract version constants）。
2. 可追溯基元（例如 `TraceableField` / provenance types）。
3. 與業務無關的純工具介面（例如 logging facade）。

## 不可以放什麼

1. 特定 agent 的 model/規則（fundamental/news/technical/debate 專屬語義）。
2. 外部服務客戶端與 SDK 綁定（例如 LLM provider、HTTP client）。
3. API/Artifact DTO 組裝與 parser（那是 interface 層責任）。

## 依賴規則

1. `kernel` 不應 import `src/agents/*`。
2. `kernel` 不應 import `src/infrastructure/*`。
3. 其他層可以依賴 `kernel`，但 `kernel` 自身保持最小依賴。

## 例子（概念）

1. `traceable`：審計與血緣（資料來源、計算公式、人工覆寫）。
2. `contracts/types`：跨層通用常數與型別別名。
