# SSE transport probe

This probe compares browser delivery from a standalone FastAPI and LangGraph service through three paths: direct browser access, a Next.js Route Handler, and a Next.js rewrite. It checks incremental event delivery, ordered IDs, terminal frames, resume after disconnect, and cookie authentication. It does not change the production app.

## Finding

Keep the production browser-to-FastAPI REST/SSE boundary. The current project uses direct browser requests, a custom fetch reader, and a FastAPI `StreamingResponse`; the local tests found no reason to add Next.js as a proxy for SSE alone.

Do not use a Next.js rewrite as an SSE route without a stream-specific no-transform header and a deployed-path smoke test. The production `/stream/{thread_id}` route currently omits `Cache-Control` and `X-Accel-Buffering`. With those headers omitted, Next.js 16.1.0 compressed rewrite responses and delivered all events at once in every run. Native FastAPI SSE responses also buffered through rewrites on Next.js 16.1.0 and 16.4.2. Direct browser requests and Route Handler responses remained incremental.

Adding `Cache-Control: no-cache, no-transform` to the stream response fixed the rewrite in five runs on both Next.js versions. Disabling Next.js compression also fixed the rewrite, but changes compression for the whole Next.js server. If Next.js must enforce same-origin session access, hold a server-only secret, or apply server-side policy, use a Route Handler and verify that it preserves the upstream body stream and required headers.

FastAPI added its native `EventSourceResponse` and `ServerSentEvent` API in version `0.135.0`. The current project lock uses FastAPI `0.125.0`, so it does not have this API. Native SSE is optional. The existing `StreamingResponse` framing works in the current stack.

## Browser test results

Each row ran five browser repetitions against a production Next.js build using Chromium. Each ordinary response emitted six events at 100 ms intervals. Replay responses emitted eight events and disconnected after the third ID. The runner treats an event as incremental only when consecutive receive times differ by at least 40 ms.

| Next.js | FastAPI | Python LangGraph | LangChain Core | Path | Result |
| --- | --- | --- | --- | --- | --- |
| 16.1.0 | 0.125.0 | 1.0.5 | 1.2.2 | Direct, Route Handler, rewrite; manual SSE | Pass. All 5 repetitions delivered incrementally. Resume, cookies, and unauthenticated 401 checks passed. |
| 16.1.0 | 0.125.0 | 1.0.5 | 1.2.2 | Direct, Route Handler, rewrite; manual SSE without cache or proxy-buffering headers | Fail only on rewrite. The rewrite and authenticated rewrite arrived as gzip batches in all 5 repetitions. |
| 16.1.0 | 0.125.0 | 1.0.5 | 1.2.2 | Direct, Route Handler, rewrite; manual SSE without proxy-buffering headers but with `no-transform` | Pass. All 5 repetitions delivered incrementally. |
| 16.1.0 | 0.125.0 | 1.2.16 | 1.7.0 | Direct, Route Handler, rewrite; manual SSE without stream headers | Direct and Route Handler passed. Rewrite and authenticated rewrite buffered in all 5 repetitions. |
| 16.1.0 | 0.135.0 | 1.0.5 | 1.2.2 | Direct, Route Handler, rewrite; manual and native SSE | Fail only on rewrite-native. All 5 repetitions arrived as a gzip batch. All other paths passed. |
| 16.1.0 | 0.161.1 | 1.0.5 | 1.2.2 | Direct, Route Handler, rewrite; manual and native SSE | Fail only on rewrite-native. All 5 repetitions arrived as a gzip batch. |
| 16.4.2 | 0.161.1 | 1.0.5 | 1.2.2 | Direct, Route Handler, rewrite; manual and native SSE | Fail only on rewrite-native. All 5 repetitions arrived as a gzip batch. |
| 16.4.2 | 0.161.1 | 1.2.16 | 1.7.0 | Direct, Route Handler, rewrite; manual and native SSE | Fail only on rewrite-native with default compression. Direct and Route Handler passed. |
| 16.4.2 | 0.161.1 | 1.2.16 | 1.7.0 | Rewrite-native with `no-transform` | Pass. All 5 repetitions delivered incrementally while Next.js compression stayed enabled. |
| 16.1.0 | 0.161.1 | 1.2.16 | 1.7.0 | Rewrite-native with `no-transform` | Pass. All 5 repetitions delivered incrementally while Next.js compression stayed enabled. |
| 16.4.2 | 0.161.1 | 1.2.16 | 1.7.0 | Rewrite-native with Next.js compression disabled | Pass. All 5 repetitions delivered incrementally. |

The browser probe includes successful cookie-authenticated requests and requests without a cookie. The unauthenticated requests returned `401` through all three paths. All replay paths resumed from `Last-Event-ID` without gaps. The native route replay check ran only on FastAPI `0.135.0` and later. The manual-response results with explicit `no-transform` headers do not describe the current production endpoint; the no-header row is the closer match to its response configuration.

## Project versions and runtime boundary

The project lockfiles at `origin/main` resolve to the versions below for Python 3.11. Frontend package versions come from `frontend/package-lock.json`.

| Component | Project version | Lockfile source |
| --- | --- | --- |
| Next.js | 16.1.0 | `frontend/package-lock.json` |
| FastAPI | 0.125.0 | `finance-agent-core/uv.lock` |
| Python LangGraph | 1.0.5 | `finance-agent-core/uv.lock` |
| LangChain Core | 1.2.2 | `finance-agent-core/uv.lock` |
| JavaScript LangGraph SDK | 1.3.1 | `frontend/package-lock.json` |

The backend's Python LangGraph and the frontend's `@langchain/langgraph-sdk` are separate packages. Do not treat their version numbers as one SDK version.

The full upgrade cohort pins LangChain Core `1.7.0`. LangGraph `1.2.16` requires LangChain Core `>=1.4.7`, so it cannot run with this project's current `1.2.2` pin. The other cohorts keep Core `1.2.2` to match the current lock.

`finance-agent-core/api/server.py` was rechecked after merging current `origin/main` at `134263e` on 2026-10-23. The `/stream/{thread_id}` handler depends on `require_current_user`, but binds the principal to an unused `_principal` parameter and never calls `_require_thread_owner` before replay or queue attachment. Issue [#83](https://github.com/sosodennis/value-investment-agent/issues/83) is closed; its acceptance criteria explicitly require cross-user SSE denial, and its completion comment says this was delivered by #100. The current source therefore disagrees with the closed issue claim. The inspected test suite has no focused cross-user SSE attachment test. Treat ownership as an unresolved production security follow-up; this localhost transport probe does not test authorization.

The runtime projection intentionally does not store `content.delta` events. It advances the cursor for those events, while `fetch_activity_since` can replay only stored activity records. A reconnect can therefore receive a cursor gap when the missing ID belongs to a streamed text delta. The route also uses process-local live queues, tracked in [#84](https://github.com/sosodennis/value-investment-agent/issues/84). This probe validates a simple resumable stream and does not prove the production event log or multi-worker delivery is gap-free.

## How to run

Use the pinned Python environments and install the browser dependencies:

```sh
uv venv /tmp/sse-transport-current
uv pip install --python /tmp/sse-transport-current/bin/python -r backend/requirements-current.txt
uv venv /tmp/sse-transport-latest
uv pip install --python /tmp/sse-transport-latest/bin/python -r backend/requirements-latest.txt
uv venv /tmp/sse-transport-fastapi-min
uv pip install --python /tmp/sse-transport-fastapi-min/bin/python -r backend/requirements-minimum-native-sse.txt
uv venv /tmp/sse-transport-fastapi-latest
uv pip install --python /tmp/sse-transport-fastapi-latest/bin/python -r backend/requirements-fastapi-latest.txt
uv venv /tmp/sse-transport-langgraph-latest
uv pip install --python /tmp/sse-transport-langgraph-latest/bin/python -r backend/requirements-langgraph-latest.txt
cd frontend
npm ci
npm run build
```

Start the backend and frontend in separate terminals. Then run the browser test:

```sh
PROBE_FRONTEND_ORIGIN=http://127.0.0.1:13100 /tmp/sse-transport-current/bin/uvicorn app:app --app-dir ../backend --host 127.0.0.1 --port 18100
SSE_BACKEND_URL=http://127.0.0.1:18100 NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:18100 npm run build
PORT=13100 SSE_BACKEND_URL=http://127.0.0.1:18100 npm start
PROBE_INTERVAL_MS=100 REPETITIONS=5 node ../scripts/run-browser-probe.mjs
```

Set `PROBE_MANUAL_STREAM_HEADERS=0` to model the current production endpoint's missing stream headers. Set `PROBE_STREAM_NO_TRANSFORM=1` to add only `Cache-Control: no-transform` through the probe middleware. To test the global compression workaround, set `PROBE_DISABLE_NEXT_COMPRESSION=1` for both `npm run build` and `npm start`.

## Sources and limits

- [FastAPI Server-Sent Events](https://fastapi.tiangolo.com/tutorial/server-sent-events/) documents the native response and its generator route pattern.
- [Next.js compression](https://nextjs.org/docs/app/api-reference/config/next-config-js/compress), [rewrites](https://nextjs.org/docs/app/api-reference/config/next-config-js/rewrites), and [Route Handlers](https://nextjs.org/docs/app/building-your-application/routing/route-handlers) document the compression setting and the two Next.js proxy paths.
- [Next.js issue #45048](https://github.com/vercel/next.js/issues/45048) was closed in February 2026. Its latest reproduction reports incremental rewrite delivery on Next.js 16.1.6, while an earlier report describes buffering in a Caddy-to-Next.js-to-FastAPI chain. These cases vary by version and proxy chain; they do not show that every SSE response needs a Next.js proxy.
- [Next.js issue #62201](https://github.com/vercel/next.js/issues/62201) reports a compression-related FastAPI streaming failure. It remains open and does not establish a universal Next.js defect.
- [Next.js discussion #48427](https://github.com/vercel/next.js/discussions/48427) collects Route Handler, compression, reverse proxy, and deployment timeout reports. The cases support testing each deployed path; they do not show that every SSE response needs a Next.js proxy.
- [FastAPI PR #15813](https://github.com/tiangolo/fastapi/pull/15813) remains open as of 2026-10-23. It concerns proxy-buffering headers on JSONL responses. Recent review discussion covers honoring an endpoint-supplied `X-Accel-Buffering` value; that is not a fix to native SSE and does not establish behavior for this project’s ingress.
- [WHATWG Server-Sent Events](https://html.spec.whatwg.org/multipage/server-sent-events.html) specifies framing, event IDs, and browser reconnection behavior.

The probe runs on localhost with production-mode Next.js and Chromium. Current project source exposes `NEXT_PUBLIC_LANGGRAPH_URL`, and `docker-compose.production.yml` does not define a public ingress or proxy. The repository has no configured GitHub deployments. The actual production hostname, CDN/ingress chain, deployed auth service, multi-worker topology, and long-duration connection limits are therefore unverified. Discussion [#131](https://github.com/sosodennis/value-investment-agent/discussions/131) currently has comments only from the repository owner; community agreement is not established and needs reports from operators who can describe a real deployment path.

## Local application auth smoke test

On 2026-10-23, a temporary account was created in the isolated local production-build stack and deleted after the check. Registration returned `201`, login returned `200`, anonymous SSE attach returned `401`, authenticated SSE attach returned `200` and the expected `retry` frame, and `/me` returned `401` after logout. This verifies the local frontend/auth/SSE-attach path only. The Compose provider service did not start, so this run did not execute a real LangGraph workflow or validate generated events. It does not cover a public deployment, ingress/CDN behavior, or production authorization ownership.

Discussion [#131](https://github.com/sosodennis/value-investment-agent/discussions/131) has three comments, all posted by the repository owner, and no replies from other participants as of this test. These comments are research updates and requests for deployment details, not evidence of community consensus.

The Next.js 16.1.0 probe install reported two high and one critical npm audit findings. The registry reported Next.js 16.4.2 as the current release on 2026-10-23, and that release fixes the reported dependency audit set. This security finding is separate from the SSE transport result.
