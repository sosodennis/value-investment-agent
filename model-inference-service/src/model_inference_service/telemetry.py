from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram, make_asgi_app
from starlette.types import ASGIApp

REQUESTS = Counter(
    "model_inference_requests_total",
    "Inference requests by operation, pinned revision, and outcome.",
    ("operation", "model_revision", "outcome"),
)
QUEUE_WAIT = Histogram(
    "model_inference_queue_wait_seconds",
    "Time an accepted request waits before a worker starts it.",
    ("operation", "model_revision"),
)
INFERENCE_TIME = Histogram(
    "model_inference_execution_seconds",
    "Time spent in the synchronous model execution call.",
    ("operation", "model_revision"),
)
IN_FLIGHT = Gauge(
    "model_inference_in_flight",
    "Model calls currently occupying an operation worker.",
    ("operation", "model_revision"),
)
QUEUE_SIZE = Gauge(
    "model_inference_queue_size",
    "Accepted requests currently waiting for an operation worker.",
    ("operation", "model_revision"),
)


def metrics_app() -> ASGIApp:
    return make_asgi_app()
