"""Measure the private model-inference HTTP service under concurrent load."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import statistics
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import uuid4

import httpx

NEWS_TEXTS = (
    "Revenue growth accelerated and operating margins expanded this quarter.",
    "The company reported a loss and weaker demand in the latest quarter.",
    "Management expects stable demand and modest margin improvement next year.",
    "The filing describes a neutral outlook with no material change in guidance.",
)
CAPACITY = {"news.sentiment": 4, "sec.fls": 2}


@dataclass(frozen=True, slots=True)
class CallSample:
    elapsed_ms: float
    status_code: int
    valid_output: bool
    error_code: str | None
    model_revision: str | None
    label: str | None


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(percentile * len(ordered)) - 1))
    return round(ordered[index], 3)


def _news_payload(index: int) -> tuple[dict[str, object], int]:
    return {"text": NEWS_TEXTS[index % len(NEWS_TEXTS)]}, 0


def _fls_payload(index: int, sentence_count: int) -> tuple[dict[str, object], int]:
    sentences = [
        f"Management expects revenue growth to improve in outlook period {index}-{item}."
        for item in range(sentence_count)
    ]
    return {"sentences": sentences}, sentence_count


def _valid_result(
    operation: str, payload: dict[str, object], expected_predictions: int
) -> tuple[bool, str | None, str | None]:
    if (
        payload.get("schema_version") != "inference.v1"
        or payload.get("operation") != operation
    ):
        return False, None, None
    result = payload.get("result")
    if not isinstance(result, dict):
        return False, None, None
    revision = payload.get("model_revision")
    if not isinstance(revision, str) or not revision:
        return False, None, None
    if operation == "news.sentiment":
        label = result.get("label")
        confidence = result.get("confidence")
        scores = result.get("scores")
        valid = (
            isinstance(label, str)
            and label in {"positive", "negative", "neutral"}
            and isinstance(confidence, (int, float))
            and not isinstance(confidence, bool)
            and math.isfinite(float(confidence))
            and 0.0 <= float(confidence) <= 1.0
            and isinstance(scores, dict)
            and bool(scores)
            and all(
                isinstance(score_label, str)
                and score_label in {"positive", "negative", "neutral"}
                and isinstance(score, (int, float))
                and not isinstance(score, bool)
                and math.isfinite(float(score))
                and 0.0 <= float(score) <= 1.0
                for score_label, score in scores.items()
            )
        )
        return valid, revision, cast(str, label) if valid else None

    predictions = result.get("predictions")
    valid = (
        isinstance(predictions, list)
        and len(predictions) == expected_predictions
        and all(
            isinstance(prediction, dict)
            and isinstance(prediction.get("keep"), bool)
            and (
                prediction.get("confidence") is None
                or (
                    isinstance(prediction.get("confidence"), (int, float))
                    and not isinstance(prediction.get("confidence"), bool)
                    and math.isfinite(float(prediction["confidence"]))
                    and 0.0 <= float(prediction["confidence"]) <= 1.0
                )
            )
            for prediction in predictions
        )
    )
    return valid, revision, None


def _error_code(payload: object) -> str:
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = error.get("code")
            if isinstance(code, str):
                return code
    return "MALFORMED_RESPONSE"


async def _call(
    client: httpx.AsyncClient,
    *,
    operation: str,
    index: int,
    sentence_count: int,
) -> CallSample:
    payload, expected_predictions = (
        _news_payload(index)
        if operation == "news.sentiment"
        else _fls_payload(index, sentence_count)
    )
    request_id = f"bench-{uuid4().hex}"
    started = time.perf_counter()
    try:
        response = await client.post(
            "/v1/inference",
            headers={"X-Request-ID": request_id},
            json={
                "schema_version": "inference.v1",
                "operation": operation,
                "input": payload,
            },
        )
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        try:
            response_payload = response.json()
        except ValueError:
            response_payload = None
        if response.status_code != 200:
            return CallSample(
                elapsed_ms,
                response.status_code,
                False,
                _error_code(response_payload),
                None,
                None,
            )
        if not isinstance(response_payload, dict):
            return CallSample(
                elapsed_ms,
                response.status_code,
                False,
                "MALFORMED_RESPONSE",
                None,
                None,
            )
        valid, revision, label = _valid_result(
            operation, response_payload, expected_predictions
        )
        if response_payload.get("request_id") != request_id:
            valid = False
        return CallSample(
            elapsed_ms,
            response.status_code,
            valid,
            None if valid else "INVALID_OUTPUT",
            revision,
            label,
        )
    except httpx.TimeoutException:
        return CallSample(
            round((time.perf_counter() - started) * 1000.0, 3),
            0,
            False,
            "CLIENT_TIMEOUT",
            None,
            None,
        )
    except httpx.HTTPError as exc:
        return CallSample(
            round((time.perf_counter() - started) * 1000.0, 3),
            0,
            False,
            type(exc).__name__.upper(),
            None,
            None,
        )


async def _bounded_call(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    *,
    operation: str,
    index: int,
    sentence_count: int,
) -> CallSample:
    async with semaphore:
        return await _call(
            client,
            operation=operation,
            index=index,
            sentence_count=sentence_count,
        )


async def _monitor_runtime(
    client: httpx.AsyncClient,
    *,
    operation: str,
    stop: asyncio.Event,
    observed: dict[str, int | str],
) -> None:
    while not stop.is_set():
        try:
            response = await client.get("/readyz")
            if response.status_code == 200:
                body = response.json()
                operations = body.get("operations") if isinstance(body, dict) else None
                state = (
                    operations.get(operation) if isinstance(operations, dict) else None
                )
                if isinstance(state, dict):
                    in_flight = state.get("in_flight")
                    queue_size = state.get("queue_size")
                    revision = state.get("model_revision")
                    if isinstance(in_flight, int):
                        observed["max_in_flight"] = max(
                            int(observed.get("max_in_flight", 0)), in_flight
                        )
                    if isinstance(queue_size, int):
                        observed["max_queue_size"] = max(
                            int(observed.get("max_queue_size", 0)), queue_size
                        )
                    if isinstance(revision, str):
                        observed["model_revision"] = revision
        except (httpx.HTTPError, ValueError):
            pass
        await asyncio.sleep(0.01)


def _summarize(samples: list[CallSample], wall_ms: float) -> dict[str, object]:
    response_latencies = [sample.elapsed_ms for sample in samples]
    successful_latencies = [
        sample.elapsed_ms for sample in samples if sample.valid_output
    ]
    statuses = Counter(str(sample.status_code) for sample in samples)
    error_codes = Counter(
        sample.error_code for sample in samples if sample.error_code is not None
    )
    return {
        "requests": len(samples),
        "valid_successes": sum(sample.valid_output for sample in samples),
        "errors": len(samples) - sum(sample.valid_output for sample in samples),
        "overloaded": sum(sample.error_code == "OVERLOADED" for sample in samples),
        "deadline_exceeded": sum(
            sample.error_code == "DEADLINE_EXCEEDED" for sample in samples
        ),
        "statuses": dict(sorted(statuses.items())),
        "error_codes": dict(sorted(error_codes.items())),
        "p50_ms": _percentile(successful_latencies, 0.50),
        "p95_ms": _percentile(successful_latencies, 0.95),
        "max_ms": round(max(successful_latencies), 3) if successful_latencies else 0.0,
        "mean_ms": round(statistics.fmean(successful_latencies), 3)
        if successful_latencies
        else 0.0,
        "all_response_p50_ms": _percentile(response_latencies, 0.50),
        "all_response_p95_ms": _percentile(response_latencies, 0.95),
        "wall_ms": round(wall_ms, 3),
        "throughput_rps": round(len(successful_latencies) / (wall_ms / 1000.0), 3)
        if wall_ms
        else 0.0,
        "response_rps": round(len(samples) / (wall_ms / 1000.0), 3) if wall_ms else 0.0,
        "labels": sorted(
            {sample.label for sample in samples if sample.label is not None}
        ),
        "raw": [asdict(sample) for sample in samples],
    }


async def _run(args: argparse.Namespace) -> int:
    token = os.getenv("INFERENCE_SERVICE_TOKEN", "")
    if not token:
        raise ValueError("INFERENCE_SERVICE_TOKEN must be set")
    if (
        args.requests_per_level < 1
        or args.sentences_per_request < 1
        or args.warmup_requests < 0
    ):
        raise ValueError("request and sentence counts must be positive")
    if any(level < 1 for level in args.concurrency):
        raise ValueError("concurrency levels must be positive")
    max_in_flight = args.max_in_flight or CAPACITY[args.operation]
    if max_in_flight < 1 or args.queue_depth < 0:
        raise ValueError("capacity limits must be positive")
    if (
        args.require_overload
        and max(args.concurrency) <= max_in_flight + args.queue_depth
    ):
        raise ValueError(
            "overload mode needs a level above in-flight plus queue capacity"
        )

    base_url = args.base_url.rstrip("/")
    timeout = httpx.Timeout(args.client_timeout_seconds)
    limits = httpx.Limits(
        max_connections=max(max(args.concurrency) + 1, 2),
        max_keepalive_connections=max(max(args.concurrency) + 1, 2),
    )
    headers = {"Authorization": f"Bearer {token}"}
    observed: dict[str, int | str] = {"max_in_flight": 0, "max_queue_size": 0}
    levels: dict[str, dict[str, object]] = {}

    async with (
        httpx.AsyncClient(
            base_url=base_url, headers=headers, timeout=timeout, limits=limits
        ) as client,
        httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=httpx.Timeout(1.0),
            limits=httpx.Limits(max_connections=1),
        ) as monitor,
    ):
        readiness = await client.get("/readyz")
        if readiness.status_code != 200:
            raise RuntimeError(f"service is not ready: HTTP {readiness.status_code}")
        readiness_body = readiness.json()
        operations = (
            readiness_body.get("operations")
            if isinstance(readiness_body, dict)
            else None
        )
        operation_state = (
            operations.get(args.operation) if isinstance(operations, dict) else None
        )
        if (
            not isinstance(operation_state, dict)
            or operation_state.get("ready") is not True
            or operation_state.get("accepting") is not True
            or not isinstance(operation_state.get("model_revision"), str)
        ):
            raise RuntimeError(
                "service readiness does not include the requested operation"
            )
        observed["model_revision"] = cast(str, operation_state["model_revision"])
        warmup_started = time.perf_counter()
        warmup_samples = [
            await _call(
                client,
                operation=args.operation,
                index=-index - 1,
                sentence_count=args.sentences_per_request,
            )
            for index in range(args.warmup_requests)
        ]
        warmup_wall_ms = (time.perf_counter() - warmup_started) * 1000.0
        if any(not sample.valid_output for sample in warmup_samples):
            raise RuntimeError("service warmup request returned an invalid result")
        warmup = _summarize(warmup_samples, warmup_wall_ms)
        stop = asyncio.Event()
        monitor_task = asyncio.create_task(
            _monitor_runtime(
                monitor, operation=args.operation, stop=stop, observed=observed
            )
        )
        try:
            for concurrency in args.concurrency:
                request_count = max(concurrency, args.requests_per_level)
                semaphore = asyncio.Semaphore(concurrency)
                started = time.perf_counter()
                samples = await asyncio.gather(
                    *(
                        _bounded_call(
                            client,
                            semaphore,
                            operation=args.operation,
                            index=concurrency * 100_000 + index,
                            sentence_count=args.sentences_per_request,
                        )
                        for index in range(request_count)
                    )
                )
                wall_ms = (time.perf_counter() - started) * 1000.0
                levels[str(concurrency)] = _summarize(samples, wall_ms)
        finally:
            stop.set()
            await monitor_task

    in_flight_seen = int(observed["max_in_flight"])
    queue_seen = int(observed["max_queue_size"])
    overload_count = sum(int(level["overloaded"]) for level in levels.values())
    invalid_output_count = sum(
        int(cast(dict[str, int], level["error_codes"]).get("INVALID_OUTPUT", 0))
        + int(cast(dict[str, int], level["error_codes"]).get("MALFORMED_RESPONSE", 0))
        for level in levels.values()
    )
    allowed_errors = set(args.allow_error)
    if args.require_overload:
        allowed_errors.add("OVERLOADED")
    unexpected_errors = sum(
        sum(
            count
            for code, count in cast(dict[str, int], level["error_codes"]).items()
            if code not in allowed_errors
        )
        for level in levels.values()
    )
    capacity_ok = in_flight_seen <= max_in_flight and queue_seen <= args.queue_depth
    overload_ok = not args.require_overload or overload_count > 0
    output_ok = invalid_output_count == 0
    report: dict[str, object] = {
        "started_at": datetime.now(UTC).isoformat(),
        "operation": args.operation,
        "endpoint": base_url,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "configured_max_in_flight": max_in_flight,
        "configured_queue_depth": args.queue_depth,
        "max_in_flight_observed": in_flight_seen,
        "max_queue_observed": queue_seen,
        "model_revision": observed.get("model_revision"),
        "warmup": warmup,
        "capacity_bounds_passed": capacity_ok,
        "overload_observed": overload_count > 0,
        "overload_expectation_passed": overload_ok,
        "output_expectation_passed": output_ok,
        "allowed_error_codes": sorted(allowed_errors),
        "unexpected_errors": unexpected_errors,
        "invalid_outputs": invalid_output_count,
        "levels": levels,
    }
    print(json.dumps(report, sort_keys=True))
    return (
        0 if capacity_ok and overload_ok and output_ok and unexpected_errors == 0 else 2
    )


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--operation", choices=tuple(CAPACITY), required=True)
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 2, 4, 8])
    parser.add_argument("--requests-per-level", type=int, default=8)
    parser.add_argument("--sentences-per-request", type=int, default=16)
    parser.add_argument("--warmup-requests", type=int, default=0)
    parser.add_argument("--queue-depth", type=int, default=8)
    parser.add_argument("--max-in-flight", type=int)
    parser.add_argument("--client-timeout-seconds", type=float, default=4.0)
    parser.add_argument("--allow-error", action="append", default=[])
    parser.add_argument("--require-overload", action="store_true")
    return parser


def main() -> None:
    args = _argument_parser().parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except (OSError, RuntimeError, ValueError, httpx.HTTPError) as exc:
        print(
            json.dumps({"error": type(exc).__name__, "message": str(exc)}),
            file=sys.stderr,
        )
        raise SystemExit(2) from exc
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
