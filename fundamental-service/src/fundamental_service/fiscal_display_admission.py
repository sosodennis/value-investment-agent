from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from itertools import pairwise
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .artifact_evidence import read_retained_artifact
from .command_artifacts import EvidenceArtifactStore
from .data_releases import ArtifactRefV1
from .fiscal_admission_authority import FiscalAuthorityOwner
from .fiscal_admission_history import (
    FiscalAdmissionHistoryPort,
    FiscalAdmissionHistoryReaderPort,
    FiscalCommitReceiptV1,
    FiscalControlBindingV1,
    FiscalHistoryHeadV1,
)
from .fiscal_authority_contracts import CurrentFiscalAuthorityV1
from .fiscal_candidate_contracts import VerifiedClassifiedCandidateSource
from .fiscal_candidate_preparation import CurrentFiscalCandidate
from .fiscal_display_contracts import (
    CurrentFiscalDisplay,
    FiscalDecideDisplayCommandV1,
    FiscalDisplayDecisionBodyV1,
    FiscalDisplayRequestV1,
    FiscalDisplayReviewExecutionV1,
    FiscalDisplayReviewScopeV1,
    FiscalDisplayReviewV1,
    SignedFiscalDisplayDecisionV1,
)
from .fiscal_source_closure import FiscalArtifactRead
from .fiscal_statement_policy import FiscalRowPolicyV1, fiscal_statement_policy
from .metadata import metadata_operation_budget
from .replay import (
    ArtifactPublicationDeadlineExceeded,
    ArtifactPublicationV1,
    ArtifactRecordV1,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError

_REVIEW = "fiscal-display-review-v1"
_DECISION = "fiscal-display-decision-v1"
_INTENT = "fiscal-display-intent-v1"
_SIGNING = "fiscal-display-signing-v1"


class FiscalCandidateReaderPort(Protocol):
    def verify_candidate(
        self, reference: ArtifactRefV1, *, deadline_at: datetime
    ) -> CurrentFiscalCandidate: ...


def fiscal_display_executable_digest() -> str:
    root = Path(__file__).parent
    return sha256_digest(
        tuple(
            (name, hashlib.sha256(root.joinpath(name).read_bytes()).hexdigest())
            for name in (
                "fiscal_display_contracts.py",
                "fiscal_display_admission.py",
                "fiscal_display_runtime.py",
                "fiscal_display_runner.py",
            )
        )
    )


def fiscal_display_policy_digest() -> str:
    return sha256_digest(
        (
            "fixed-candidate-independent-display-v1",
            fiscal_statement_policy(),
            "historical-quarter-ttm-only",
            "no-valuation-authorization",
        )
    )


def _invalid(message: str) -> SnapshotError:
    return SnapshotError("FISCAL_DISPLAY_INVALID", message)


def _ref(record: ArtifactRecordV1, role: str) -> ArtifactRefV1:
    return ArtifactRefV1(
        role=role,
        artifact_id=record.artifact_id,
        content_hash=record.content_hash,
        media_type=record.media_type,
    )


class FiscalDisplayAdmission:
    def __init__(
        self,
        *,
        candidates: FiscalCandidateReaderPort,
        artifacts: EvidenceArtifactStore,
        history: FiscalAdmissionHistoryReaderPort,
        authorities: FiscalAuthorityOwner,
        configuration_digest: Callable[[FiscalDisplayRequestV1], str],
        authorize: Callable[[FiscalDisplayRequestV1, datetime], Ed25519PrivateKey]
        | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.candidates, self.artifacts, self.history, self.authorities = (
            candidates,
            artifacts,
            history,
            authorities,
        )
        self._configuration_digest, self._authorize, self.clock = (
            configuration_digest,
            authorize,
            clock,
        )

    @staticmethod
    def _expired() -> SnapshotError:
        return SnapshotError(
            "REQUEST_DEADLINE_EXCEEDED", "display deadline expired", retryable=True
        )

    def _now(self) -> datetime:
        now = self.clock()
        if now.utcoffset() is None:
            raise _invalid("display clock must be timezone aware")
        return now

    def _budget(self, deadline_at: datetime) -> float:
        now = self._now()
        if deadline_at.utcoffset() is None or now >= deadline_at:
            raise self._expired()
        return (deadline_at - now).total_seconds()

    def _authority(
        self, request: FiscalDisplayRequestV1, deadline_at: datetime
    ) -> CurrentFiscalAuthorityV1:
        authority = self.authorities.read_current(
            request.authority_id,
            expected_role="release_approver",
            deadline_at=deadline_at,
        )
        if authority.grant.identity.principal_kind != "machine":
            raise _invalid(
                "automatic display review requires a machine release approver"
            )
        return authority

    @staticmethod
    def _independent(
        candidate: CurrentFiscalCandidate, execution: FiscalDisplayReviewExecutionV1
    ) -> None:
        activities = [candidate.preparation]
        for source in candidate.source_evidence:
            if isinstance(source, VerifiedClassifiedCandidateSource):
                activities.extend(source.activities)
        if any(
            activity.principal_id == execution.principal_id
            or activity.key_id == execution.key_id
            or execution.execution_id in activity.execution_ids
            for activity in activities
        ):
            raise _invalid(
                "display review is not independent of every candidate activity"
            )

    def _inspect(
        self, candidate: CurrentFiscalCandidate, deadline_at: datetime
    ) -> FiscalDisplayReviewScopeV1:
        projection, content = candidate.projection, candidate.content
        policy = fiscal_statement_policy()
        rows: dict[str, FiscalRowPolicyV1] = {row.row_id: row for row in policy.rows}
        nodes = {node.node_id: node for node in projection.nodes}
        observations = {
            item.observation_id: item for item in projection.source_observations
        }
        formulas = {
            None,
            "reported_quarter_cross_checked_with_ytd_difference",
            "fiscal_year_minus_nine_months",
            "current_ytd_minus_prior_ytd",
            "sum_four_contiguous_quarters",
            "window_opening_cash",
            "window_ending_cash",
            "same_end_balance_sheet_instant",
        }
        if (
            len(nodes) != len(projection.nodes)
            or len(observations) != len(projection.source_observations)
            or projection.policy_id != policy.policy_id
            or content.projection_policy_digest != policy.digest
            or projection.supported_history_threshold is not None
            or projection.valuation_eligibility != "not_evaluated"
        ):
            raise _invalid("display projection identity, policy or eligibility differs")
        permitted = {
            item.observation_id: item
            for source in content.source_uses
            for item in source.scope.permitted_inputs
        }
        if any(
            permitted.get(identity) != item
            or item.available_at > content.cutoff_at
            or item.accepted_at > content.cutoff_at
            for identity, item in observations.items()
        ):
            raise _invalid("display observations exceed exact source use or PIT")
        if len(projection.quarter_nodes) != len(rows) * len(
            projection.quarter_periods
        ) or len(projection.ttm_nodes) != len(rows) * len(projection.ttm_windows):
            raise _invalid("display lacks complete row and period coverage")
        quarter_periods = tuple(target.period for target in projection.quarter_periods)
        if any(period.kind != "duration" for period in quarter_periods) or any(
            target.cutoff_at != content.cutoff_at
            for target in projection.quarter_periods
        ):
            raise _invalid("display quarter periods or cutoff differ")
        for window in projection.ttm_windows:
            spans = tuple(target.period for target in window.quarters)
            if any(
                target not in projection.quarter_periods for target in window.quarters
            ) or any(
                left.kind != "duration"
                or right.kind != "duration"
                or left.end + timedelta(days=1) != right.start
                for left, right in pairwise(spans)
            ):
                raise _invalid("display TTM periods are not exact contiguous quarters")
        if any(node.frequency != "quarter" for node in projection.quarter_nodes) or any(
            node.frequency != "ttm" for node in projection.ttm_nodes
        ):
            raise _invalid("display frequency membership differs")
        for node in projection.nodes:
            self._budget(deadline_at)
            row = rows.get(node.row_id)
            if (
                row is None
                or row.statement != node.statement
                or node.policy_id != policy.policy_id
                or node.executable_digest != content.executable_digest
                or node.formula not in formulas
            ):
                raise _invalid("display row, formula or executable is unsupported")
            dependencies = tuple(
                edge.input_id for edge in (*node.input_edges, *node.verification_edges)
            )
            if (
                any(
                    identity not in nodes and identity not in observations
                    for identity in dependencies
                )
                or any(
                    identity not in observations
                    for identity in (
                        *node.source_observation_ids,
                        *node.verification_observation_ids,
                    )
                )
                or any(identity not in nodes for identity in node.verification_node_ids)
            ):
                raise _invalid("display graph contains an unresolved input")
            if node.availability in {"unavailable", "conflict"}:
                if node.value is not None or node.reason_code is None:
                    raise _invalid("display missing or conflict semantics were lost")
            else:
                if (
                    node.value is None
                    or not node.value.is_finite()
                    or node.available_at is None
                    or node.available_at > content.cutoff_at
                    or node.reporting_basis is None
                ):
                    raise _invalid(
                        "display value lacks finite source, basis or PIT evidence"
                    )
                if node.availability == "derived" and (
                    node.revision_basis_proof is None or not node.input_edges
                ):
                    raise _invalid(
                        "display derived value lacks revision proof or operands"
                    )
                source_quality = [
                    observations[identity].quality.value
                    for identity in (
                        *node.source_observation_ids,
                        *node.verification_observation_ids,
                    )
                ]
                source_quality.extend(
                    nodes[identity].quality.value
                    for identity in (*dependencies, *node.verification_node_ids)
                    if identity in nodes
                )
                if (
                    "provisional" in source_quality
                    and node.quality.value != "provisional"
                ):
                    raise _invalid("display upgraded provisional source quality")
            if node.formula == "sum_four_contiguous_quarters" and (
                node.frequency != "ttm"
                or row.aggregation != "additive_flow"
                or len(node.input_edges) != 4
                or any(
                    edge.coefficient != 1
                    or edge.input_id not in nodes
                    or nodes[edge.input_id].frequency != "quarter"
                    for edge in node.input_edges
                )
            ):
                raise _invalid("display TTM formula lacks four quarter inputs")
            if node.formula in {
                "current_ytd_minus_prior_ytd",
                "fiscal_year_minus_nine_months",
            } and (
                node.frequency != "quarter"
                or tuple(edge.coefficient for edge in node.input_edges) != (1, -1)
            ):
                raise _invalid("display quarter difference has wrong ordered operands")
        return FiscalDisplayReviewScopeV1(
            candidate_ref=candidate.reference,
            candidate_digest=candidate.candidate.candidate_digest,
            content=content,
            projection_digest=sha256_digest(projection),
            node_digests=tuple(
                (node.node_id, sha256_digest(node)) for node in projection.nodes
            ),
            observation_digests=tuple(
                (item.observation_id, sha256_digest(item))
                for item in projection.source_observations
            ),
            display_policy_digest=fiscal_display_policy_digest(),
            executable_digest=fiscal_display_executable_digest(),
        )

    def _load_review(
        self, reader: FiscalArtifactRead, ref: ArtifactRefV1
    ) -> FiscalDisplayReviewV1:
        raw = read_retained_artifact(reader, ref)
        review = FiscalDisplayReviewV1.model_validate_json(raw)
        if (
            ref.role != _REVIEW
            or ref.artifact_id != review.request.artifact_id(_REVIEW)
            or canonical_bytes(review) != raw
        ):
            raise _invalid("display review reference or bytes differ")
        return review

    def _load(
        self, reader: FiscalArtifactRead, ref: ArtifactRefV1
    ) -> SignedFiscalDisplayDecisionV1:
        raw = read_retained_artifact(reader, ref)
        decision = SignedFiscalDisplayDecisionV1.model_validate_json(raw)
        if (
            ref.role != _DECISION
            or ref.artifact_id != decision.artifact_id
            or canonical_bytes(decision) != raw
        ):
            raise _invalid("display decision reference or bytes differ")
        return decision

    def _verify_review(
        self,
        body: FiscalDisplayDecisionBodyV1,
        candidate: CurrentFiscalCandidate,
        authority: CurrentFiscalAuthorityV1,
        deadline_at: datetime,
    ) -> None:
        review = body.review
        execution, identity = review.execution, authority.grant.identity
        if (
            review.reviewed != self._inspect(candidate, deadline_at)
            or review.request != body.command.request
            or execution.authority_id != identity.authority_id
            or execution.grant_ref != authority.grant_ref
            or execution.principal_id != identity.principal_id
            or execution.key_id != identity.key_id
            or not authority.grant.valid_from
            <= execution.started_at
            <= execution.completed_at
            <= body.signed_at
            < review.request.expires_at
            <= authority.grant.valid_until
            or review.request.expires_at > candidate.candidate.body.command.expires_at
        ):
            raise _invalid(
                "display decision differs from actual review, candidate or current grant"
            )
        self._independent(candidate, execution)

    def _verify(
        self,
        decision: SignedFiscalDisplayDecisionV1,
        candidate: CurrentFiscalCandidate,
        authority: CurrentFiscalAuthorityV1,
        deadline_at: datetime,
    ) -> None:
        self._verify_review(decision.body, candidate, authority, deadline_at)
        try:
            Ed25519PublicKey.from_public_bytes(
                base64.b64decode(
                    authority.grant.identity.public_key_ed25519_base64, validate=True
                )
            ).verify(bytes.fromhex(decision.signature), decision.signing_bytes())
        except (InvalidSignature, ValueError) as error:
            raise _invalid("display decision signature is invalid") from error

    def _finish(
        self,
        decision: SignedFiscalDisplayDecisionV1,
        publication: ArtifactPublicationV1,
        *,
        deadline_at: datetime,
        configuration: str,
    ) -> CurrentFiscalDisplay:
        request = decision.body.command.request
        candidate = self.candidates.verify_candidate(
            request.candidate_ref, deadline_at=deadline_at
        )
        authority = self._authority(request, deadline_at)
        self._verify(decision, candidate, authority, deadline_at)
        reader = FiscalArtifactRead(self.artifacts, partial(self._budget, deadline_at))
        for record in candidate.consumed_metadata:
            reader.expect(record.artifact_id, record)
        ref = _ref(publication.artifact, _DECISION)
        if (
            self._load(reader, ref) != decision
            or self._load_review(reader, decision.body.command.release_review_ref)
            != decision.body.review
        ):
            raise _invalid("display evidence changed before completion")
        expected_dependencies = tuple(
            sorted(
                {
                    decision.body.command.release_review_ref.content_hash,
                    request.candidate_ref.content_hash,
                    authority.grant_ref.content_hash,
                    sha256_digest(decision.body),
                }
            )
        )
        if publication.artifact.dependency_hashes != expected_dependencies:
            raise _invalid("display decision dependency metadata differs")
        if reader.get(
            decision.body.command.release_review_ref.artifact_id
        ).dependency_hashes != (request.candidate_ref.content_hash,):
            raise _invalid("display review dependency metadata differs")
        for role, value in ((_INTENT, request), (_SIGNING, decision.body)):
            if read_retained_artifact(
                reader, _ref(reader.get(request.artifact_id(role)), role)
            ) != canonical_bytes(value):
                raise _invalid("display intent or frozen signing body differs")
        heads = {head.stream_id: head for head in candidate.history_heads}
        for head in authority.history_heads:
            if heads.setdefault(head.stream_id, head) != head:
                raise _invalid("display dependencies have conflicting history heads")
            if head.stream_kind == "evidence":
                reader.get(head.subject_id)
        control = self.history.read(
            ("control:display-decision:" + request.locator_digest,),
            deadline_at=deadline_at,
        )
        expected = FiscalControlBindingV1(
            action="release_approved",
            payload_ref=ref,
            command_digest=decision.body.command.command_digest,
        )
        if (
            len(control.entries) != 1
            or control.entries[0].event.body != expected
            or control.entries[0].event.origin_id
            != decision.body.review.execution.issuance.origin_id
            or control.entries[0].event.recorded_at < decision.body.signed_at
        ):
            raise _invalid(
                "display decision is revoked, superseded or lacks exact local approval"
            )
        control.require_current_epoch(control.entries)
        heads.update({head.stream_id: head for head in control.heads})
        epoch = self.history.read_epoch(deadline_at=deadline_at)
        execution = decision.body.review.execution
        epoch.require_current_issuance(execution.issuance)
        epoch.require_current_activity(
            execution.started_at, execution.completed_at, decision.body.signed_at
        )
        records = tuple(record for _, record in reader.records if record is not None)
        reader.check_current()
        observed = self.history.finish_observation(
            records, tuple(heads.values()), epoch, deadline_at=deadline_at
        )
        final_authority = self._authority(request, deadline_at)
        if self._configuration_digest(request) != configuration or (
            final_authority.grant_ref,
            final_authority.grant,
            final_authority.history_heads,
        ) != (authority.grant_ref, authority.grant, authority.history_heads):
            raise _invalid("display configuration or grant changed before return")
        expiries = [
            request.expires_at,
            authority.grant.valid_until,
            candidate.candidate.body.command.expires_at,
        ]
        for source in candidate.source_evidence:
            if isinstance(source, VerifiedClassifiedCandidateSource):
                expiries.extend(source.expires_at)
        now = self._now()
        if (
            any(now >= expiry for expiry in expiries)
            or now < candidate.observed_at
            or now < observed.observed_through
            or now < authority.observed_at
            or any(
                not isinstance(entry.commit_bound, FiscalCommitReceiptV1)
                or now <= entry.commit_bound.visible_by
                for entry in observed.entries
            )
        ):
            raise _invalid(
                "display permission expired or clock precedes trusted observation"
            )
        if (
            decision.body.review.reviewed.executable_digest
            != fiscal_display_executable_digest()
            or decision.body.review.reviewed.display_policy_digest
            != fiscal_display_policy_digest()
        ):
            raise _invalid("display executable or policy changed before return")
        self._budget(deadline_at)
        return CurrentFiscalDisplay(
            ref, decision, candidate, publication, records, observed.heads, now
        )

    def read_current(
        self,
        decision_ref: ArtifactRefV1,
        candidate_ref: ArtifactRefV1,
        *,
        deadline_at: datetime,
    ) -> CurrentFiscalDisplay:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            try:
                reader = FiscalArtifactRead(
                    self.artifacts, partial(self._budget, deadline_at)
                )
                decision = self._load(reader, decision_ref)
                configuration = self._configuration_digest(
                    decision.body.command.request
                )
                if decision.body.command.request.candidate_ref != candidate_ref:
                    raise _invalid("display read candidate differs from exact decision")
                return self._finish(
                    decision,
                    ArtifactPublicationV1(
                        artifact=reader.get(decision_ref.artifact_id), wrote=False
                    ),
                    deadline_at=deadline_at,
                    configuration=configuration,
                )
            except ValueError as error:
                raise _invalid("display evidence failed typed verification") from error

    def review_and_decide(
        self,
        request: FiscalDisplayRequestV1,
        *,
        expected_head: FiscalHistoryHeadV1 | None,
        deadline_at: datetime,
    ) -> CurrentFiscalDisplay:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            try:
                if self._authorize is None or not isinstance(
                    self.history, FiscalAdmissionHistoryPort
                ):
                    raise _invalid("display writer is not configured")
                request = FiscalDisplayRequestV1.model_validate_json(
                    canonical_bytes(request)
                )
                self._authorize(request, deadline_at)
                reader = FiscalArtifactRead(
                    self.artifacts, partial(self._budget, deadline_at)
                )
                previous = reader.current(request.artifact_id(_INTENT))
                if previous is not None and reader.read(
                    previous.artifact_id
                ) != canonical_bytes(request):
                    raise SnapshotError(
                        "FISCAL_DISPLAY_COMMAND_REUSED",
                        "display command intent is immutable",
                    )
                self.artifacts.put_with_receipt(
                    request.artifact_id(_INTENT),
                    request,
                    publication_budget=partial(self._budget, deadline_at),
                )
                review_record = reader.current(request.artifact_id(_REVIEW))
                if review_record is None:
                    authority = self._authority(request, deadline_at)
                    epoch = self.history.read_epoch(deadline_at=deadline_at)
                    started = self._now()
                    candidate = self.candidates.verify_candidate(
                        request.candidate_ref, deadline_at=deadline_at
                    )
                    reviewed = self._inspect(candidate, deadline_at)
                    identity = authority.grant.identity
                    review = FiscalDisplayReviewV1(
                        request=request,
                        reviewed=reviewed,
                        execution=FiscalDisplayReviewExecutionV1(
                            authority_id=identity.authority_id,
                            grant_ref=authority.grant_ref,
                            principal_id=identity.principal_id,
                            key_id=identity.key_id,
                            execution_id="display-job:" + uuid4().hex,
                            issuance=epoch.issuance_context,
                            started_at=started,
                            completed_at=self._now(),
                        ),
                    )
                    self._independent(candidate, review.execution)
                    epoch.require_current_activity(
                        started, review.execution.completed_at
                    )
                    if (
                        self._authority(request, deadline_at).grant_ref
                        != authority.grant_ref
                    ):
                        raise _invalid("display grant changed during actual review")
                    review_record = self.artifacts.put_with_receipt(
                        request.artifact_id(_REVIEW),
                        review,
                        (request.candidate_ref.content_hash,),
                        publication_budget=partial(self._budget, deadline_at),
                    ).artifact
                return self.decide_release(
                    FiscalDecideDisplayCommandV1(
                        request=request, release_review_ref=_ref(review_record, _REVIEW)
                    ),
                    expected_head=expected_head,
                    deadline_at=deadline_at,
                )
            except ArtifactPublicationDeadlineExceeded as error:
                raise self._expired() from error
            except ValueError as error:
                raise _invalid("display review failed typed verification") from error

    def decide_release(
        self,
        command: FiscalDecideDisplayCommandV1,
        *,
        expected_head: FiscalHistoryHeadV1 | None,
        deadline_at: datetime,
    ) -> CurrentFiscalDisplay:
        with metadata_operation_budget(
            partial(self._budget, deadline_at), self._expired
        ):
            try:
                command = FiscalDecideDisplayCommandV1.model_validate_json(
                    canonical_bytes(command)
                )
                return self._decide_release(
                    command, expected_head=expected_head, deadline_at=deadline_at
                )
            except ArtifactPublicationDeadlineExceeded as error:
                raise self._expired() from error
            except ValueError as error:
                raise _invalid("display decision failed typed verification") from error

    def _decide_release(
        self,
        command: FiscalDecideDisplayCommandV1,
        *,
        expected_head: FiscalHistoryHeadV1 | None,
        deadline_at: datetime,
    ) -> CurrentFiscalDisplay:
        if self._authorize is None or not isinstance(
            self.history, FiscalAdmissionHistoryPort
        ):
            raise _invalid("display writer is not configured")
        request = command.request
        configuration = self._configuration_digest(request)
        key = self._authorize(request, deadline_at)
        reader = FiscalArtifactRead(self.artifacts, partial(self._budget, deadline_at))
        review = self._load_review(reader, command.release_review_ref)
        if review.request != request:
            raise _invalid("display command differs from actual review request")
        candidate = self.candidates.verify_candidate(
            request.candidate_ref, deadline_at=deadline_at
        )
        authority = self._authority(request, deadline_at)
        existing = reader.current(request.artifact_id(_DECISION))
        if existing is None:
            if reader.current(request.artifact_id(_SIGNING)) is not None:
                raise SnapshotError(
                    "FISCAL_DISPLAY_SIGNING_OUTCOME_UNAVAILABLE",
                    "signing began without a durable exact outcome",
                )
            body = FiscalDisplayDecisionBodyV1(
                command=command, review=review, signed_at=self._now()
            )
            if key.public_key().public_bytes_raw() != base64.b64decode(
                authority.grant.identity.public_key_ed25519_base64, validate=True
            ):
                raise _invalid("display deployment key differs from current grant")
            self._verify_review(body, candidate, authority, deadline_at)
            marker = self.artifacts.put_with_receipt(
                request.artifact_id(_SIGNING),
                body,
                publication_budget=partial(self._budget, deadline_at),
            )
            if not marker.wrote:
                raise SnapshotError(
                    "FISCAL_DISPLAY_SIGNING_OUTCOME_UNAVAILABLE",
                    "only first live invocation may sign frozen body",
                )
            key = self._authorize(request, deadline_at)
            signed = SignedFiscalDisplayDecisionV1(
                body=body, signature=key.sign(canonical_bytes(body)).hex()
            )
            publication = self.artifacts.put_with_receipt(
                signed.artifact_id,
                signed,
                tuple(
                    sorted(
                        {
                            command.release_review_ref.content_hash,
                            request.candidate_ref.content_hash,
                            authority.grant_ref.content_hash,
                            sha256_digest(body),
                        }
                    )
                ),
                publication_budget=partial(self._budget, deadline_at),
            )
        else:
            signed = self._load(reader, _ref(existing, _DECISION))
            if signed.body.command != command:
                raise _invalid("display command identity was reused")
            publication = ArtifactPublicationV1(artifact=existing, wrote=False)
        self._verify(signed, candidate, authority, deadline_at)
        self.history.read_epoch(deadline_at=deadline_at).require_current_issuance(
            signed.body.review.execution.issuance
        )
        records = {record.artifact_id: record for record in candidate.consumed_metadata}
        for role in (_INTENT, _REVIEW, _SIGNING, _DECISION):
            record = self.artifacts.get(request.artifact_id(role))
            records[record.artifact_id] = record
        for head in authority.history_heads:
            if head.stream_kind == "evidence":
                records[head.subject_id] = self.artifacts.get(head.subject_id)
        values = tuple(records.values())
        for start in range(0, len(values), 256):
            self.history.checkpoint(
                values[start : start + 256], deadline_at=deadline_at
            )
        self._authorize(request, deadline_at)
        self.history.append_once(
            "display-decision:" + request.locator_digest,
            FiscalControlBindingV1(
                action="release_approved",
                payload_ref=_ref(publication.artifact, _DECISION),
                command_digest=command.command_digest,
            ),
            expected_head=expected_head,
            deadline_at=deadline_at,
        )
        return self._finish(
            signed, publication, deadline_at=deadline_at, configuration=configuration
        )
