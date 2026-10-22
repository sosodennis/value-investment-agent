# Issue #109 deployment and workload verification

## Result

The isolated deployment starts both model services while the model registry is
unreachable, and replacing only the backend preserves both inference container
IDs, start times, images, readiness states, and loaded model revisions. The
backend's first inference request after rollout exceeded its caller deadline in
both recorded cold probes; five subsequent requests for each operation passed
in the final probe. Readiness therefore proves that model loading completed,
but it does not prove that the first backend call will fit its request deadline.

The repeated warm-workload comparison is descriptive, not a speedup claim. It
ran five alternating baseline/service rounds with valid-output checks and error
counts. A profiler was not run, so these results do not identify the resource
that limits throughput or establish why the two paths differ.

## Environment and method

- ARM64 Docker host; 10 CPUs and 7.75 GiB Docker memory.
- Both sides were capped at 4 CPUs and 1500 MiB, with one PyTorch thread.
- Baseline image: `sha256:ba6dac071a004c6a85e9bc66164a2f0ce0b2c30594d50be8686aaeaf6ea0ec72`.
- Inference revisions: News `2db55b5439cef6253c12a4973f3a9e823ff90b79`; FLS
  `443586dc31c765c0aaf1c4daaed8cf3643c92fa5`.
- Each round used one unmeasured warmup, then eight calls at concurrency 1, 2,
  4, and 8. FLS classified 16 sentences per call. The HTTP harness checked the
  response schema, operation, correlation ID, model revision, and output values.
- The direct baseline used the old backend image and the same benchmark inputs.
  Its process RSS and the inference container's Docker memory are different
  measurements and should not be compared as if they were the same metric.
- Latency percentiles below are the median and min–max range across five runs.
  HTTP latency percentiles include valid responses only; failures are shown
  separately. Throughput is successful responses per elapsed workload time.

## Startup and resource use

| Workload | Baseline model-load time, median (range) | Baseline peak RSS after concurrency, median (range) | Offline service readiness |
| --- | ---: | ---: | ---: |
| News sentiment | 6.98 s (6.83–8.25 s) | 900.7 MiB (898.5–905.2 MiB) | 15 s |
| SEC FLS | 6.22 s (6.18–6.44 s) | 1059.6 MiB (1056.2–1072.0 MiB) | 16 s |

The final saturation run sampled Docker memory 15 times per service. News peaked
at 498.7 MiB and FLS at 494.6 MiB under a 1.465 GiB container limit. This is
container-level sampled memory, not process peak RSS. The model images loaded
with registry access disabled.

The final backend-only replacement retained both model-service IDs, start
times, image IDs, and model revisions; see
[`deployment-final-probe2.jsonl`](deployment-final-probe2.jsonl). After
replacement, the first News call took 627.740 ms against a 500 ms deadline and
the first FLS call took 751.264 ms against a 750 ms deadline; both returned
`DEADLINE_EXCEEDED`. The five later calls for each operation succeeded. The
earlier deployment probe also recorded one deadline failure on each first
call, followed by successful calls. Rollout checks should preserve this cold
first-call result rather than treating readiness as an inference latency
guarantee.

## Five-round warm-workload comparison

Entries show `p50 / p95` milliseconds as median (range), then successful
throughput as median (range). Direct-baseline requests all succeeded. At FLS
concurrency 4 and 8, the service returned `OVERLOADED` for 15 of 40 requests at
each level; the percentiles are for the remaining successful requests only.

| Operation | Concurrency | Direct p50 / p95 | Direct req/s | HTTP p50 / p95 | HTTP req/s | Valid / total HTTP calls |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| News | 1 | 77.9 (76.1–79.1) / 81.6 (78.2–120.0) | 12.9 (12.0–13.4) | 76.6 (75.9–79.0) / 82.3 (79.7–85.0) | 12.9 (12.6–12.9) | 40 / 40 |
| News | 2 | 82.7 (82.1–85.5) / 86.2 (85.5–87.4) | 23.8 (23.4–23.9) | 82.9 (80.0–86.4) / 87.7 (84.0–89.3) | 23.6 (22.8–24.6) | 40 / 40 |
| News | 4 | 89.6 (87.5–97.0) / 94.9 (93.5–107.9) | 42.0 (39.0–43.7) | 107.2 (102.6–110.2) / 118.2 (113.1–132.1) | 35.9 (34.0–36.2) | 40 / 40 |
| News | 8 | 175.7 (160.7–184.6) / 188.1 (184.8–219.0) | 41.7 (35.9–42.4) | 110.3 (106.6–111.6) / 223.8 (219.6–226.0) | 35.6 (35.3–36.3) | 40 / 40 |
| FLS | 1 | 559.7 (558.0–566.8) / 581.6 (562.2–592.6) | 1.8 (1.8–1.8) | 221.3 (217.1–226.9) / 233.9 (224.6–238.9) | 4.5 (4.4–4.6) | 40 / 40 |
| FLS | 2 | 566.9 (564.6–571.1) / 572.2 (569.1–581.7) | 3.5 (3.5–3.5) | 319.9 (317.9–323.7) / 343.8 (335.7–352.9) | 6.1 (6.1–6.2) | 40 / 40 |
| FLS | 4 | 599.3 (597.1–601.3) / 612.2 (609.8–620.9) | 6.6 (6.5–6.6) | 322.5 (313.3–327.5) / 547.8 (535.3–566.7) | 5.5 (5.3–5.6) | 25 / 40; 15 overloaded |
| FLS | 8 | 1182.0 (1175.9–1272.1) / 1217.5 (1205.6–1302.1) | 6.5 (6.1–6.6) | 324.4 (319.9–339.1) / 555.3 (546.5–571.1) | 5.4 (5.2–5.5) | 25 / 40; 15 overloaded |

The HTTP service completed every News comparison request and had no deadline
failures in this warmed comparison. FLS at concurrency 4 and 8 produced
overload responses but no deadline failures. These measurements cover this
host, image, request shape, and harness; they do not establish a general
performance advantage.

## Saturation and recommended limits

| Operation and configured capacity | Repeated saturation result | Decision |
| --- | --- | --- |
| News: 4 in-flight + 8 queued | Two queue-8 saturation runs differed: one had 4 `DEADLINE_EXCEEDED` and 4 `OVERLOADED` of 16; another had 12 successes and 4 `OVERLOADED`, with no deadline errors. | Use 4 queued. Five queue-4 runs each returned 8 valid and 8 `OVERLOADED` of 16, with no deadline errors; observed queue and in-flight counts stayed within configured bounds. |
| FLS: 2 in-flight + 8 queued | At 12 concurrent calls, 4 succeeded, 6 hit `DEADLINE_EXCEEDED`, and 2 were `OVERLOADED`. Five warmed comparison runs at concurrency 8 each had 4 deadline failures. | Reduce to 1 queued. Five queue-1 saturation runs each returned 3 valid and 9 `OVERLOADED` of 12, with no deadline errors. |
| FLS: 2 in-flight + 2 queued | Two saturation probes returned 4 successes and no deadline failures in one run; the other returned 2 successes, 2 `DEADLINE_EXCEEDED`, and 8 `OVERLOADED`. | Queue 2 did not consistently avoid deadline failures; retain queue 1. |

Recommended defaults are therefore News `4 in-flight + 4 queued` and FLS `2
in-flight + 1 queued`, one process/model copy per operation, four CPUs and a
1.5 GiB memory cap per service. At the 12-request FLS saturation level, the
queue-1 setup intentionally admits only three requests and rejects the other
nine quickly. The recommendation prioritizes bounded admission and avoiding
observed deadline failures for admitted work; it is not a claim that the
largest possible throughput was reached.

No profiler was used to attribute the observed latency or throughput limits.
Rerun profiling and the benchmark on the target deployment host before using
these figures for capacity expansion or for claiming a performance win.

## Raw evidence

- Five alternating runs: [`comparison-final-warmup-queue-4-1/`](comparison-final-warmup-queue-4-1/)
- News queue 4 saturation, five runs: `saturation-final-queue-4-news-1/` through
  `saturation-final-queue-4-news-5/`
- FLS queue 1 saturation, five runs: `saturation-final-queue-1-fls-1/` through
  `saturation-final-queue-1-fls-5/`
- FLS queue 2 probes: `saturation-probe-queue2-1/` and
  `saturation-probe-queue2-2/`
- Earlier queue 8 comparison and saturation evidence: `comparison-20261022T200005Z/`,
  `news-saturation.json`, `saturation-news-final/`, and `fls-saturation.json`
- Deployment probes: `deployment-final.jsonl` and
  `deployment-final-probe2.jsonl`
