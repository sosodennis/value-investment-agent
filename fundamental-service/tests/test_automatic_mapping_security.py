"""Machine mapping requires exact original DEI before asserting a security."""

from decimal import Decimal

import pytest

from fundamental_service.accounting_roles import AccountingRoleRuleSetV1
from fundamental_service.automatic_mapping import (
    AutomaticMappingDecisionV1,
    AutomaticMappingRequestV1,
    verify_automatic_mapping_replay,
)
from fundamental_service.automatic_mapping_batch import AutomaticMappingBatchRequestV1
from fundamental_service.automatic_mapping_runner import approve_mapping_batch
from fundamental_service.contracts import IdentityV1, SourceRecordV1, SourceRole
from fundamental_service.data_releases import (
    AutomaticMappingApprovalV1,
    DataReleaseError,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from fundamental_service.valuation_requirements import valuation_requirements_profile
from test_automatic_mapping import approve, case, evaluate, MACHINE_KEY
from test_automatic_mapping_disclosures import expense_case
from test_issuer_operating_release import inventory


def security_case(tmp_path, *, omitted=None, altered=None, duplicate=False):
    initial, _, _, _ = case(tmp_path / "markers")
    marker = next(
        f for f in initial.original.report.facts if f.concept == "dei:DocumentType"
    )
    values = {
        "dei:EntityIncorporationStateCountryCode": "DE",
        "dei:TradingSymbol": "EXAMPLE",
        "dei:Security12bTitle": "Common Stock",
    }
    extra = tuple(
        marker.model_copy(
            update={"concept": concept, "value": value, **(altered or {})}
        )
        for concept, value in values.items()
        if concept != omitted
    )
    if duplicate:
        extra += (extra[-1].model_copy(update={"value": "Preferred Stock"}),)
    request, store, roots, _ = expense_case(tmp_path / "expense", extra_facts=extra)
    identity = IdentityV1(
        issuer_id=request.original.source.cik,
        issuer_name=request.original.identity.issuer_name,
        domicile="US",
        reporting_basis="us-gaap",
        currency="USD",
        security_id="EXAMPLE",
        share_class="Common Stock",
    )
    return request.model_copy(update={"security_identity": identity}), store, roots


def security_source(request):
    original = request.original.source
    return SourceRecordV1(
        source_id="sec-filing",
        uri=original.uri,
        role=SourceRole.FILING,
        available_at=original.available_at,
        captured_at=original.captured_at,
        http_status=200,
        media_type="application/xhtml+xml",
        terms_reference="synthetic SEC boundary fixture",
        content_hash=original.content_hash,
        parser_input_hash=original.parser_input_hash,
        parser_version=request.original.report.parser_version,
        accession_number=original.accession_number,
        form="10-K",
    )


def test_original_bound_security_expense_rebuilds_and_reuses_exact_evidence(tmp_path):
    request, store, roots = security_case(tmp_path)
    assert (
        AutomaticMappingRequestV1.model_validate_json(canonical_bytes(request))
        == request
    )
    receipt = approve(request, store, roots)
    decision = evaluate(request, store)
    assert decision.status == "approved"
    mapping = decision.mapping
    assert isinstance(mapping.accounting_rules, AccountingRoleRuleSetV1)
    assert mapping.accounting_rules.security_id == "EXAMPLE"
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=security_source(request),
        issuer_id=request.original.source.cik,
        security_id="EXAMPLE",
        normalized_field="stock_based_compensation",
        mapping=mapping,
    )
    assert len(candidates) == 1 and candidates[0].value == Decimal("141936")
    assert candidates[0].security_id == "EXAMPLE"
    assert candidates[0].accounting_evidence.rule_set == mapping.accounting_rules
    approval = AutomaticMappingApprovalV1.model_validate_json(
        store.read(receipt.approval_publication.artifact.artifact_id)
    )
    assert (
        verify_automatic_mapping_replay(approval, mapping, artifacts=store) == request
    )
    before = inventory(store.root)
    repeated = approve(request, store, roots)
    assert repeated.output_digest == receipt.output_digest
    assert not repeated.input_publication.wrote
    assert not repeated.decision_publication.wrote
    assert not repeated.approval_publication.wrote
    assert inventory(store.root) == before
    changed_rules = mapping.accounting_rules.model_copy(update={"security_id": "OTHER"})
    forged = mapping.model_copy(update={"accounting_rules": changed_rules})
    with pytest.raises(DataReleaseError, match="retained policy evaluation"):
        verify_automatic_mapping_replay(approval, forged, artifacts=store)


@pytest.mark.parametrize("issuer_only", (False, True))
def test_security_bound_expense_cannot_be_rebuilt_as_another_security_or_issuer_only(
    tmp_path, issuer_only
):
    request, store, _ = security_case(tmp_path)
    mapping = evaluate(request, store).mapping
    with pytest.raises(SnapshotError):
        parsed_facts_to_candidates(
            request.original.report,
            source=request.original.source if issuer_only else security_source(request),
            issuer_id=request.original.source.cik,
            security_id=None if issuer_only else "OTHER",
            normalized_field="stock_based_compensation",
            mapping=mapping,
        )


@pytest.mark.parametrize(
    "change",
    (
        {"issuer_id": "0000000999"},
        {"issuer_name": "Other Company"},
        {"security_id": "OTHER"},
        {"share_class": "Preferred Stock"},
        {"domicile": "GB"},
        {"currency": "EUR"},
        {"reporting_basis": "ifrs"},
    ),
)
def test_unproved_security_identity_is_retained_without_a_certificate(tmp_path, change):
    request, store, roots = security_case(tmp_path)
    request = request.model_copy(
        update={
            "security_identity": request.security_identity.model_copy(update=change)
        }
    )
    decision = evaluate(request, store)
    assert decision.status == "abstain" and decision.mapping is None
    assert any(
        code.startswith("HISTORICAL_IDENTITY_") for code in decision.reason_codes
    )
    receipt = approve(request, store, roots)
    assert receipt.approval_publication is None
    assert (
        AutomaticMappingDecisionV1.model_validate_json(
            store.read(receipt.decision_publication.artifact.artifact_id)
        )
        == decision
    )


@pytest.mark.parametrize(
    "changes,reason",
    (
        ({"omitted": "dei:TradingSymbol"}, "HISTORICAL_IDENTITY_MISSING"),
        ({"omitted": "dei:Security12bTitle"}, "HISTORICAL_IDENTITY_MISSING"),
        (
            {"omitted": "dei:EntityIncorporationStateCountryCode"},
            "HISTORICAL_IDENTITY_MISSING",
        ),
        (
            {"altered": {"namespace_uri": "https://example.com/dei"}},
            "HISTORICAL_IDENTITY_SCOPE_UNSUPPORTED",
        ),
        ({"duplicate": True}, "HISTORICAL_IDENTITY_CONFLICT"),
    ),
)
def test_missing_untrusted_or_conflicting_dei_cannot_establish_a_security(
    tmp_path, changes, reason
):
    request, store, roots = security_case(tmp_path, **changes)
    decision = evaluate(request, store)
    assert decision.status == "abstain" and reason in decision.reason_codes
    assert approve(request, store, roots).approval_publication is None


@pytest.mark.parametrize("valid", (True, False))
def test_complete_batch_propagates_security_scope_and_retains_all_roles(
    tmp_path, valid
):
    single, store, roots = security_case(tmp_path)
    if not valid:
        single = single.model_copy(
            update={
                "security_identity": single.security_identity.model_copy(
                    update={"security_id": "OTHER"}
                )
            }
        )
    batch = AutomaticMappingBatchRequestV1(
        **single.model_dump(exclude={"protocol", "proposal"}),
        mapping_version=single.proposal.mapping_version,
        model_version="fcff_dcf-v2",
        requirements=valuation_requirements_profile("fcff_dcf"),
    )
    first = approve_mapping_batch(
        batch, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    decisions = [
        AutomaticMappingDecisionV1.model_validate_json(
            store.read(receipt.decision_publication.artifact.artifact_id)
        )
        for receipt in first.mapping_receipts
    ]
    if valid:
        expense = next(
            d.mapping
            for d in decisions
            if d.mapping is not None
            and d.mapping.normalized_field == "stock_based_compensation"
        )
        assert expense.accounting_rules.security_id == "EXAMPLE"
    else:
        assert all(d.status == "abstain" and d.mapping is None for d in decisions)
    before = inventory(store.root)
    second = approve_mapping_batch(
        batch, artifacts=store, trust_roots=roots, private_key=MACHINE_KEY
    )
    assert not second.wrote and second.output_digest == first.output_digest
    assert inventory(store.root) == before


def test_omitted_security_identity_preserves_existing_canonical_request_bytes(tmp_path):
    request, _, _, _ = expense_case(tmp_path)
    payload = request.model_dump(mode="json")
    assert "security_identity" not in payload
    explicit = AutomaticMappingRequestV1.model_validate_json(
        canonical_bytes({**payload, "security_identity": None})
    )
    assert canonical_bytes(explicit) == canonical_bytes(request)
    assert sha256_digest(payload) == sha256_digest(request)
