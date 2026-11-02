# Client debug capture

使用 client debug capture 來診斷只有瀏覽器才知道的 UI 問題，例如 viewport、component 位置、interaction state、動畫數值和 Performance Timeline 資料。

> Status: Implemented for issue #236. Keep this runbook focused on temporary page probes; remove those probes after the bug is fixed.

這是一條 runtime diagnostics channel。它不是產品 analytics、session replay，也不取代 Playwright。預設實作只使用 bounded process-local buffer 和 sanitized structured logs，不使用 PostgreSQL。

## 設計依據和驗證標準

這個工具刻意採用「短期、可關閉、低 cardinality、可關聯」的 diagnostics model：

- [OpenTelemetry Browser guide](https://opentelemetry.io/docs/languages/js/getting-started/browser/) 把 browser instrumentation 視為仍在演進的能力，並以 document-load、user-interaction、XHR 和 batch exporter 為典型工具。這個 helper 只提供低成本、手動 probe；需要完整 tracing 時，應改用正式 OTel pipeline。
- [W3C Trace Context Recommendation](https://www.w3.org/TR/trace-context/) 定義 `traceparent`/`tracestate` 的跨服務關聯方式，也要求不要把 PII 放入 trace context。這是為什麼 event 只接受 bounded correlation metadata，並禁止把 token、cookie 和 user content 放進 details。
- [MDN PerformanceObserver](https://developer.mozilla.org/en-US/docs/Web/API/PerformanceObserver) 定義從 browser Performance Timeline 觀察新 entry 的方法。performance probe 應使用 `PerformanceObserver`、User Timing 或 `getBoundingClientRect()`，不要用猜測的 wall-clock log 取代 browser measurement。

客觀驗收不依賴截圖主觀判斷，而是檢查以下可重複結果：OpenAPI 與 generated TypeScript 完全一致；disabled flag 下 endpoint 回傳 404 且 frontend 不發 request；enabled capture 的 event sequence/elapsed time 單調遞增；相同 event retry 只算 duplicate；foreign owner 讀取得到 404；敏感/DOM/input 欄位被拒絕或 redact；payload、queue、capture、TTL 上限可被測試觸發；同一 event 的 `request_id`/`traceparent` 可以在 structured log 中關聯。

## 選擇 runtime 模式

local 和 staging 使用 runtime-only mode。

- event 只在 backend process memory 保留短時間。
- backend 將 accepted event 寫成 structured log。
- backend restart 後 buffer 會消失。
- 不同 worker 或 replica 未必能看到另一個 process 建立的 capture。
- 不需要 database migration、table 或 cleanup job。

只有在需要 restart 後仍可讀取、跨 worker 讀取、長期比較或團隊共用時，才增加 shared sink。shared sink 是另一個 capability decision，不屬於這個 debug contract。

## 開啟 capture

在 local 或 staging configuration 開啟 backend flag：

~~~dotenv
CLIENT_DEBUG_CAPTURE_ENABLED=true
~~~

在 debug build 開啟 frontend flag：

~~~dotenv
NEXT_PUBLIC_ENABLE_CLIENT_DEBUG_CAPTURE=true
~~~

production 預設關閉兩個 flags。frontend helper 在 flag 關閉時會變成 no-op。

照常啟動 local stack：

~~~bash
docker compose up --build
~~~

打開包含問題的頁面。用 `debugCapture.captureId` 讀取 capture ID，並把它和 reproduction steps 一起保留。shared helper 不會自動把 capture ID 寫入 console。

## 加入 probe

在任何 page 或 component 中，只從 shared facade import 工具：

~~~ts
import { debugCapture } from '@/lib/client-debug';
~~~

使用一個 namespaced event name 和 JSON object 呼叫一個方法。helper 會自動加入 capture ID、event ID、sequence、client timestamps、route、viewport、scroll position、visibility state，以及可取得的 request correlation。

所有 page 共用同一個 facade。page code 不得直接 import queue、transport、redaction、buffer 或 API client，也不得直接呼叫 `/api/v1/client-debug/events`。這些細節由 `frontend/src/lib/client-debug/` 擁有。

保留的 public surface 只包括：

- `debugCapture.emit(name, details)`：加入一個 JSON debug event
- `debugCapture.flush()`：在測試或明確的 page lifecycle 邊界手動 flush
- `debugCapture.isEnabled`：只用於避免昂貴的 DOM measurement

不要讓 component 依賴 capture ID、batch timer、HTTP response 或 backend buffer 的實作細節。

~~~ts
debugCapture.emit('ui.layout', {
    target: 'valuation-distribution',
    rect: readRect(element),
    state: {
        isLoading,
        activeTab,
    },
});
~~~

使用穩定的 component name 和 target name。不要送 generated CSS selector、DOM path 或完整 element text。

helper 將 event 先放入 memory queue。它會在短 timer 或 batch 達到上限時送出；pagehide 時會重送尚未確認的 in-flight batch，並合併 queue 中可放入單一 48 KiB keepalive request 的 events。這是 best-effort terminal flush，超出單一 request budget 的 queue 尾端不保證送達。

## 記錄常見證據

需要知道 element 位置或尺寸時，記錄 layout snapshot：

~~~ts
debugCapture.emit('ui.layout', {
    target: 'results-panel',
    rect: readRect(resultsPanel),
    parentRect: readRect(resultsPanel.parentElement),
    computed: pickComputedStyle(resultsPanel, [
        'display',
        'position',
        'overflow',
        'visibility',
        'transform',
    ]),
});
~~~

把 interaction 記成短 causal sequence。記錄 action 前的 state、action 本身和 render 後的 state：

~~~ts
debugCapture.emit('interaction.before', {
    target: 'model-picker',
    state: { open: isOpen, selectedValue },
});

debugCapture.emit('interaction.click', {
    target: 'model-picker',
    pointer: { type: event.pointerType, x: event.clientX, y: event.clientY },
    defaultPrevented: event.defaultPrevented,
});

queueMicrotask(() => {
    debugCapture.emit('interaction.after', {
        target: 'model-picker',
        state: { open: isOpen, selectedValue },
    });
});
~~~

動畫只記錄 start、end 和少量 samples。不要上傳每一個 animation frame；60fps probe 應先在 client 取樣或降頻：

~~~ts
debugCapture.emit('animation.sample', {
    target: 'panel-transition',
    animationName: 'expand-panel',
    phase: 'running',
    elapsedMs,
    progress,
    computed: {
        height,
        opacity,
        transform,
    },
});
~~~

需要 browser timing 時，使用 PerformanceObserver 和 User Timing，而不是用 wall-clock log 猜測：

~~~ts
debugCapture.emit('performance.measure', {
    name: measure.name,
    durationMs: measure.duration,
    startTimeMs: measure.startTime,
});
~~~

capture 會記錄一次 browser capability snapshot。先查看 snapshot，再判斷某個 performance entry type 是否缺失。

## Event contract

frontend 將 batched events 傳到：

~~~http
POST /api/v1/client-debug/events
~~~

request 使用 client_debug.v1：

~~~json
{
  "schema_version": "client_debug.v1",
  "capture_id": "capture-uuid",
  "events": [
    {
      "event_id": "event-uuid",
      "sequence": 17,
      "occurred_at": "2026-11-02T10:15:20.123Z",
      "elapsed_ms": 842.4,
      "name": "ui.layout",
      "severity": "debug",
      "component": "WorkspaceOutputPanel",
      "context": {
        "route": "/workspace",
        "viewport": { "width": 1440, "height": 900, "dpr": 2 },
        "scroll": { "x": 0, "y": 220 },
        "visibility_state": "visible",
        "reduced_motion": false,
        "request_id": "request-id"
      },
      "details": {
        "target": "valuation-distribution",
        "rect": { "x": 112, "y": 384, "width": 968, "height": 420 }
      }
    }
  ]
}
~~~

details 是 flexible JSON。保持它小，只記錄解釋 reproduction 所需的 evidence。event name 使用以下 prefixes：

- ui.：layout、visibility、render state、component snapshot
- interaction.：pointer、keyboard、focus、state transition
- animation.：transition timing 和 computed animation values
- performance.：User Timing 和 Performance Timeline entries
- network.：sanitized request status 和 duration
- error.：client error 和 rejected state transition

endpoint 回傳 202 Accepted，並包含 accepted、duplicate 和 dropped counts。backend 加上 received_at、authenticated principal 和 server request ID。client 不能設定 ownership fields。

## 查看 capture

backend 提供 active process 內的 read endpoint：

~~~http
GET /api/v1/client-debug/captures/{capture_id}?after_seq=0&limit=200
~~~

read endpoint 不屬於 frontend workflow。若 read endpoint 暫時不可用，使用 capture ID 過濾 structured backend logs：

~~~bash
docker compose logs -f backend \
  | jq 'select(.event == "client_debug.event" and .capture_id == "capture-uuid")'
~~~

按 sequence 讀取 events。用 occurred_at 比較不同系統，用 elapsed_ms 重建 browser 內的順序。使用 request_id 或 traceparent 將 browser event 對到 backend logs 和 workflow activity。

## Collection limits

runtime mode 使用 bounded limits，避免 probe 阻塞 UI 或填滿 backend process：

- 每個 request 最多 50 events
- 每個 request 最大 256 KiB
- 每個 capture 最多 100,000 events；預設 4 MiB capture budget 讓單一 60fps sampler 有約一分鐘的實用窗口，實際時間取決於 event payload 大小
- 每個 capture 最多 4 MiB accounted memory；所有 active captures 共用 32 MiB accounted process budget。每個 event 按序列化 payload 大小加 512 bytes index allowance 計費，以包含 compact record、索引和 rate-window reference 的估算成本；這是有界估算，不等同 process RSS
- 每個 owner 最多 8 個 active captures
- 每個 owner 每分鐘最多 120,000 個 accepted events，使用 rolling 60-second window；8 個 60fps sampler 一分鐘只需要 28,800 events，因此 event quota 不會成為這個 profile 的先行瓶頸
- default in-memory TTL 是 24 小時
- client queue 上限是 2,000；健康 transport 下 client 每次 drain 最多送 8 個 50-event batches，足以排空 8 個 60fps sampler 的 480 events/s 等價負載；實際吞吐取決於 request latency
- animation samples 仍應由 client sampler 控制；需要更長或更密的 raw capture 時，先按 payload 大小調高 `CLIENT_DEBUG_MAX_BYTES_PER_CAPTURE`，但不超過 16 MiB，並確認 process budget

容量計算使用同一個公式：`accepted_events = sampler_count × samples_per_second × duration_seconds`。例如 8 × 60 × 60 = 28,800，低於預設 120,000/min。這只證明 rate admission；每個 event 還會按 `serialized_payload_bytes + 512` 計入 capture/process byte budget。以約 1 KiB accounted event 估算，4 MiB capture 約可保留 4,000 events，8 個 raw 60fps sampler 約 8 秒；要保留一分鐘，應降低 sampler rate、聚合 frame，或提高 capture byte budget。byte budget 是有意的硬界線，避免只調高事件數而讓 process memory 無界增長。

queue 或 capture 達到上限時，系統會丟棄新 events。server response 的 `dropped` 是該 batch 被拒收的總數，並同時提供 `dropped_rate_limited` 和 `dropped_capacity`，分別表示 rolling owner rate 與 per-capture/process event 或 byte budget。建立 capture 時遇到 active-capture quota 會回傳 429。client queue 滿載、pagehide terminal batch 超出 48 KiB，或非 retryable HTTP error 的丟棄不會計入 server counters。傳送不會阻塞 rendering。

## Privacy rules

不要收集以下資料：

- input values、passwords、tokens、cookies 或 authorization headers
- 完整 innerText、outerHTML 或 serialized DOM tree
- query strings、URL fragments 或 arbitrary request bodies
- 不需要解釋 bug 的 financial records 或 user-generated content
- 透過這個 endpoint 傳送 screenshots 或 video

client 會 redact 常見 sensitive keys。backend 也把 client details 視為 untrusted input，執行同樣的 redaction 並限制 size 和 depth。redaction 是最後一道防線，第一道防線是不收集敏感資料。

## 保留工具，移除除錯代碼

修正問題後：

1. 保留 `frontend/src/lib/client-debug/`、backend debug adapter、contract 和它們的 tests。
2. 移除所有 page 和 component 的 `debugCapture` imports。
3. 移除所有 page 和 component 的 `debugCapture.emit()` calls。
4. 移除只為 debug 建立的 measurement helper、temporary state、event-name constants 和 `data-debug-id` attributes。
5. 移除只為 debug 加入的 `useEffect`、event listener、`ResizeObserver`、`PerformanceObserver` 和 animation sampler。
6. 關閉兩個 debug feature flags。不要刪除 shared tool 的 flag 定義。
7. 搜尋 repository，確認沒有殘留 page-specific debug references：

~~~bash
rg -n "debugCapture|data-debug-id|client_debug\.v1|ui\.layout|interaction\.before|animation\.sample" frontend/src frontend/e2e
~~~

搜尋結果只可以包含 shared tool、contract tests、runbook 或仍然有效的正式測試。

8. 關閉 capture 後，重新執行一次原本的 workflow。
9. 執行 frontend checks：

~~~bash
cd frontend
npm run lint
npm run typecheck
npm run test -- --run
~~~

## Verification checklist

使用 capture 前，確認：

- capture ID 出現在 browser console。
- event 有預期的 route、viewport、component 和 target。
- sequence 和 elapsed_ms 都是 monotonic。
- retry 不會建立 duplicate event。
- layout rectangle 和 getBoundingClientRect() 的誤差在預期 pixel tolerance 內。
- event 能對到 backend request_id 或 traceparent。
- capture 沒有 input value、token、cookie、raw DOM 或不必要的 user content。
- investigation 完成後，debug flags 已關閉。
- 問題修復後，page-specific debug code 已刪除，shared debug tool 仍可供下一次除錯使用。

## 需要 runtime-only 以外的模式時

只有在以下情況才選 shared sink：

- reproduction 期間 backend 會 restart
- 多個 workers 或 replicas 必須讀取同一個 capture
- 另一位工程師需要稍後查看 capture
- captures 要跨 build 比較，或要成為 release gate

先針對這些需求選 dedicated log 或 telemetry sink，再考慮 PostgreSQL。只有當 capture 成為具備 owner、retention 和 authorization model 的 queryable product artifact 時，才使用 database。
