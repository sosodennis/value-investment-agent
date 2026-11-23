"""Research witnesses retain authenticated reviewed terminal claims through calculation."""

import hashlib
import json
from datetime import timedelta
from decimal import Decimal

import pytest

from fundamental_service.forward_evidence import (
    FORWARD_EVIDENCE_POLICY_VERSION,
    ForwardEvidenceMetric,
    ForwardEvidenceReviewRequestV1,
    review_forward_evidence,
)
from fundamental_service.testsupport import auth_headers
from fundamental_service.valuation_preparation import AutomaticValuationPreparationV1
from test_conditional_revision import _calculate, _envelope, _prepared, _request
from test_forward_evidence import _claim, _source


def _review_request(automatic):
    at = automatic.input.valuation_context.valuation_timestamp
    passage = "External source expects long-term terminal growth of 2.5 percent; user assumption only."
    source = _source(passage=passage, published_at=at - timedelta(days=1)).model_copy(
        update={"retrieved_at": at}
    )
    claim = _claim(value="0.025", source=source).model_copy(
        update={
            "metric": ForwardEvidenceMetric.TERMINAL_GROWTH,
            "assumption_path": "assumptions.terminal_growth",
            "issuer_id": automatic.input.identity.issuer_id,
            "ticker": automatic.input.identity.security_id,
            "model_id": automatic.model_id,
            "period_end": at.date() + timedelta(days=3650),
            "fiscal_period": "long-term",
        }
    )
    return ForwardEvidenceReviewRequestV1(
        opt_in=True,
        ticker=claim.ticker,
        issuer_id=claim.issuer_id,
        model_id=claim.model_id,
        assumption_path=claim.assumption_path,
        valuation_timestamp=at,
        automatic_preparation_digest=automatic.preparation_digest,
        claims=(claim,),
    )


def _review(
    client, request, *, subject="subject-test", organization="organization-test"
):
    return client.post(
        "/v1/valuation/forward-evidence/review",
        headers=auth_headers(organization_id=organization),
        json=_envelope(
            request.model_dump(mode="json"), subject=subject, organization=organization
        ),
    )


def _researched(tmp_path):
    fixture, client, _, automatic = _prepared(tmp_path)
    request = _review_request(automatic)
    response = _review(client, request)
    assert response.status_code == 200, response.text
    review = response.json()["result"]
    assert review["status"] == "prepared" and review["review_ref"]
    apply = _request(automatic)
    apply["forward_review_ref"] = review["review_ref"]
    source = request.claims[0].source
    apply["provenance"]["forward_reference"] = {
        "claim_id": request.claims[0].claim_id,
        "source_url": source.source_url,
        "source_content_hash": source.content_hash,
        "citation": source.retained_passage,
        "license_reference": source.license_reference,
    }
    return fixture, client, automatic, request, review, apply


def _apply(client, apply, **scope):
    return client.post(
        "/v1/valuation/prepare/override",
        headers=auth_headers(
            organization_id=scope.get("organization", "organization-test")
        ),
        json=_envelope(apply, **scope),
    )


def test_research_apply_and_recalculate_retains_real_service_witness(tmp_path):
    fixture, client, automatic, request, review, apply = _researched(tmp_path)
    assert review["policy_version"] == FORWARD_EVIDENCE_POLICY_VERSION
    assert review["claims"][0]["metric"] == "terminal_growth"
    ref = review["review_ref"]
    witness = json.loads(fixture.artifacts.read(ref["artifact_id"]))
    assert "review_ref" not in witness["review"]
    assert witness["request"] == request.model_dump(mode="json")
    assert witness["actor"] == {
        "subject_id": "subject-test",
        "organization_id": "organization-test",
    }
    assert (
        hashlib.sha256(fixture.artifacts.read(ref["artifact_id"])).hexdigest()
        == ref["content_hash"]
    )
    response = _apply(client, apply)
    assert response.status_code == 200, response.text
    revised = AutomaticValuationPreparationV1.model_validate_json(
        json.dumps(response.json()["result"])
    )
    assert revised.input.assumptions.terminal_growth == Decimal("0.025")
    assert revised.input.uncertainty.scenarios == automatic.input.uncertainty.scenarios
    assert revised.quality_status == automatic.quality_status
    manual = revised.assumptions_evidence[-1]
    assert (
        manual.manual_provenance.forward_reference.citation
        == request.claims[0].source.retained_passage
    )
    assert manual.source_refs == (request.claims[0].source.content_hash,)
    proof_ref = revised.input.provenance.conditional_revision_ref
    assert (
        ref["content_hash"]
        in fixture.artifacts.get(proof_ref.artifact_id).dependency_hashes
    )
    proof = json.loads(fixture.artifacts.read(proof_ref.artifact_id))
    assert proof["forward_review_ref"] == ref
    first = _calculate(client, revised.input)
    assert first.status_code == 200, first.text
    assert first.json()["result"]["requested_samples"] == 256
    assert _calculate(client, revised.input).json()["result"] == first.json()["result"]
    for suffix in ("", "/content"):
        read = client.request(
            "GET",
            f"/v1/artifacts/{ref['artifact_id']}{suffix}",
            headers=auth_headers(),
            json=_envelope({}),
        )
        assert read.status_code == 200, read.text


@pytest.mark.parametrize(
    "field,value,code",
    (
        (
            "metric",
            ForwardEvidenceMetric.REVENUE_GROWTH,
            "TERMINAL_METRIC_PATH_MISMATCH",
        ),
        ("unit", "currency", "TERMINAL_GROWTH_INVALID"),
        ("value", Decimal("0.041"), "TERMINAL_GROWTH_INVALID"),
        ("value", Decimal("-0.001"), "TERMINAL_GROWTH_INVALID"),
    ),
)
def test_terminal_review_requires_terminal_metric_ratio_and_prior_domain(
    tmp_path, field, value, code
):
    _, _, _, automatic = _prepared(tmp_path)
    request = _review_request(automatic)
    request = request.model_copy(
        update={"claims": (request.claims[0].model_copy(update={field: value}),)}
    )
    reviewed = review_forward_evidence(request)
    assert reviewed.status == "unsupported"
    assert code in reviewed.claims[0].issue_codes


@pytest.mark.parametrize(
    "fault",
    (
        "missing_ref",
        "missing_cite",
        "claim",
        "value",
        "cite",
        "url",
        "hash",
        "license",
        "fake_ref",
        "other_owner",
        "other_org",
    ),
)
def test_compact_citation_or_different_claim_cannot_authorize_apply(tmp_path, fault):
    _, client, _, _, _, apply = _researched(tmp_path)
    if fault == "missing_ref":
        apply.pop("forward_review_ref")
    elif fault == "missing_cite":
        apply["provenance"].pop("forward_reference")
    elif fault == "value":
        apply["value"] = "0.026"
    elif fault == "fake_ref":
        apply["forward_review_ref"] = {
            "artifact_id": "forward-review-v1-" + "f" * 64,
            "content_hash": "f" * 64,
        }
    elif fault not in {"other_owner", "other_org"}:
        field, value = {
            "claim": ("claim_id", "other"),
            "cite": (
                "citation",
                "A different long source passage that was never reviewed.",
            ),
            "url": ("source_url", "https://other.test"),
            "hash": ("source_content_hash", "f" * 64),
            "license": ("license_reference", "other-terms"),
        }[fault]
        apply["provenance"]["forward_reference"][field] = value
    response = _apply(
        client,
        apply,
        **(
            {"subject": "other"}
            if fault == "other_owner"
            else {"organization": "other"}
            if fault == "other_org"
            else {}
        ),
    )
    assert response.status_code == (
        403 if fault in {"other_owner", "other_org"} else 422
    ), response.text


@pytest.mark.parametrize(
    "fault", ("issuer", "ticker", "model", "prep", "valuation", "path")
)
def test_successful_review_for_different_binding_cannot_be_applied(tmp_path, fault):
    _, client, automatic, request, _, apply = _researched(tmp_path)
    changes = {
        "issuer": {"issuer_id": "other"},
        "ticker": {"ticker": "OTHER"},
        "model": {"model_id": "transition_fcff_dcf"},
        "prep": {"automatic_preparation_digest": "f" * 64},
        "valuation": {
            "valuation_timestamp": request.valuation_timestamp + timedelta(days=1)
        },
        "path": {"assumption_path": "assumptions.forecast.revenue_growth[0]"},
    }[fault]
    claim_changes = {
        key: value
        for key, value in changes.items()
        if key in {"issuer_id", "ticker", "model_id", "assumption_path"}
    }
    if fault == "path":
        claim_changes["metric"] = ForwardEvidenceMetric.REVENUE_GROWTH
    other = request.model_copy(
        update={
            **changes,
            "claims": (request.claims[0].model_copy(update=claim_changes),),
        }
    )
    response = _review(client, other)
    assert response.status_code == 200, response.text
    assert response.json()["result"]["status"] == "prepared"
    apply["forward_review_ref"] = response.json()["result"]["review_ref"]
    response = _apply(client, apply)
    assert response.status_code == 422, response.text


def test_withdrawn_witness_refuses_calculation_and_all_dependent_evidence_reads(
    tmp_path,
):
    fixture, client, _, _, review, apply = _researched(tmp_path)
    response = _apply(client, apply)
    assert response.status_code == 200, response.text
    revised = AutomaticValuationPreparationV1.model_validate_json(
        json.dumps(response.json()["result"])
    )
    calculated = _calculate(client, revised.input)
    assert calculated.status_code == 200, calculated.text
    result = calculated.json()["result"]
    ids = {
        review["review_ref"]["artifact_id"],
        revised.input.provenance.conditional_revision_ref.artifact_id,
        *(ref["artifact_id"] for ref in result["base"]["artifact_references"]),
        *(ref["artifact_id"] for ref in result["artifact_references"]),
    }
    fixture.artifacts.invalidate(review["review_ref"]["artifact_id"])
    assert _calculate(client, revised.input).status_code == 422
    for artifact_id in ids:
        for suffix in ("", "/content"):
            response = client.request(
                "GET",
                f"/v1/artifacts/{artifact_id}{suffix}",
                headers=auth_headers(),
                json=_envelope({}),
            )
            assert response.status_code == 422, response.text


def test_witness_metadata_and_content_are_owner_scoped(tmp_path):
    _, client, _, _, review, _ = _researched(tmp_path)
    for scope in ({"subject": "other"}, {"organization": "other"}):
        for suffix in ("", "/content"):
            response = client.request(
                "GET",
                f"/v1/artifacts/{review['review_ref']['artifact_id']}{suffix}",
                headers=auth_headers(
                    organization_id=scope.get("organization", "organization-test")
                ),
                json=_envelope({}, **scope),
            )
            assert response.status_code == 403, response.text
            assert (
                "content_hash" not in response.text
                and "retained_passage" not in response.text
            )


@pytest.mark.parametrize(
    "fault",
    ("unknown_license", "rejected_license", "stale", "future", "content", "conflict"),
)
def test_unadmitted_terminal_sources_never_receive_review_witness(tmp_path, fault):
    from fundamental_service.forward_evidence import ForwardEvidenceLicenseStatus

    _, client, _, automatic = _prepared(tmp_path)
    request = _review_request(automatic)
    claim = request.claims[0]
    if fault == "conflict":
        claims = (
            claim,
            claim.model_copy(
                update={"claim_id": "conflicting-claim", "value": Decimal("0.026")}
            ),
        )
    else:
        source = claim.source
        changes = {
            "unknown_license": {"license_status": ForwardEvidenceLicenseStatus.UNKNOWN},
            "rejected_license": {
                "license_status": ForwardEvidenceLicenseStatus.REJECTED
            },
            "stale": {
                "published_at": request.valuation_timestamp - timedelta(days=366)
            },
            "future": {
                "published_at": request.valuation_timestamp + timedelta(days=1),
                "retrieved_at": request.valuation_timestamp + timedelta(days=1),
            },
            "content": {"content_hash": "f" * 64},
        }[fault]
        claims = (
            claim.model_copy(update={"source": source.model_copy(update=changes)}),
        )
    request = request.model_copy(update={"claims": claims})
    response = _review(client, request)
    assert response.status_code == 200, response.text
    reviewed = response.json()["result"]
    assert reviewed["status"] == "unsupported"
    assert "review_ref" not in reviewed
    assert reviewed["accepted_claim_ids"] == []
