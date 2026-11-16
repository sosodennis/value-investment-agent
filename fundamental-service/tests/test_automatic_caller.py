"""CLI-to-service automatic caller checks with synthetic released sources."""

import io
import json
import subprocess
import threading
import time
import urllib.error
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from fundamental_service.automatic_caller import DeploymentAutomaticCaller
from fundamental_service.preparation_runner import SourcePreparationEvidenceV1
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.testsupport import TEST_SERVICE_TOKEN
from test_automatic_valuation import _case


def _transport(client, monkeypatch):
    calls = []

    class Opener:
        def open(self, request, *, timeout):
            calls.append(request)
            assert 0 < timeout <= 30
            response = client.request(
                request.method,
                request.full_url,
                content=request.data,
                headers=dict(request.header_items()),
            )
            if response.status_code != 200:
                raise urllib.error.HTTPError(
                    request.full_url, response.status_code, "refused", {}, None
                )
            return io.BytesIO(response.content)

    monkeypatch.setattr(
        "fundamental_service.automatic_caller_http.urllib.request.build_opener",
        lambda *args: Opener(),
    )

    def run(command, *, input, capture_output, timeout, check):
        from fundamental_service.automatic_caller_http import read_response

        try:
            return subprocess.CompletedProcess(
                command, 0, read_response(json.loads(input)), b""
            )
        except urllib.error.HTTPError as error:
            return subprocess.CompletedProcess(
                command, 3, b"", canonical_bytes({"http_status": error.code})
            )

    monkeypatch.setattr("fundamental_service.automatic_caller.subprocess.run", run)
    return calls


def _source(fixture, client, request):
    from fundamental_service.testsupport import auth_headers, make_internal_envelope
    from fundamental_service.valuation_preparation import (
        AutomaticValuationPreparationV1,
    )

    response = client.post(
        "/v1/valuation/prepare",
        headers=auth_headers(),
        json=make_internal_envelope(request["preparation"]),
    )
    assert response.status_code == 200, response.text
    preparation = AutomaticValuationPreparationV1.model_validate_json(
        canonical_bytes(response.json()["result"])
    )
    evidence = SourcePreparationEvidenceV1(
        source_revision="a" * 40,
        plan_digest="b" * 64,
        status="approval_required",
        snapshot_id=fixture.snapshot.snapshot_id,
        snapshot_manifest_digest=fixture.snapshot.manifest_digest,
        data_release_manifest_digest=request["preparation"][
            "data_release_manifest_digest"
        ],
        preparation=preparation,
    )
    return fixture.artifacts.put(
        f"source-preparation:{sha256_digest(evidence)}", evidence
    )


def test_cli_reads_exact_preparation_and_uses_authenticated_automatic_endpoint(
    tmp_path, monkeypatch
):
    fixture, client, policy, request = _case(tmp_path)
    source = _source(fixture, client, request)
    calls = _transport(client, monkeypatch)
    caller = DeploymentAutomaticCaller(
        base_url="http://testserver", policy=policy, token=TEST_SERVICE_TOKEN
    )
    result = caller.execute(
        source,
        caller_id="subject-test",
        organization_id="organization-test",
        deadline_at=datetime.now(UTC) + timedelta(seconds=30),
    )
    assert result.decision.decision == "approved"
    assert result.calculation.input_digest == request["expected_input_digest"]
    assert [item.method for item in calls] == ["GET", "POST"]
    assert calls[-1].full_url.endswith("/v1/valuation/calculate-automatically")
    assert TEST_SERVICE_TOKEN not in repr(caller)


def test_changed_preparation_hash_stops_before_decision(tmp_path, monkeypatch):
    fixture, client, policy, request = _case(tmp_path)
    source = _source(fixture, client, request)
    calls = _transport(client, monkeypatch)
    caller = DeploymentAutomaticCaller(
        base_url="http://testserver", policy=policy, token=TEST_SERVICE_TOKEN
    )
    with pytest.raises(ValueError, match="content hash differs"):
        caller.execute(
            source.model_copy(update={"content_hash": "c" * 64}),
            caller_id="subject-test",
            organization_id="organization-test",
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )
    assert len(calls) == 1


def test_unsigned_or_wrong_credential_cannot_create_automatic_decision(
    tmp_path, monkeypatch
):
    fixture, client, policy, request = _case(tmp_path)
    source = _source(fixture, client, request)
    calls = _transport(client, monkeypatch)
    caller = DeploymentAutomaticCaller(
        base_url="http://testserver", policy=policy, token="wrong-service-token"
    )
    with pytest.raises(RuntimeError, match="HTTP 401"):
        caller.execute(
            source,
            caller_id="subject-test",
            organization_id="organization-test",
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )
    assert len(calls) == 1


def test_cli_automatic_configuration_is_explicit_and_credential_free(
    tmp_path, monkeypatch
):
    _, _, policy, _ = _case(tmp_path)
    monkeypatch.delenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_FILE", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_DIGEST", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_SERVICE_URL", raising=False)
    assert DeploymentAutomaticCaller.from_env() is None
    path = tmp_path / "approval.json"
    path.write_bytes(canonical_bytes(policy))
    monkeypatch.setenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_FILE", str(path))
    monkeypatch.setenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_POLICY_DIGEST", policy.digest)
    with pytest.raises(ValueError, match="policy and service URL"):
        DeploymentAutomaticCaller.from_env()
    monkeypatch.setenv("FUNDAMENTAL_SERVICE_TOKEN", TEST_SERVICE_TOKEN)
    monkeypatch.setenv(
        "FUNDAMENTAL_AUTOMATIC_APPROVAL_SERVICE_URL",
        "https://secret:token@example.test",
    )
    with pytest.raises(ValueError, match="credential-free"):
        DeploymentAutomaticCaller.from_env()
    monkeypatch.setenv(
        "FUNDAMENTAL_AUTOMATIC_APPROVAL_SERVICE_URL", "http://testserver"
    )
    assert DeploymentAutomaticCaller.from_env().policy == policy


def test_slow_drip_http_cannot_extend_command_deadline(tmp_path):
    _, _, policy, _ = _case(tmp_path)
    stop = threading.Event()

    class SlowResponse(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100000")
            self.end_headers()
            try:
                while not stop.wait(0.02):
                    self.wfile.write(b"a")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowResponse)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    caller = DeploymentAutomaticCaller(
        base_url=f"http://127.0.0.1:{server.server_port}",
        policy=policy,
        token="synthetic-private-token",
    )
    started = time.monotonic()
    try:
        with pytest.raises(TimeoutError, match="deadline expired") as error:
            caller._request(
                "/slow",
                {},
                method="GET",
                caller_id="subject-test",
                organization_id="organization-test",
                deadline_at=datetime.now(UTC) + timedelta(seconds=0.5),
            )
        assert time.monotonic() - started < 2
        assert caller.token not in str(error.value)
    finally:
        stop.set()
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
