# Cross-Agent Refactor Lessons and Execution Playbook

日期: 2026-03-02
範圍: `finance-agent-core/src/agents/*`
狀態: Active
搭配規範: `cross_agent_class_naming_and_layer_responsibility_guideline.md`

本文件只保留「可執行經驗」。硬規則以 cross-agent standard 為唯一來源，避免重複維護。

## 1. 反覆出現的反模式（精簡版）

1. Canonical owner 不清楚
   - 症狀: 同一契約在多層重定義，欄位語義漂移。
   - 做法: 指定單一 canonical owner，其他層只做 mapping/projection。
2. Compatibility 長期滯留
   - 症狀: alias/shim 長期並存，路徑混亂。
   - 做法: 每個 compatibility 必須有移除切片；遷移完成即刪除。
3. Layer 邊界污染
   - 症狀: domain/application 引入 infra 或 prompt/transport 關注。
   - 做法: 嚴格按層分責，prompt spec/rendering 留在 interface。
4. God module 與 generic bucket
   - 症狀: `helpers.py/tools.py/services.py` 混合多能力。
   - 做法: 依 capability owner 拆分，入口檔只做 orchestration。
5. Runtime 依賴傳遞失控
   - 症狀: use-case 鏈路傳遞大量 `*_fn` callables。
   - 做法: 收斂為 typed runtime ports，由 wiring 注入。
6. 邊界型別過寬
   - 症狀: mature port 仍大量 `object`。
   - 做法: 用最小 typed contracts（保持簡潔，不過度抽象）。
7. Narrative 文字驅動控制流
   - 症狀: 用 assumptions/log 字串決定流程。
   - 做法: 只用 typed decision fields 做控制流。
8. 錯誤契約漂移
   - 症狀: 不同 agent/node 的 error update shape 不一致。
   - 做法: 統一 contract 與測試守衛。
9. State reader 例外外洩
   - 症狀: optional 中間態解析錯誤直接使 use-case 終止。
   - 做法: state reader 回傳 `None`，由 use-case 決定 recoverable/terminal。
10. Preview projection owner 漂移
   - 症狀: `interface/mappers` 反向依賴 `application/view_models.py`。
   - 做法: preview projection 統一放在 `interface/preview_projection_service.py`，再交由 formatter 輸出。

## 2. 標準重構切片流程（每批固定）

1. Slice 定義
   - 指定 capability owner、要刪除的 legacy 路徑、驗收條件。
2. 先收斂邊界，再搬實作
   - 先定 ports/contracts 與 package owner，再搬 call sites。
3. 原子遷移
   - 同一批完成主要 call sites；避免長期雙路徑。
4. 驗證三件套
   - `ruff check`
   - targeted tests（能力相關）
   - import hygiene scan/tests（防回流）
5. 文檔同步
   - 更新 blueprint/tracker（做了什麼、驗證、是否偏離計畫）。
6. 偏離管理
   - 如偏離原計畫，必須記錄原因與取捨（可維護性/可讀性/風險）。
7. 收尾
   - 移除 compatibility residue，補 guard 測試。

## 3. 何時更新 standards

僅在以下情況更新 standards：

1. 發現「新類型」反模式（可跨 agent 重複出現）。
2. 現有規則無法阻止已發生的回歸。
3. 規則可以被寫成可檢查的 gate（lint/test/checklist）。

不更新 standards 的情況：

1. 只是單一檔案的實作細節。
2. 不能跨 agent 泛化的案例。
3. 會引入過多抽象或增加認知負擔的規則。

## 4. 文檔維護策略（降負擔）

1. 規範唯一來源: cross-agent standard。
2. 本 playbook 只記「反模式類型 + 落地流程」。
3. 每次重構最多新增一條新反模式，並嘗試合併既有重複條目。
4. 任何新條目都必須回答兩件事：
   - 是否能跨 agent 泛化？
   - 是否能被自動檢查或明確 checklist 驗證？
