from datetime import UTC, datetime
from decimal import Decimal

from fundamental_service.forward_evidence import (
    ForwardEvidenceClaimStatus,
    ForwardEvidenceClaimV1,
    ForwardEvidenceExtractionMethod,
    ForwardEvidenceLicenseStatus,
    ForwardEvidenceMetric,
    ForwardEvidencePeriodType,
    ForwardEvidenceReviewRequestV1,
    ForwardEvidenceSourceV1,
    review_forward_evidence,
)


def _source(
    *,
    passage: str = "Management expects revenue growth of 12 percent in fiscal 2027.",
    published_at: datetime | None = None,
    license_status: ForwardEvidenceLicenseStatus = ForwardEvidenceLicenseStatus.APPROVED,
    license_reference: str | None = "provider-terms-v1",
) -> ForwardEvidenceSourceV1:
    import hashlib

    effective_published_at = published_at or datetime(2026, 10, 1, tzinfo=UTC)
    return ForwardEvidenceSourceV1(
        source_id="source-1",
        source_url="https://issuer.example/guidance",
        publisher="Issuer IR",
        source_type="issuer_guidance",
        retained_passage=passage,
        content_hash=hashlib.sha256(passage.encode()).hexdigest(),
        published_at=effective_published_at,
        retrieved_at=max(effective_published_at, datetime(2026, 10, 2, tzinfo=UTC)),
        license_status=license_status,
        license_reference=license_reference,
    )


def _claim(
    *,
    claim_id: str = "claim-1",
    value: str = "0.12",
    source: ForwardEvidenceSourceV1 | None = None,
    status: ForwardEvidenceClaimStatus = ForwardEvidenceClaimStatus.ACCEPTED,
    issue_codes: tuple[str, ...] = (),
) -> ForwardEvidenceClaimV1:
    return ForwardEvidenceClaimV1(
        claim_id=claim_id,
        issuer_id="issuer-aapl",
        ticker="AAPL",
        model_id="fcff_dcf",
        metric=ForwardEvidenceMetric.REVENUE_GROWTH,
        assumption_path="assumptions.forecast.revenue_growth[0]",
        value=Decimal(value),
        unit="ratio",
        fiscal_period="FY2027",
        period_type=ForwardEvidencePeriodType.ANNUAL,
        period_end=datetime(2027, 9, 30, tzinfo=UTC).date(),
        extraction_method=ForwardEvidenceExtractionMethod.LLM_FROM_SOURCE_PASSAGE,
        source=source or _source(),
        status=status,
        issue_codes=issue_codes,
        exclusion_reasons=issue_codes,
    )


def _request(*claims: ForwardEvidenceClaimV1) -> ForwardEvidenceReviewRequestV1:
    return ForwardEvidenceReviewRequestV1(
        opt_in=True,
        ticker="AAPL",
        issuer_id="issuer-aapl",
        model_id="fcff_dcf",
        assumption_path="assumptions.forecast.revenue_growth[0]",
        valuation_timestamp=datetime(2026, 11, 1, tzinfo=UTC),
        automatic_preparation_digest="a" * 64,
        claims=claims,
    )


def test_review_accepts_licensed_forward_claim_and_binds_digest() -> None:
    result = review_forward_evidence(_request(_claim()))

    assert result.status == "prepared"
    assert result.accepted_claim_ids == ("claim-1",)
    assert result.claims[0].status is ForwardEvidenceClaimStatus.ACCEPTED
    assert result.reference_digest != "a" * 64


def test_review_excludes_unlicensed_claim_with_reason() -> None:
    claim = _claim(
        source=_source(
            license_status=ForwardEvidenceLicenseStatus.UNKNOWN,
            license_reference=None,
        )
    )

    result = review_forward_evidence(_request(claim))

    assert result.status == "unsupported"
    assert result.excluded_claim_ids == ("claim-1",)
    assert result.claims[0].issue_codes == ("SOURCE_LICENSE_NOT_APPROVED",)


def test_review_excludes_stale_and_historical_period_claim() -> None:
    claim = _claim(
        source=_source(
            published_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
    ).model_copy(update={"period_end": datetime(2026, 9, 30, tzinfo=UTC).date()})

    result = review_forward_evidence(_request(claim))

    assert result.status == "unsupported"
    assert set(result.claims[0].issue_codes) == {
        "SOURCE_STALE",
        "FORWARD_PERIOD_MISMATCH",
    }


def test_review_excludes_conflicting_claims_as_a_group() -> None:
    result = review_forward_evidence(
        _request(_claim(), _claim(claim_id="claim-2", value="0.15"))
    )

    assert result.status == "unsupported"
    assert set(result.excluded_claim_ids) == {"claim-1", "claim-2"}
    assert all(claim.issue_codes == ("CONFLICTING_SOURCES",) for claim in result.claims)


def test_review_excludes_reference_only_debt_term_without_changing_baseline() -> None:
    claim = _claim().model_copy(
        update={
            "metric": ForwardEvidenceMetric.DEBT_TERM,
            "assumption_path": None,
        }
    )

    result = review_forward_evidence(_request(claim))

    assert result.status == "unsupported"
    assert "REFERENCE_ONLY_METRIC" in result.claims[0].issue_codes


def test_review_rejects_future_source_before_policy_evaluation() -> None:
    claim = _claim(
        source=_source(
            published_at=datetime(2026, 12, 1, tzinfo=UTC),
        )
    )

    result = review_forward_evidence(_request(claim))

    assert result.claims[0].issue_codes == ("SOURCE_PUBLISHED_AFTER_VALUATION",)
