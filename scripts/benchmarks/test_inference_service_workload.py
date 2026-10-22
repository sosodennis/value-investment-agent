from __future__ import annotations

from inference_service_workload import (
    _argument_parser,
    _summarize,
    _valid_result,
)


def test_deadline_errors_are_not_allowed_by_default() -> None:
    args = _argument_parser().parse_args(
        ["--base-url", "http://inference", "--operation", "news.sentiment"]
    )

    assert args.allow_error == []
    assert args.warmup_requests == 0


def test_news_wire_result_is_valid_without_backend_derived_has_numbers() -> None:
    valid, revision, label = _valid_result(
        "news.sentiment",
        {
            "schema_version": "inference.v1",
            "operation": "news.sentiment",
            "model_revision": "revision-123",
            "result": {
                "label": "positive",
                "confidence": 0.9,
                "scores": {"positive": 0.9, "negative": 0.05, "neutral": 0.05},
            },
        },
        0,
    )

    assert valid is True
    assert revision == "revision-123"
    assert label == "positive"


def test_news_wire_result_rejects_wrong_operation_and_non_finite_score() -> None:
    wrong_operation, _, _ = _valid_result(
        "news.sentiment",
        {
            "schema_version": "inference.v1",
            "operation": "sec.fls",
            "model_revision": "revision-123",
            "result": {
                "label": "positive",
                "confidence": 0.9,
                "scores": {"positive": 0.9},
            },
        },
        0,
    )
    invalid_score, _, _ = _valid_result(
        "news.sentiment",
        {
            "schema_version": "inference.v1",
            "operation": "news.sentiment",
            "model_revision": "revision-123",
            "result": {
                "label": "positive",
                "confidence": 0.9,
                "scores": {"positive": float("nan")},
            },
        },
        0,
    )

    assert wrong_operation is False
    assert invalid_score is False


def test_fls_wire_result_requires_exact_ordered_cardinality_shape() -> None:
    payload = {
        "schema_version": "inference.v1",
        "operation": "sec.fls",
        "model_revision": "revision-fls",
        "result": {
            "predictions": [
                {"keep": True, "confidence": 0.8},
                {"keep": False, "confidence": 0.1},
            ]
        },
    }

    assert _valid_result("sec.fls", payload, 2) == (True, "revision-fls", None)
    assert _valid_result("sec.fls", payload, 1)[0] is False


def test_summarize_keeps_deadline_and_overload_errors_visible() -> None:
    from inference_service_workload import CallSample

    summary = _summarize(
        [
            CallSample(100.0, 200, True, None, "revision", "positive"),
            CallSample(500.0, 504, False, "DEADLINE_EXCEEDED", None, None),
            CallSample(1.0, 429, False, "OVERLOADED", None, None),
        ],
        600.0,
    )

    assert summary["valid_successes"] == 1
    assert summary["errors"] == 2
    assert summary["deadline_exceeded"] == 1
    assert summary["overloaded"] == 1
    assert summary["p50_ms"] == 100.0
    assert summary["p95_ms"] == 100.0
    assert summary["all_response_p95_ms"] == 500.0
    assert summary["throughput_rps"] == 1.667
    assert summary["response_rps"] == 5.0
    assert summary["error_codes"] == {"DEADLINE_EXCEEDED": 1, "OVERLOADED": 1}
