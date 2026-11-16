"""Company/date CLI adapter to the authenticated automatic caller boundary."""

import hashlib
import json
import os
import subprocess
import sys
import urllib.parse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from src.shared.internal_services import InternalPrincipal, build_internal_context

from .automatic_approval import AutomaticValuationApprovalPolicyV1
from .automatic_valuation import (
    AutomaticValuationRequestV1,
    AutomaticValuationResponseV1,
    load_runtime_automatic_approval_policy,
)
from .contracts import ValuationEvidenceReadRequestV1
from .preparation_runner import SourcePreparationEvidenceV1
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes


@dataclass(frozen=True)
class DeploymentAutomaticCaller:
    base_url: str
    policy: AutomaticValuationApprovalPolicyV1
    token: str = field(repr=False)

    @classmethod
    def from_env(cls) -> "DeploymentAutomaticCaller | None":
        policy = load_runtime_automatic_approval_policy()
        base_url = os.getenv("FUNDAMENTAL_AUTOMATIC_APPROVAL_SERVICE_URL")
        if policy is None and base_url is None:
            return None
        if policy is None or not base_url:
            raise ValueError("automatic issuer caller requires policy and service URL")
        url = urllib.parse.urlsplit(base_url)
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
        ):
            raise ValueError(
                "automatic caller requires a credential-free service origin"
            )
        token = os.getenv("FUNDAMENTAL_SERVICE_TOKEN")
        if not token:
            raise ValueError("automatic issuer caller requires its service credential")
        return cls(base_url=base_url.rstrip("/"), policy=policy, token=token)

    def _request(
        self,
        path: str,
        payload: dict[str, object],
        *,
        method: str,
        caller_id: str,
        organization_id: str,
        deadline_at: datetime,
    ) -> bytes:
        now = datetime.now(UTC)
        seconds = (deadline_at - now).total_seconds()
        if seconds <= 0:
            raise TimeoutError("automatic issuer caller deadline expired")
        context = build_internal_context(
            principal=InternalPrincipal(
                subject_id=caller_id,
                organization_id=organization_id,
                membership_id=f"deployment-automatic-caller:{caller_id}",
            ),
            correlation_id="automatic-issuer-caller",
            deadline_at=deadline_at,
            audience="fundamental-service",
            signing_key=self.token,
            issued_at=now,
        )
        wire = {
            "url": self.base_url + path,
            "body": canonical_bytes({"context": context, "input": payload}).decode(),
            "method": method,
            "timeout_seconds": seconds,
            "headers": {
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "X-Organization-ID": organization_id,
            },
        }
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).with_name("automatic_caller_http.py")),
                ],
                input=canonical_bytes(wire),
                capture_output=True,
                timeout=max(0.001, (deadline_at - datetime.now(UTC)).total_seconds()),
                check=False,
            )
        except subprocess.TimeoutExpired:
            raise TimeoutError("automatic issuer caller deadline expired") from None
        if completed.returncode:
            try:
                error = json.loads(completed.stderr)
            except ValueError:
                error = {}
            status = error.get("http_status") if isinstance(error, dict) else None
            raise RuntimeError(
                f"automatic caller service refused {method} with HTTP {status}"
                if isinstance(status, int)
                else "automatic caller transport failed"
            )
        if datetime.now(UTC) >= deadline_at:
            raise TimeoutError("automatic issuer caller deadline expired")
        return completed.stdout

    def execute(
        self,
        source_preparation: ArtifactRecordV1,
        *,
        caller_id: str,
        organization_id: str,
        deadline_at: datetime,
    ) -> AutomaticValuationResponseV1 | None:
        raw = self._request(
            "/v1/artifacts/"
            + urllib.parse.quote(source_preparation.artifact_id, safe="")
            + "/content",
            {},
            method="GET",
            caller_id=caller_id,
            organization_id=organization_id,
            deadline_at=deadline_at,
        )
        if hashlib.sha256(raw).hexdigest() != source_preparation.content_hash:
            raise ValueError("automatic caller source preparation content hash differs")
        evidence = SourcePreparationEvidenceV1.model_validate_json(raw)
        if evidence.status != "approval_required":
            return None
        prepared = evidence.preparation
        assert prepared is not None and prepared.input is not None
        assert prepared.input.input_digest is not None
        assert evidence.snapshot_id is not None
        assert evidence.data_release_manifest_digest is not None
        request = AutomaticValuationRequestV1(
            preparation=ValuationEvidenceReadRequestV1(
                contract_version="fundamental.v1",
                snapshot_id=evidence.snapshot_id,
                data_release_manifest_digest=evidence.data_release_manifest_digest,
                model_id=prepared.model_id,
            ),
            expected_input_digest=prepared.input.input_digest,
            approval_policy_digest=self.policy.digest,
        )
        raw = self._request(
            "/v1/valuation/calculate-automatically",
            request.model_dump(mode="json"),
            method="POST",
            caller_id=caller_id,
            organization_id=organization_id,
            deadline_at=deadline_at,
        )
        response = json.loads(raw)
        if (
            not isinstance(response, dict)
            or response.get("contract_version") != "internal.v1"
            or response.get("schema_version") != "fundamental.v1"
        ):
            raise ValueError("automatic caller response contract differs")
        result = AutomaticValuationResponseV1.model_validate_json(
            canonical_bytes(response["result"])
        )
        decision = result.decision
        if (
            decision.caller_id != caller_id
            or decision.organization_id != organization_id
            or decision.expected_input_digest != request.expected_input_digest
            or decision.requested_policy_digest != request.approval_policy_digest
        ):
            raise ValueError("automatic caller response is bound to another decision")
        return result
