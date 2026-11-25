from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import (
    Context,
    Decimal,
    Inexact,
    InvalidOperation,
    Overflow,
    Rounded,
    localcontext,
)

from .contracts import QualityStatus
from .fiscal_statement_contracts import (
    FiscalCandidateDecisionV1,
    FiscalAvailability,
    AmendedFiscalRevisionV1,
    FiscalDurationPeriodV1,
    FiscalInputEdgeV1,
    FiscalFrequency,
    FiscalInstantPeriodV1,
    FiscalObservationV1,
    FiscalPeriodTargetV1,
    FiscalPrecisionIntervalV1,
    FiscalProjectionInputV1,
    FiscalProjectionResultV1,
    FiscalReconciliationV1,
    FiscalCashContinuityV1,
    FiscalRevisionBasisProofV1,
    FiscalTtmWindowV1,
    FiscalValueNodeV1,
    ReportedFiscalYearV1,
    ReportedInstantV1,
    ReportedQuarterV1,
    ReportedYtdV1,
)
from .fiscal_statement_policy import (
    FISCAL_STATEMENT_POLICY_ID,
    FiscalRowPolicyV1,
    fiscal_statement_policy,
)
from .serialization import sha256_digest


class FiscalProjectionError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Selection:
    selected: FiscalObservationV1 | None
    decisions: tuple[FiscalCandidateDecisionV1, ...]
    reason: str | None = None


def _numeric_context(values: Iterable[Decimal]) -> Context:
    amounts = tuple(values)
    if not amounts:
        precision = 50
    else:
        largest = max(value.adjusted() for value in amounts)
        smallest = min(int(value.as_tuple().exponent) for value in amounts)
        precision = max(50, largest - smallest + 32)
        if precision > 100_000:
            raise FiscalProjectionError(
                "FISCAL_NUMERIC_RANGE_UNSUPPORTED",
                "numeric exponent range is unsupported",
            )
    return Context(
        prec=precision,
        Emin=-999999,
        Emax=999999,
        traps=[Inexact, Rounded, InvalidOperation, Overflow],
    )


def _interval(observation: FiscalObservationV1) -> FiscalPrecisionIntervalV1 | None:
    value = observation.value
    if value is None or observation.decimals is None:
        return None
    if observation.decimals == "INF":
        return FiscalPrecisionIntervalV1(
            lower=value, upper=value, lower_inclusive=True, upper_inclusive=True
        )
    if abs(observation.decimals) > 10_000:
        return None
    half = Decimal(10) ** -observation.decimals / Decimal(2)
    return FiscalPrecisionIntervalV1(lower=value - half, upper=value + half)


def _signed_interval(
    intervals: tuple[tuple[FiscalPrecisionIntervalV1 | None, int], ...],
) -> FiscalPrecisionIntervalV1 | None:
    if any(interval is None for interval, _ in intervals):
        return None
    lower, upper = Decimal(0), Decimal(0)
    lower_inclusive, upper_inclusive = True, True
    for interval, coefficient in intervals:
        if interval is None:
            return None
        if coefficient >= 0:
            lower += interval.lower * coefficient
            upper += interval.upper * coefficient
            lower_inclusive &= interval.lower_inclusive
            upper_inclusive &= interval.upper_inclusive
        else:
            lower += interval.upper * coefficient
            upper += interval.lower * coefficient
            lower_inclusive &= interval.upper_inclusive
            upper_inclusive &= interval.lower_inclusive
    return FiscalPrecisionIntervalV1(
        lower=lower,
        upper=upper,
        lower_inclusive=lower_inclusive,
        upper_inclusive=upper_inclusive,
    )


def _precision_order(observation: FiscalObservationV1) -> int:
    if observation.decimals == "INF":
        return 1_000_001
    return observation.decimals if observation.decimals is not None else -1_000_001


def _scope_error(
    observation: FiscalObservationV1, request: FiscalProjectionInputV1
) -> str | None:
    scope, basis = request.scope, observation.basis
    if observation.issuer_id != scope.issuer_id or basis.issuer_id != scope.issuer_id:
        return "issuer_mismatch"
    if (basis.currency, basis.unit) != (scope.currency, scope.unit):
        return "unit_mismatch"
    if basis.consolidation_scope != scope.consolidation_scope:
        return "consolidation_scope_mismatch"
    if basis.dimensions:
        return "dimension_mismatch"
    if basis.entity_scope != scope.entity_scope:
        return "entity_scope_mismatch"
    if (
        basis.security_id != scope.security_id
        or basis.security_scope != scope.security_scope
    ):
        return "security_scope_mismatch"
    if observation.value is None:
        return "source_value_unavailable"
    if observation.quality not in {QualityStatus.VERIFIED, QualityStatus.PROVISIONAL}:
        return "source_quality_unavailable"
    return None


def _compatibility_error(observations: tuple[FiscalObservationV1, ...]) -> str | None:
    if not observations:
        return None
    basis = observations[0].basis
    for observation in observations[1:]:
        other = observation.basis
        if basis.issuer_id != other.issuer_id:
            return "issuer_mismatch"
        if basis.unit != other.unit or basis.currency != other.currency:
            return "unit_mismatch"
        if basis.consolidation_scope != other.consolidation_scope:
            return "consolidation_scope_mismatch"
        if basis.dimensions != other.dimensions:
            return "dimension_mismatch"
        if basis.cash_basis != other.cash_basis:
            return "cash_basis_mismatch"
        if not basis.same_accounting_scope(other):
            return "accounting_scope_mismatch"
    return None


def _conflict(reason: str | None) -> bool:
    return reason is not None and (
        reason.endswith(("_mismatch", "_conflict"))
        or reason
        in {
            "source_candidate_conflict",
            "duplicate_fact_conflict",
            "duplicate_basis_conflict",
            "duplicate_precision_unavailable",
            "cash_continuity_conflict",
        }
    )


def _rejected_selection(
    decisions: Iterable[FiscalCandidateDecisionV1],
    candidates: Iterable[FiscalObservationV1],
    reason: str,
) -> _Selection:
    rejected = tuple(decisions) + tuple(
        FiscalCandidateDecisionV1(
            observation_id=item.observation_id, outcome="rejected", reason=reason
        )
        for item in candidates
    )
    return _Selection(
        None, tuple(sorted(rejected, key=lambda item: item.observation_id)), reason
    )


def _select(
    request: FiscalProjectionInputV1,
    row: FiscalRowPolicyV1,
    matches: Callable[[FiscalObservationV1], bool],
) -> _Selection:
    boundary = row.aggregation == "cash_opening"
    rows = (
        {"cash_flow_beginning_balance", "cash_flow_ending_balance"}
        if boundary
        else {row.row_id}
    )
    candidates = sorted(
        (
            observation
            for observation in request.observations
            if observation.row_id in rows
            and observation.statement == row.statement
            and matches(observation)
        ),
        key=lambda item: item.observation_id,
    )
    decisions: list[FiscalCandidateDecisionV1] = []
    eligible = []
    unknown_amendments = []
    for candidate in candidates:
        amendment = candidate.filing_revision
        if (
            candidate.available_at > request.cutoff_at
            or candidate.accepted_at > request.cutoff_at
        ):
            decisions.append(
                FiscalCandidateDecisionV1(
                    observation_id=candidate.observation_id,
                    outcome="rejected",
                    reason="not_available_at_cutoff",
                )
            )
        elif (
            isinstance(amendment, AmendedFiscalRevisionV1)
            and amendment.scope == "unknown"
        ):
            unknown_amendments.append(candidate)
            decisions.append(
                FiscalCandidateDecisionV1(
                    observation_id=candidate.observation_id,
                    outcome="rejected",
                    reason="unknown_amendment_scope",
                )
            )
        else:
            eligible.append(candidate)
    if not eligible:
        return _Selection(None, tuple(decisions), "source_period_unavailable")
    latest = max(candidate.available_at for candidate in eligible)
    if any(candidate.available_at >= latest for candidate in unknown_amendments):
        return _rejected_selection(decisions, eligible, "revision_scope_unavailable")
    current = [candidate for candidate in eligible if candidate.available_at == latest]
    for candidate in eligible:
        if candidate.available_at < latest:
            decisions.append(
                FiscalCandidateDecisionV1(
                    observation_id=candidate.observation_id,
                    outcome="superseded",
                    reason="later_eligible_disclosure",
                )
            )
    reasons = {
        reason
        for candidate in current
        if (reason := _scope_error(candidate, request)) is not None
    }
    if reasons:
        return _rejected_selection(decisions, current, sorted(reasons)[0])
    if row.statement == "cash_flow" and any(
        candidate.basis.cash_basis is None for candidate in current
    ):
        return _rejected_selection(decisions, current, "cash_basis_unavailable")
    basis = current[0].basis
    if any(candidate.basis != basis for candidate in current):
        return _rejected_selection(decisions, current, "duplicate_basis_conflict")
    intervals = [_interval(candidate) for candidate in current]
    for index, left in enumerate(intervals):
        for right in intervals[index + 1 :]:
            if left is None or right is None:
                if len({candidate.value for candidate in current}) > 1:
                    return _rejected_selection(
                        decisions, current, "source_candidate_conflict"
                    )
            elif not left.overlaps(right):
                return _rejected_selection(
                    decisions, current, "source_candidate_conflict"
                )
    selected = min(
        current,
        key=lambda item: (
            -_precision_order(item),
            item.source_locator.fact_index,
            item.observation_id,
        ),
    )
    decisions.extend(
        FiscalCandidateDecisionV1(
            observation_id=candidate.observation_id,
            outcome="selected" if candidate == selected else "equivalent_duplicate",
            reason="latest_exact_period_highest_precision",
        )
        for candidate in current
    )
    return _Selection(
        selected, tuple(sorted(decisions, key=lambda item: item.observation_id))
    )


def _proof(
    request: FiscalProjectionInputV1,
    row: FiscalRowPolicyV1,
    period: FiscalDurationPeriodV1,
    observations: tuple[FiscalObservationV1, ...],
    component_periods: tuple[FiscalPeriodTargetV1, ...] = (),
) -> FiscalRevisionBasisProofV1 | None:
    by_id = {item.observation_id: item for item in request.observations}
    required = {item.observation_id for item in observations}
    for proof in request.basis_proofs:
        if (
            proof.row_id != row.row_id
            or proof.period != period
            or proof.cutoff_at != request.cutoff_at
            or proof.source_revision != request.source_revision
            or proof.public_available_at > request.cutoff_at
            or proof.component_period_digests
            != tuple(sha256_digest(item) for item in component_periods)
        ):
            continue
        bindings = {
            item.observation_id: item.observation_digest for item in proof.observations
        }
        if not required.issubset(bindings):
            continue
        if any(
            identity not in by_id or by_id[identity].observation_digest != digest
            for identity, digest in bindings.items()
        ):
            continue
        filings = {item.accession_number: item for item in proof.filings}
        if any(
            item.accession_number not in filings
            or filings[item.accession_number].primary_document_sha256
            != item.source_locator.primary_document_sha256
            or filings[item.accession_number].accepted_at != item.accepted_at
            for item in (by_id[identity] for identity in bindings)
        ):
            continue
        if any(item.accepted_at > proof.public_available_at for item in proof.filings):
            continue
        if any(
            by_id[identity].available_at > proof.public_available_at
            for identity in bindings
        ):
            continue
        lineage_invalid = False
        for identity in bindings:
            observation = by_id[identity]
            revision = observation.filing_revision
            if isinstance(revision, AmendedFiscalRevisionV1) and (
                revision.scope == "unknown"
                or filings[observation.accession_number].amends_accession
                != revision.amends_accession
                or revision.amends_accession not in filings
            ):
                lineage_invalid = True
        if lineage_invalid:
            continue
        if any(
            pair.original_id not in bindings or pair.comparative_id not in bindings
            for pair in proof.comparative_pairs
        ):
            continue
        revisions = {item.basis.revision_basis_id for item in observations}
        if len(revisions) > 1 and not any(
            required.issubset({item.observation_id for item in bridge.observations})
            and all(
                bindings.get(item.observation_id) == item.observation_digest
                for item in bridge.observations
            )
            for bridge in proof.revision_bridges
        ):
            continue
        if not observations or any(
            not observations[0].basis.same_accounting_scope(item.basis)
            for item in observations[1:]
        ):
            continue
        return proof
    return None


def _node(
    request: FiscalProjectionInputV1,
    row: FiscalRowPolicyV1,
    target: FiscalPeriodTargetV1,
    *,
    frequency: FiscalFrequency = "quarter",
    availability: FiscalAvailability = "unavailable",
    value: Decimal | None = None,
    observations: tuple[FiscalObservationV1, ...] = (),
    edges: tuple[FiscalInputEdgeV1, ...] = (),
    formula: str | None = None,
    proof: FiscalRevisionBasisProofV1 | None = None,
    reason: str | None = None,
    interval: FiscalPrecisionIntervalV1 | None = None,
    candidates: tuple[FiscalCandidateDecisionV1, ...] = (),
    available_at: datetime | None = None,
    quality: QualityStatus | None = None,
    verification_ids: tuple[str, ...] = (),
    verification_nodes: tuple[str, ...] = (),
    verification_edges: tuple[FiscalInputEdgeV1, ...] = (),
) -> FiscalValueNodeV1:
    proof_ids = (
        {item.observation_id for item in proof.observations}
        if proof is not None
        else set()
    )
    dependency_quality = tuple(
        item.quality
        for item in request.observations
        if item.observation_id in proof_ids
    )
    selected_quality = quality or (
        QualityStatus.PROVISIONAL
        if any(item is QualityStatus.PROVISIONAL for item in dependency_quality)
        or any(item.quality is QualityStatus.PROVISIONAL for item in observations)
        else QualityStatus.VERIFIED
        if value is not None
        else QualityStatus.UNSUPPORTED
    )
    if availability == "unavailable" and _conflict(reason):
        availability = "conflict"
    timestamps = [item.available_at for item in observations]
    if proof is not None:
        timestamps.append(proof.public_available_at)
    if available_at is not None:
        timestamps.append(available_at)
    if timestamps:
        available_at = max(timestamps)
    payload = dict(
        row_id=row.row_id,
        statement=row.statement,
        frequency=frequency,
        period=target.period,
        availability=availability,
        value=value,
        source_observation_ids=tuple(item.observation_id for item in observations),
        verification_observation_ids=verification_ids,
        verification_node_ids=verification_nodes,
        formula=formula,
        policy_id=FISCAL_STATEMENT_POLICY_ID,
        executable_digest=request.executable_digest,
        input_edges=edges,
        verification_edges=verification_edges,
        source_binding_digest=request.source_binding_digest,
        reporting_basis=observations[0].basis if observations else None,
        revision_basis_proof=proof,
        quality=selected_quality,
        precision_interval=interval,
        reason_code=reason,
        candidates=candidates,
        available_at=available_at,
    )
    return FiscalValueNodeV1.model_validate(
        {"node_id": sha256_digest(payload), **payload}
    )


def _reported(
    request: FiscalProjectionInputV1,
    row: FiscalRowPolicyV1,
    target: FiscalPeriodTargetV1,
    selection: _Selection,
    scope_period: FiscalDurationPeriodV1,
) -> FiscalValueNodeV1:
    observation = selection.selected
    if observation is None:
        return _node(
            request,
            row,
            target,
            reason=selection.reason,
            candidates=selection.decisions,
        )
    proof = _proof(request, row, scope_period, (observation,))
    if proof is None:
        return _node(
            request,
            row,
            target,
            reason="revision_basis_unavailable",
            candidates=selection.decisions,
        )
    return _node(
        request,
        row,
        target,
        availability="reported",
        value=observation.value,
        observations=(observation,),
        proof=proof,
        interval=_interval(observation),
        candidates=selection.decisions,
    )


def _quarter(
    request: FiscalProjectionInputV1,
    row: FiscalRowPolicyV1,
    target: FiscalPeriodTargetV1,
) -> FiscalValueNodeV1:
    period = target.period
    if not isinstance(period, FiscalDurationPeriodV1):
        return _node(request, row, target, reason="quarter_duration_required")
    if not 80 <= period.inclusive_days <= 105:
        return _node(request, row, target, reason="irregular_fiscal_period_unsupported")
    if period.fiscal_period == "TTM" or (period.start == period.fiscal_year_start) != (
        period.fiscal_period == "Q1"
    ):
        return _node(request, row, target, reason="fiscal_identity_mismatch")
    if target.cutoff_at != request.cutoff_at:
        return _node(request, row, target, reason="cutoff_mismatch")
    if row.aggregation != "additive_flow":
        instant = (
            period.start - timedelta(days=1)
            if row.aggregation == "cash_opening"
            else period.end
        )
        instant_period = FiscalInstantPeriodV1(
            instant=instant,
            fiscal_year=period.fiscal_year,
            fiscal_period=period.fiscal_period,
        )
        actual = target.model_copy(update={"period": instant_period})
        selection = _select(
            request,
            row,
            lambda item: isinstance(item.period, ReportedInstantV1)
            and item.period.instant == instant,
        )
        return _reported(request, row, actual, selection, period)
    direct = _select(
        request,
        row,
        lambda item: isinstance(item.period, ReportedQuarterV1)
        and item.period.period == period,
    )
    if period.start == period.fiscal_year_start:
        same_span = _select(
            request,
            row,
            lambda item: isinstance(item.period, (ReportedQuarterV1, ReportedYtdV1))
            and item.period.period == period,
        )
        return _reported(request, row, target, same_span, period)
    current = _select(
        request,
        row,
        lambda item: isinstance(item.period, (ReportedYtdV1, ReportedFiscalYearV1))
        and item.period.period.start == period.fiscal_year_start
        and item.period.period.end == period.end
        and item.period.period.fiscal_year_start == period.fiscal_year_start
        and item.period.period.fiscal_year == period.fiscal_year
        and item.period.period.fiscal_period == period.fiscal_period,
    )
    prior_end = period.start - timedelta(days=1)

    def prior_ytd(item: FiscalObservationV1) -> bool:
        if not (
            isinstance(item.period, ReportedYtdV1)
            or isinstance(item.period, ReportedQuarterV1)
            and item.period.applicability == "quarter_and_ytd"
        ):
            return False
        span = item.period.period
        expected_prior = {"Q2": "Q1", "Q3": "Q2", "FY": "Q3"}.get(period.fiscal_period)
        return (
            span.start == period.fiscal_year_start
            and span.end == prior_end
            and span.fiscal_year_start == period.fiscal_year_start
            and span.fiscal_year == period.fiscal_year
            and span.fiscal_period == expected_prior
        )

    prior = _select(request, row, prior_ytd)
    decisions = tuple(
        sorted(
            direct.decisions + current.decisions + prior.decisions,
            key=lambda item: item.observation_id,
        )
    )
    if direct.selected is None and direct.reason not in {
        None,
        "source_period_unavailable",
    }:
        return _node(request, row, target, reason=direct.reason, candidates=decisions)
    if current.selected is None or prior.selected is None:
        severe = next(
            (
                selection.reason
                for selection in (current, prior)
                if selection.reason not in {None, "source_period_unavailable"}
            ),
            None,
        )
        if severe is not None:
            return _node(request, row, target, reason=severe, candidates=decisions)
        if direct.selected is not None:
            return _reported(request, row, target, direct, period)
        reason = (
            "current_ytd_unavailable"
            if current.selected is None
            else "prior_ytd_unavailable"
        )
        return _node(request, row, target, reason=reason, candidates=decisions)
    operands = (current.selected, prior.selected)
    required = operands + ((direct.selected,) if direct.selected is not None else ())
    compatibility = _compatibility_error(required)
    if compatibility is not None:
        return _node(request, row, target, reason=compatibility, candidates=decisions)
    proof = _proof(request, row, period, required)
    if proof is None:
        reason = (
            "revision_basis_mismatch"
            if len({item.basis.revision_basis_id for item in required}) > 1
            else "revision_basis_unavailable"
        )
        return _node(request, row, target, reason=reason, candidates=decisions)
    first, second = operands
    if first.value is None or second.value is None:
        return _node(
            request,
            row,
            target,
            reason="source_value_unavailable",
            candidates=decisions,
        )
    value = first.value - second.value
    interval = _signed_interval(((_interval(first), 1), (_interval(second), -1)))
    if direct.selected is not None:
        direct_interval = _interval(direct.selected)
        if direct_interval is None or interval is None:
            return _node(
                request,
                row,
                target,
                availability="conflict",
                reason="direct_derived_precision_unavailable",
                candidates=decisions,
            )
        if not direct_interval.overlaps(interval):
            return _node(
                request,
                row,
                target,
                availability="conflict",
                reason="direct_derived_conflict",
                candidates=decisions,
            )
        return _node(
            request,
            row,
            target,
            availability="reported",
            value=direct.selected.value,
            observations=(direct.selected,),
            proof=proof,
            interval=direct_interval,
            candidates=decisions,
            formula="reported_quarter_cross_checked_with_ytd_difference",
            verification_ids=tuple(item.observation_id for item in operands),
            verification_edges=(
                FiscalInputEdgeV1(input_id=first.observation_id, coefficient=1),
                FiscalInputEdgeV1(input_id=second.observation_id, coefficient=-1),
            ),
            available_at=max(item.available_at for item in required),
        )
    return _node(
        request,
        row,
        target,
        availability="derived",
        value=value,
        observations=operands,
        proof=proof,
        interval=interval,
        candidates=decisions,
        formula="fiscal_year_minus_nine_months"
        if period.fiscal_period == "FY"
        else "current_ytd_minus_prior_ytd",
        edges=(
            FiscalInputEdgeV1(input_id=first.observation_id, coefficient=1),
            FiscalInputEdgeV1(input_id=second.observation_id, coefficient=-1),
        ),
    )


def _ttm(
    request: FiscalProjectionInputV1,
    row: FiscalRowPolicyV1,
    window: FiscalTtmWindowV1,
    quarter_nodes: dict[tuple[str, str], FiscalValueNodeV1],
    continuity: tuple[FiscalCashContinuityV1, ...],
) -> FiscalValueNodeV1:
    spans = tuple(item.period for item in window.quarters)
    if any(not isinstance(span, FiscalDurationPeriodV1) for span in spans):
        raise FiscalProjectionError(
            "FISCAL_TTM_PERIOD_INVALID", "TTM requires four duration periods"
        )
    durations = tuple(
        span for span in spans if isinstance(span, FiscalDurationPeriodV1)
    )
    last = durations[-1]
    period = FiscalDurationPeriodV1(
        start=min(span.start for span in durations),
        end=max(span.end for span in durations),
        fiscal_year_start=min(span.fiscal_year_start for span in durations),
        fiscal_year=last.fiscal_year,
        fiscal_period="TTM",
        inclusive_days=(
            max(span.end for span in durations) - min(span.start for span in durations)
        ).days
        + 1,
    )
    target = FiscalPeriodTargetV1(
        period_id=window.window_id,
        period=period,
        cutoff_at=request.cutoff_at,
        source_binding_digest=window.source_binding_digest,
    )
    if tuple(span.start for span in durations) != tuple(
        sorted(span.start for span in durations)
    ):
        return _node(
            request, row, target, frequency="ttm", reason="out_of_order_quarters"
        )
    if any(left.end >= right.start for left, right in zip(durations, durations[1:])):
        return _node(
            request, row, target, frequency="ttm", reason="overlapping_quarters"
        )
    if any(
        left.end + timedelta(days=1) != right.start
        for left, right in zip(durations, durations[1:])
    ):
        return _node(request, row, target, frequency="ttm", reason="quarter_gap")
    for left, right in zip(durations, durations[1:]):
        next_period = {"Q1": "Q2", "Q2": "Q3", "Q3": "FY", "FY": "Q1"}.get(
            left.fiscal_period
        )
        if (
            right.fiscal_period != next_period
            or right.fiscal_year != left.fiscal_year + (left.fiscal_period == "FY")
        ):
            return _node(
                request, row, target, frequency="ttm", reason="fiscal_identity_mismatch"
            )
        if (
            left.fiscal_period != "FY"
            and left.fiscal_year_start != right.fiscal_year_start
        ):
            return _node(
                request,
                row,
                target,
                frequency="ttm",
                reason="fiscal_year_start_mismatch",
            )
    known_targets = {item.period_id: item for item in request.quarter_targets}
    if any(item.period_id not in known_targets for item in window.quarters):
        return _node(request, row, target, frequency="ttm", reason="missing_quarter")
    if any(item != known_targets[item.period_id] for item in window.quarters):
        return _node(
            request,
            row,
            target,
            frequency="ttm",
            reason="ttm_component_period_mismatch",
        )
    if not 350 <= period.inclusive_days <= 380:
        return _node(
            request,
            row,
            target,
            frequency="ttm",
            reason="irregular_ttm_period_unsupported",
        )
    components = tuple(
        quarter_nodes.get((item.period_id, row.row_id)) for item in window.quarters
    )
    required_components = (
        components
        if row.aggregation == "additive_flow"
        else (components[0],)
        if row.aggregation == "cash_opening"
        else (components[-1],)
    )
    if any(
        component is None or component.value is None
        for component in required_components
    ):
        conflicting = next(
            (
                component
                for component in required_components
                if component is not None and component.availability == "conflict"
            ),
            None,
        )
        return _node(
            request,
            row,
            target,
            frequency="ttm",
            reason=conflicting.reason_code
            if conflicting
            else "required_quarter_unavailable",
            edges=tuple(
                FiscalInputEdgeV1(input_id=component.node_id, coefficient=1)
                for component in required_components
                if component is not None
            ),
        )
    available = tuple(
        component for component in required_components if component is not None
    )
    source_ids = tuple(
        dict.fromkeys(
            identity
            for component in available
            for identity in component.source_observation_ids
        )
    )
    by_id = {item.observation_id: item for item in request.observations}
    observations = tuple(by_id[identity] for identity in source_ids)
    compatibility = _compatibility_error(observations)
    if compatibility is not None:
        return _node(request, row, target, frequency="ttm", reason=compatibility)
    if row.aggregation in {"cash_opening", "cash_closing"}:
        cash_bases = {
            component.reporting_basis.cash_basis
            for component in components
            if component is not None and component.reporting_basis is not None
        }
        if len(cash_bases) > 1:
            return _node(
                request,
                row,
                target,
                frequency="ttm",
                reason="cash_boundary_basis_mismatch",
            )
    cash_checks = continuity if row.statement == "cash_flow" else ()
    verification_ids = tuple(
        dict.fromkeys(
            identity for check in cash_checks for identity in check.input_node_ids
        )
    )
    verification_nodes = tuple(
        node for node in quarter_nodes.values() if node.node_id in verification_ids
    )
    conflict = next(
        (check for check in cash_checks if check.status == "conflict"), None
    )
    if conflict is not None:
        return _node(
            request,
            row,
            target,
            frequency="ttm",
            reason=conflict.reason_code,
            verification_nodes=verification_ids,
        )
    proof = _proof(request, row, period, observations, window.quarters)
    if proof is None:
        reason = (
            "revision_basis_mismatch"
            if len({item.basis.revision_basis_id for item in observations}) > 1
            else "revision_basis_unavailable"
        )
        return _node(request, row, target, frequency="ttm", reason=reason)
    value: Decimal | None
    if row.aggregation == "additive_flow":
        value = sum(
            (component.value for component in available if component.value is not None),
            Decimal(0),
        )
        selected = available
        interval = _signed_interval(
            tuple((component.precision_interval, 1) for component in selected)
        )
        formula = "sum_four_contiguous_quarters"
    else:
        selected = available
        value = selected[0].value
        interval = selected[0].precision_interval
        formula = (
            "window_opening_cash"
            if row.aggregation == "cash_opening"
            else "window_ending_cash"
            if row.aggregation == "cash_closing"
            else "same_end_balance_sheet_instant"
        )
        target = target.model_copy(
            update={
                "period": selected[0].period.model_copy(update={"fiscal_period": "TTM"})
            }
        )
    quality = (
        QualityStatus.PROVISIONAL
        if any(
            component.quality is QualityStatus.PROVISIONAL
            for component in selected + verification_nodes
        )
        or any(
            check.status != "consistent_at_reported_precision" for check in cash_checks
        )
        or any(
            by_id[item.observation_id].quality is QualityStatus.PROVISIONAL
            for item in proof.observations
        )
        else QualityStatus.VERIFIED
    )
    return _node(
        request,
        row,
        target,
        frequency="ttm",
        availability="derived" if row.aggregation == "additive_flow" else "reported",
        value=value,
        observations=observations,
        proof=proof,
        edges=tuple(
            FiscalInputEdgeV1(input_id=component.node_id, coefficient=1)
            for component in selected
        ),
        formula=formula,
        interval=interval,
        available_at=max(
            component.available_at
            for component in selected + verification_nodes
            if component.available_at is not None
        ),
        quality=quality,
        verification_nodes=verification_ids,
    )


def _cash_continuity(
    window: FiscalTtmWindowV1,
    nodes: dict[tuple[str, str], FiscalValueNodeV1],
) -> tuple[FiscalCashContinuityV1, ...]:
    checks = []
    for left, right in zip(window.quarters, window.quarters[1:]):
        closing = nodes.get((left.period_id, "cash_flow_ending_balance"))
        opening = nodes.get((right.period_id, "cash_flow_beginning_balance"))
        pair = tuple(node for node in (closing, opening) if node is not None)
        status, reason = "unresolved_missing_inputs", None
        if any(node.availability == "conflict" for node in pair):
            status, reason = (
                "conflict",
                next(
                    node.reason_code for node in pair if node.availability == "conflict"
                ),
            )
        elif len(pair) == 2 and all(node.value is not None for node in pair):
            first, second = pair
            if (
                first.reporting_basis is None
                or second.reporting_basis is None
                or not first.reporting_basis.same_accounting_scope(
                    second.reporting_basis
                )
            ):
                status, reason = "conflict", "cash_boundary_basis_mismatch"
            elif (
                first.reporting_basis.revision_basis_id
                != second.reporting_basis.revision_basis_id
            ):
                status, reason = "conflict", "revision_basis_mismatch"
            elif (
                not isinstance(first.period, FiscalInstantPeriodV1)
                or not isinstance(second.period, FiscalInstantPeriodV1)
                or first.period.instant != second.period.instant
            ):
                status, reason = "conflict", "cash_boundary_period_mismatch"
            else:
                status = "unresolved_precision"
            if (
                status == "unresolved_precision"
                and first.precision_interval is not None
                and second.precision_interval is not None
            ):
                status = (
                    "consistent_at_reported_precision"
                    if first.precision_interval.overlaps(second.precision_interval)
                    else "conflict"
                )
                reason = (
                    None
                    if status == "consistent_at_reported_precision"
                    else "cash_continuity_conflict"
                )
        checks.append(
            FiscalCashContinuityV1.model_validate(
                dict(
                    window_id=window.window_id,
                    boundary_date=left.period.end
                    if isinstance(left.period, FiscalDurationPeriodV1)
                    else left.period.instant,
                    status=status,
                    input_node_ids=tuple(node.node_id for node in pair),
                    reason_code=reason,
                )
            )
        )
    return tuple(checks)


def _reconcile(
    period_id: str, frequency: FiscalFrequency, nodes: tuple[FiscalValueNodeV1, ...]
) -> tuple[FiscalReconciliationV1, ...]:
    by_row = {node.row_id: node for node in nodes}
    rules = (
        (
            "opening_plus_change_equals_closing",
            (
                ("cash_flow_beginning_balance", 1),
                ("net_change_in_cash", 1),
                ("cash_flow_ending_balance", -1),
            ),
        ),
        (
            "flows_plus_fx_equals_change",
            (
                ("operating_cash_flow", 1),
                ("investing_cash_flow", 1),
                ("financing_cash_flow", 1),
                ("effect_of_exchange_rates_on_cash", 1),
                ("net_change_in_cash", -1),
            ),
        ),
    )
    results = []
    zero = FiscalPrecisionIntervalV1(
        lower=Decimal(0), upper=Decimal(0), upper_inclusive=True
    )
    for rule, terms in rules:
        inputs = tuple((by_row[row_id], coefficient) for row_id, coefficient in terms)
        status, residual, interval, reason = (
            "unresolved_missing_inputs",
            None,
            None,
            None,
        )
        bases = tuple(
            node.reporting_basis
            for node, _ in inputs
            if node.reporting_basis is not None
        )
        if any(node.availability == "conflict" for node, _ in inputs):
            status, reason = "conflict", "input_conflict"
        elif all(node.value is not None for node, _ in inputs):
            if bases and any(
                not bases[0].same_accounting_scope(basis) for basis in bases[1:]
            ):
                status, reason = "conflict", "cash_basis_mismatch"
            elif bases and len({basis.revision_basis_id for basis in bases}) > 1:
                status, reason = "conflict", "revision_basis_mismatch"
            else:
                residual = sum(
                    (
                        node.value * coefficient
                        for node, coefficient in inputs
                        if node.value is not None
                    ),
                    Decimal(0),
                )
                interval = _signed_interval(
                    tuple(
                        (node.precision_interval, coefficient)
                        for node, coefficient in inputs
                    )
                )
                status = (
                    "unresolved_precision"
                    if interval is None
                    else "consistent_at_reported_precision"
                    if interval.overlaps(zero)
                    else "conflict"
                )
        results.append(
            FiscalReconciliationV1.model_validate(
                dict(
                    period_id=period_id,
                    frequency=frequency,
                    rule=rule,
                    status=status,
                    input_node_ids=tuple(node.node_id for node, _ in inputs),
                    residual=residual,
                    precision_interval=interval,
                    reason_code=reason,
                )
            )
        )
    return tuple(results)


def project_fiscal_statements(
    request: FiscalProjectionInputV1,
) -> FiscalProjectionResultV1:
    """Project service-owned mapped inputs without granting display admission."""
    policy = fiscal_statement_policy()
    identities = tuple(item.observation_id for item in request.observations)
    if len(set(identities)) != len(identities):
        raise FiscalProjectionError(
            "FISCAL_OBSERVATION_DUPLICATE", "observation identities must be unique"
        )
    targets = tuple(item.period_id for item in request.quarter_targets)
    if len(set(targets)) != len(targets):
        raise FiscalProjectionError(
            "FISCAL_PERIOD_DUPLICATE", "quarter target identities must be unique"
        )
    proof_keys = tuple(
        (item.row_id, item.period.start, item.period.end)
        for item in request.basis_proofs
    )
    if len(set(proof_keys)) != len(proof_keys):
        raise FiscalProjectionError(
            "FISCAL_BASIS_PROOF_AMBIGUOUS", "basis proof scopes must be unique"
        )
    values = [item.value for item in request.observations if item.value is not None]
    values.extend(
        Decimal((0, (1,), -item.decimals - 1))
        for item in request.observations
        if isinstance(item.decimals, int) and abs(item.decimals) <= 10_000
    )
    with localcontext(_numeric_context(values)):
        quarters = tuple(
            _quarter(request, row, target)
            for target in request.quarter_targets
            for row in policy.rows
        )
        by_cell: dict[tuple[str, str], FiscalValueNodeV1] = {
            (target.period_id, row.row_id): quarters[
                index * len(policy.rows) + row_index
            ]
            for index, target in enumerate(request.quarter_targets)
            for row_index, row in enumerate(policy.rows)
        }
        continuity = {
            window.window_id: _cash_continuity(window, by_cell)
            for window in request.ttm_windows
        }
        ttms = tuple(
            _ttm(request, row, window, by_cell, continuity[window.window_id])
            for window in request.ttm_windows
            for row in policy.rows
        )
        reconciliations = tuple(
            result
            for index, target in enumerate(request.quarter_targets)
            for result in _reconcile(
                target.period_id,
                "quarter",
                quarters[index * len(policy.rows) : (index + 1) * len(policy.rows)],
            )
        ) + tuple(
            result
            for index, window in enumerate(request.ttm_windows)
            for result in _reconcile(
                window.window_id,
                "ttm",
                ttms[index * len(policy.rows) : (index + 1) * len(policy.rows)],
            )
        )
    known = {row.row_id for row in policy.rows}
    return FiscalProjectionResultV1(
        policy_id=policy.policy_id,
        executable_digest=request.executable_digest,
        quarter_nodes=quarters,
        ttm_nodes=ttms,
        unsupported_rows=tuple(
            sorted({item.row_id for item in request.observations} - known)
        ),
        source_observations=request.observations,
        quarter_periods=request.quarter_targets,
        ttm_windows=request.ttm_windows,
        reconciliations=reconciliations,
        cash_continuities=tuple(
            check for checks in continuity.values() for check in checks
        ),
        quality=QualityStatus.PROVISIONAL
        if any(node.quality is not QualityStatus.VERIFIED for node in quarters + ttms)
        or any(
            check.status != "consistent_at_reported_precision"
            for check in reconciliations
        )
        else QualityStatus.VERIFIED,
    )
