from __future__ import annotations

import asyncio
import json
import multiprocessing
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from multiprocessing.queues import Queue
from queue import Empty
from uuid import uuid4

import litellm
from litellm import Router
from litellm.integrations.custom_logger import CustomLogger
from provider_key_telemetry import provider_key_telemetry
from redis import Redis

_lock = threading.Lock()
_dispatches: list[str] = []
_servers: list[ThreadingHTTPServer] = []


class _CallbackProbe(CustomLogger):
    def __init__(self) -> None:
        self.success_deployments: list[str | None] = []
        self.failure_deployments: list[str | None] = []

    @staticmethod
    def deployment_id(kwargs: dict[str, object]) -> str | None:
        params = kwargs.get("litellm_params")
        if not isinstance(params, dict):
            return None
        metadata = params.get("metadata")
        model_info = params.get("model_info")
        if isinstance(metadata, dict) and isinstance(metadata.get("model_info"), dict):
            model_info = metadata["model_info"]
        if isinstance(model_info, dict):
            model_id = model_info.get("id")
            return model_id if isinstance(model_id, str) else None
        return None

    async def async_log_success_event(
        self,
        kwargs: dict[str, object],
        response_obj: object,
        start_time: object,
        end_time: object,
    ) -> None:
        self.success_deployments.append(self.deployment_id(kwargs))

    async def async_log_failure_event(
        self,
        kwargs: dict[str, object],
        response_obj: object,
        start_time: object,
        end_time: object,
    ) -> None:
        self.failure_deployments.append(self.deployment_id(kwargs))


class _UnavailableUpstream(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        with _lock:
            _dispatches.append(self.server.deployment_name)

        body = json.dumps({"error": {"message": "synthetic upstream failure"}}).encode()
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


class _RecoveringUpstream(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.dispatch_count += 1
        if self.server.dispatch_count == 1:
            body = json.dumps(
                {"error": {"message": "synthetic upstream failure"}}
            ).encode()
            status = 503
        else:
            body = json.dumps(
                {
                    "model": "synthetic-model",
                    "choices": [
                        {"message": {"role": "assistant", "content": "recovered"}}
                    ],
                }
            ).encode()
            status = 200
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def _start_upstream(deployment_name: str) -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _UnavailableUpstream)
    server.deployment_name = deployment_name
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _servers.append(server)
    return f"http://127.0.0.1:{server.server_port}/v1"


def _start_recovering_upstream() -> tuple[str, ThreadingHTTPServer]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _RecoveringUpstream)
    server.dispatch_count = 0
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _servers.append(server)
    return f"http://127.0.0.1:{server.server_port}/v1", server


def _call_router(router: Router) -> None:
    try:
        router.completion(
            model="retry-contract",
            messages=[{"role": "user", "content": "synthetic test"}],
            num_retries=1,
        )
    except Exception:
        return
    raise AssertionError("the synthetic upstream should fail each request")


def _run_router_worker(
    api_base: str,
    redis_host: str,
    redis_port: int,
    results: Queue,
) -> None:
    router = Router(
        model_list=[
            {
                "model_name": "shared-retry-contract",
                "litellm_params": {
                    "model": "openai/synthetic-model",
                    "api_base": api_base,
                    "api_key": "synthetic-only",
                },
                "model_info": {"id": "shared-deployment"},
            }
        ],
        redis_host=redis_host,
        redis_port=redis_port,
        num_retries=1,
        allowed_fails=0,
        cooldown_time=60,
        retry_after=0,
        routing_strategy="simple-shuffle",
        cache_responses=False,
    )
    try:
        router.completion(
            model="shared-retry-contract",
            messages=[{"role": "user", "content": "synthetic test"}],
            num_retries=1,
        )
    except Exception as exc:
        results.put(("failed", type(exc).__name__))
    else:
        results.put(("succeeded", ""))


def _run_separate_router_process(
    api_base: str, redis_host: str, redis_port: int
) -> tuple[str, str]:
    context = multiprocessing.get_context("spawn")
    results: Queue = context.Queue()
    process = context.Process(
        target=_run_router_worker,
        args=(api_base, redis_host, redis_port, results),
    )
    process.start()
    try:
        outcome = results.get(timeout=60)
    except Empty as exc:
        process.terminate()
        process.join()
        raise AssertionError("LiteLLM worker did not return a result") from exc
    process.join(timeout=10)
    if process.is_alive():
        process.terminate()
        process.join()
        raise AssertionError("LiteLLM worker did not exit")
    if process.exitcode != 0:
        raise AssertionError(f"LiteLLM worker exited with {process.exitcode}")
    results.close()
    results.join_thread()
    return outcome


def _verify_shared_cooldown() -> None:
    redis_host = "llm-gateway-contract-redis"
    redis_port = 6379
    with Redis(host=redis_host, port=redis_port) as client:
        client.flushdb()
        assert client.ping()

    api_base = _start_upstream("shared-deployment")
    before_first_worker = len(_dispatches)
    first_worker = _run_separate_router_process(api_base, redis_host, redis_port)
    after_first_worker = len(_dispatches)
    assert first_worker[0] == "failed", first_worker
    assert after_first_worker - before_first_worker == 1

    second_worker = _run_separate_router_process(api_base, redis_host, redis_port)
    assert second_worker[0] == "failed", second_worker
    assert len(_dispatches) == after_first_worker, tuple(_dispatches)


def _verify_cooldown_recovery() -> None:
    redis_host = "llm-gateway-contract-redis"
    redis_port = 6379
    with Redis(host=redis_host, port=redis_port) as client:
        client.flushdb()

    api_base, upstream = _start_recovering_upstream()
    router = Router(
        model_list=[
            {
                "model_name": "recovery-contract",
                "litellm_params": {
                    "model": "openai/synthetic-model",
                    "api_base": api_base,
                    "api_key": "synthetic-only",
                },
                "model_info": {"id": "recovery-deployment"},
            }
        ],
        redis_host=redis_host,
        redis_port=redis_port,
        num_retries=0,
        allowed_fails=0,
        cooldown_time=1,
        retry_after=0,
        routing_strategy="simple-shuffle",
        cache_responses=False,
    )

    for _ in range(2):
        try:
            router.completion(
                model="recovery-contract",
                messages=[{"role": "user", "content": "synthetic test"}],
                num_retries=0,
            )
        except Exception:
            pass
        else:
            raise AssertionError("the deployment should remain cooled down")
    assert upstream.dispatch_count == 1

    time.sleep(1.1)
    response = router.completion(
        model="recovery-contract",
        messages=[{"role": "user", "content": "synthetic test"}],
        num_retries=0,
    )
    assert response.choices[0].message.content == "recovered"
    assert upstream.dispatch_count == 2


async def _verify_key_telemetry() -> None:
    redis_host = "llm-gateway-contract-redis"
    redis_port = 6379
    with Redis(host=redis_host, port=redis_port) as client:
        client.flushdb()

    previous_success_callbacks = litellm._async_success_callback
    previous_failure_callbacks = litellm._async_failure_callback
    previous_callbacks = litellm.callbacks
    callback_probe = _CallbackProbe()
    litellm.callbacks = [provider_key_telemetry, callback_probe]
    litellm._async_success_callback = [provider_key_telemetry, callback_probe]
    litellm._async_failure_callback = [provider_key_telemetry, callback_probe]

    failed_id = str(uuid4())
    failed_base = _start_upstream("telemetry-failure")
    failed_router = Router(
        model_list=[
            {
                "model_name": "telemetry-failure-contract",
                "litellm_params": {
                    "model": "openai/synthetic-model",
                    "api_base": failed_base,
                    "api_key": "synthetic-only",
                },
                "model_info": {"id": failed_id},
            }
        ],
        redis_host=redis_host,
        redis_port=redis_port,
        num_retries=0,
        allowed_fails=0,
        cooldown_time=1,
        retry_after=0,
        routing_strategy="simple-shuffle",
        cache_responses=False,
    )

    recovered_id = str(uuid4())
    recovered_base, recovered_upstream = _start_recovering_upstream()
    recovered_router = Router(
        model_list=[
            {
                "model_name": "telemetry-recovery-contract",
                "litellm_params": {
                    "model": "openai/synthetic-model",
                    "api_base": recovered_base,
                    "api_key": "synthetic-only",
                },
                "model_info": {"id": recovered_id},
            }
        ],
        redis_host=redis_host,
        redis_port=redis_port,
        num_retries=0,
        allowed_fails=0,
        cooldown_time=1,
        retry_after=0,
        routing_strategy="simple-shuffle",
        cache_responses=False,
    )

    async def request(router: Router, model: str) -> None:
        try:
            await router.acompletion(
                model=model,
                messages=[{"role": "user", "content": "synthetic test"}],
                num_retries=0,
            )
        except Exception:
            return
        if model == "telemetry-failure-contract":
            raise AssertionError("the synthetic upstream should fail")

    try:
        await request(failed_router, "telemetry-failure-contract")
        key = f"via:llm-provider:key-health:{failed_id}"
        with Redis(host=redis_host, port=redis_port, decode_responses=True) as client:
            failure = client.hgetall(key)
        assert failure.get("status") == "cooldown", failure
        assert failure.get("failure_count") == "1", failure
        assert failure.get("last_error") == "unavailable", failure
        assert failure.get("cooldown_until"), failure

        await request(recovered_router, "telemetry-recovery-contract")
        await asyncio.sleep(1.1)
        await request(recovered_router, "telemetry-recovery-contract")
        assert recovered_upstream.dispatch_count == 2
        assert (
            failed_id in callback_probe.failure_deployments
        ), callback_probe.failure_deployments
        for _ in range(50):
            if recovered_id in callback_probe.success_deployments:
                break
            await asyncio.sleep(0.02)
        assert (
            recovered_id in callback_probe.success_deployments
        ), callback_probe.success_deployments
        with Redis(host=redis_host, port=redis_port, decode_responses=True) as client:
            recovered = client.hgetall(f"via:llm-provider:key-health:{recovered_id}")
        assert recovered.get("status") == "healthy", recovered
        assert recovered.get("failure_count") == "0", recovered
        assert recovered.get("last_used_at"), recovered
    finally:
        litellm._async_success_callback = previous_success_callbacks
        litellm._async_failure_callback = previous_failure_callbacks
        litellm.callbacks = previous_callbacks
        await provider_key_telemetry.aclose()


def main() -> None:
    model_bases = (
        _start_upstream("deployment-a"),
        _start_upstream("deployment-b"),
    )
    router = Router(
        model_list=[
            {
                "model_name": "retry-contract",
                "litellm_params": {
                    "model": "openai/synthetic-model",
                    "api_base": base,
                    "api_key": "synthetic-only",
                },
                "model_info": {"id": f"deployment-{index}"},
            }
            for index, base in enumerate(model_bases)
        ],
        num_retries=1,
        allowed_fails=0,
        cooldown_time=60,
        retry_after=0,
        routing_strategy="simple-shuffle",
        cache_responses=False,
    )
    try:
        _call_router(router)
        first_request_dispatches = tuple(_dispatches)
        _call_router(router)
        second_request_dispatches = tuple(_dispatches[len(first_request_dispatches) :])

        assert set(first_request_dispatches) == {
            "deployment-a",
            "deployment-b",
        }, first_request_dispatches
        assert not second_request_dispatches, second_request_dispatches
        _verify_shared_cooldown()
        _verify_cooldown_recovery()
        asyncio.run(_verify_key_telemetry())
    finally:
        for server in _servers:
            server.shutdown()

    print(
        "PASS: LiteLLM bounds upstream retries, cools failed deployments, "
        "shares cooldown across Router processes, records per-key outcomes, "
        "and recovers after cooldown."
    )


if __name__ == "__main__":
    main()
