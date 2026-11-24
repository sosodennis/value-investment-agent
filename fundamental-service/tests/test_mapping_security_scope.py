from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from fundamental_service.arelle_parser import ParsedXbrlFactV1
from fundamental_service.facts import CanonicalMappingV1, MappingObservationScopeV1
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_sec_rebuild import _rebuild_report, _rebuild_source
from test_automatic_mapping import evaluate
from test_automatic_mapping_security import security_case, security_source


def scope_case(**changes):
    source = _rebuild_source("a" * 64)
    fact = ParsedXbrlFactV1(
        concept="us-gaap:Revenues",
        value="100",
        context_id="issuer-annual",
        unit="iso4217:USD",
        entity_scheme="http://www.sec.gov/CIK",
        entity_identifier="0000320193",
        period_start=date(2024, 1, 1),
        period_end=date(2024, 9, 28),
        is_numeric=True,
        consolidation_scope="consolidated",
        security_scope="unspecified",
    ).model_copy(update=changes)
    report = _rebuild_report(source.content_hash, facts=(fact,))
    mapping = CanonicalMappingV1(
        contract_version="fundamental.v1",
        decision_id="synthetic-source-bound-revenue",
        source_concept=fact.concept,
        normalized_field="revenue",
        mapping_version="synthetic-scope-v1",
        confidence="high",
        status="approved",
        security_scope="issuer",
        observation_scope=MappingObservationScopeV1(
            issuer_id="0000320193",
            accession_number=source.accession_number,
            raw_content_hash=source.content_hash,
            parser_input_hash=source.content_hash,
            parser_replay_digest=report.replay_digest(),
            observation_digests=(sha256_digest(fact),),
        ),
    )
    return source, report, mapping


def rebuild(source, report, mapping):
    return parsed_facts_to_candidates(
        report,
        source=source,
        issuer_id="0000320193",
        security_id="AAPL",
        normalized_field="revenue",
        mapping=mapping,
    )


def test_explicit_mapping_establishes_issuer_amount_without_changing_observation():
    source, report, mapping = scope_case()
    before = canonical_bytes(report)
    candidates = rebuild(source, report, mapping)
    assert len(candidates) == 1
    assert candidates[0].value == Decimal("100")
    assert candidates[0].security_scope == "issuer"
    assert candidates[0].security_id == "AAPL"
    assert canonical_bytes(report) == before
    assert report.facts[0].security_scope == "unspecified"


def test_computed_issuer_target_retains_source_bound_amount_and_class_identity(
    tmp_path,
):
    request, store, _ = security_case(tmp_path)
    decision = evaluate(request, store)
    assert decision.status == "approved"
    mapping = CanonicalMappingV1.model_validate(
        decision.mapping.model_dump() | {"security_scope": "issuer"}
    )
    candidates = parsed_facts_to_candidates(
        request.original.report,
        source=security_source(request),
        issuer_id=request.original.source.cik,
        security_id="EXAMPLE",
        normalized_field="stock_based_compensation",
        mapping=mapping,
    )
    assert len(candidates) == 1
    assert candidates[0].value == Decimal("141936")
    assert candidates[0].security_scope == "issuer"
    assert candidates[0].security_id == "EXAMPLE"
    assert candidates[0].accounting_evidence.rule_set == mapping.accounting_rules


@pytest.mark.parametrize("scoped", (False, True))
def test_mapping_without_explicit_target_preserves_original_scope(scoped):
    source, report, mapping = scope_case()
    mapping = mapping.model_copy(
        update={
            "security_scope": None,
            "observation_scope": mapping.observation_scope if scoped else None,
        }
    )
    assert rebuild(source, report, mapping)[0].security_scope == "unspecified"
    assert b'"security_scope"' not in canonical_bytes(mapping)


@pytest.mark.parametrize(
    "changes",
    (
        {"unit": "xbrli:shares"},
        {"unit": "iso4217:USD/xbrli:shares"},
        {"security_scope": "class-a"},
        {"consolidation_scope": "segmented"},
        {"dimensions": (("us-gaap:StatementClassOfStockAxis", "example:ClassA"),)},
    ),
)
def test_issuer_target_cannot_promote_class_or_nonmonetary_observation(changes):
    source, report, mapping = scope_case(**changes)
    with pytest.raises(SnapshotError) as error:
        rebuild(source, report, mapping)
    assert error.value.code == "MAPPING_SECURITY_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "changes",
    (
        {"status": "provisional"},
        {"confidence": "medium"},
        {"observation_scope": None},
    ),
)
def test_issuer_target_requires_source_bound_high_confidence_approval(changes):
    _, _, mapping = scope_case()
    with pytest.raises(ValidationError, match="issuer scope requires"):
        CanonicalMappingV1.model_validate(mapping.model_dump() | changes)


def test_issuer_target_does_not_bypass_original_report_or_issuer_binding():
    source, report, mapping = scope_case()
    wrong = mapping.observation_scope.model_copy(update={"issuer_id": "0000000001"})
    assert (
        rebuild(source, report, mapping.model_copy(update={"observation_scope": wrong}))
        == ()
    )
    changed = report.model_copy(
        update={"facts": (report.facts[0].model_copy(update={"value": "999"}),)}
    )
    with pytest.raises(SnapshotError) as error:
        rebuild(source, changed, mapping)
    assert error.value.code == "MAPPING_REPORT_MISMATCH"
