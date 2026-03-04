# Cross-Agent Refactor Lessons and Execution Playbook

日期: 2026-03-03
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
11. Repository 混入 projection/聚合責任
   - 症狀: repository adapter 同時做 artifact I/O 與 domain entity projection。
   - 做法: repository 只負責 save/load；projection/aggregation 回到 application/domain owner service。
12. Workflow state boundary 型別誤收斂
   - 症狀: 為消除 `object` 而把 LangGraph 異質 state 邊界過度抽象，反而增加認知負擔。
   - 做法: 保留 `Mapping[str, object]` 在 workflow entry；在 `state_readers` 立即正規化為 typed 值，避免 raw state 向內層擴散。
13. Async use-case 中的同步外部呼叫阻塞
   - 症狀: 在 `async` 流程內直接 `invoke()` / sync SDK call，導致 event loop 被阻塞、整體延遲放大。
   - 做法: 優先使用 async API；若上游僅提供 sync API，邊界層使用 `asyncio.to_thread(...)` 包裝。
14. Degraded 流程可觀測性不足
   - 症狀: 只看到 `is_degraded=true`，但不知道在哪個階段、因何降級、影響範圍多大。
   - 做法: 對 degraded path 補 dedicated structured warning log，固定帶 `error_code`、`degrade_source`、`fallback_mode`、`input/output_count`。
15. Artifact 缺失被靜默視為空資料
   - 症狀: repository 在 artifact 缺失時回傳 `[]/{}/\"\"`，造成流程「偽成功」並掩蓋 root cause。
   - 做法: repository/read-boundary 必須顯式拋出 not-found failure；由 use-case 明確決定 terminal/degraded。
16. 高頻 async provider 每次請求都新建 client/session
   - 症狀: 每篇/每次呼叫都建立 `AsyncClient`（或同類 session），延遲與資源開銷偏高。
   - 做法: provider 層重用 client/session，並提供顯式 close hook 於應用 shutdown 清理。
17. Provider 失敗語義只有 `None`
   - 症狀: 外部請求失敗只回傳 `None`，use-case 無法區分原因與影響，容易出現「狀態健康但品質下降」。
   - 做法: provider 回傳 typed failure payload（如 failure_code/http_status/reason）；use-case 依此計算 degraded 指標與錯誤摘要。
18. Interface → Application 反向依賴
   - 症狀: `interface` mappers/projection 依賴 `application` DTO/service，導致層邊界倒置、重構時高耦合。
   - 做法: boundary mapping/prompt/rendering 保留在 `interface`；workflow/app context mapping owner 放在 `application`。
19. Completion log 只覆蓋 happy path
   - 症狀: 有 `started` 但只有成功分支有 `completed`，early return / error 分支缺 completion summary，導致節點終態不可觀測。
   - 做法: 每個 terminal return path（success/waiting/error）都要打同一個 completion event，固定帶 `status`/`is_degraded`/`error_code`（若有）。
20. Deterministic 與 Monte Carlo 基準案例不一致
   - 症狀: point intrinsic 顯示上漲，但 distribution 顯示 current 已高於 P95（或反向矛盾）。
   - 做法: MC evaluator 必須滿足「zero-shock base case = deterministic point」；任何裁剪/guard 都不能改變 base 值，並且記錄 `base_case_intrinsic_value` 供運行時核對。
21. 估值方法論 gate 缺失（企業級可靠性）
   - 症狀: 模型可跑但無法快速驗證是否滿足方法論一致性（cash-flow/discount-rate/terminal/scenario/reproducibility）。
   - 做法: 每個估值模型至少具備 5 個 gate：`cash_flow_basis 明確`、`terminal r>g guard`、`discount-rate 與 cash-flow 口徑一致`、`風險以 scenario/distribution 表達`、`Monte Carlo 可重現且輸出 diagnostics`。
22. Entity/Domain Service 責任漂移
   - 症狀: 單一實體狀態可完成的 deterministic 邏輯被拆成多個薄 `*_service.py`，造成跳檔與低內聚；或跨實體協調被硬塞入 entity 造成模型臃腫。
   - 做法: 單一 aggregate/value-object 的無 I/O 規則優先收斂在 model owner；跨實體/跨聚合協調保留 domain service。
23. 重計算路徑缺少性能 gate
   - 症狀: Monte Carlo/WFA 類能力在重構後功能不壞，但延遲明顯退化且缺乏可重現對照基準。
   - 做法: 建立固定 seed/window/iterations 的可重現性能基線，並加回歸門檻；async use-case 中以邊界 offload 避免阻塞 event loop。
24. Workflow context 契約與實際讀寫漂移
   - 症狀: `workflow/state.py` 保留舊欄位，或缺少當前 use-case 已寫入欄位，導致跨 agent 協作時型別與語義脫節。
   - 做法: 每次切片同步比對 `state_updates`/reader/consumer 與 context 定義；新增欄位就入契約，無 writer/consumer 的欄位立即刪除，不保留兼容占位。
   - 補充: canonical 欄位（例如 `intent_extraction.resolved_ticker`）不得再鏡像回 root `ticker`。
25. Workflow context 過度鏡像（payload duplication）
   - 症狀: state context 同時保存 artifact 中已有的大量衍生欄位（例如 summary/metrics/details），導致 checkpoint 冗餘與維護成本上升。
   - 做法: context 只保留 orchestration 需要的最小欄位與 artifact pointer；展示/分析細節由 artifact preview/full payload 承載。

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
