"""Issuer accounting uses the security path's evaluator without security authority."""

from decimal import Decimal
import json
from pathlib import Path

import pytest

from fundamental_service.accounting_roles import IssuerAccountingRoleRuleSetV1
from fundamental_service.arelle_parser import (
    ArelleValidationProfileV1,
    fact_semantic_digest,
)
from fundamental_service.contracts import CanonicalFactV1, QualityStatus
from fundamental_service.facts import (
    CanonicalMappingV1,
    verify_accounting_role_evidence,
)
from fundamental_service.original_issuer import (
    compose_issuer_operating_source,
    evaluate_original_issuer,
)
from fundamental_service.sec_rebuild import parsed_facts_to_candidates
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_accounting_roles import _fixture
from test_original_issuer import DECISION, original


def issuer_rule(disposition="derived", *, source_changes=None):
    security_snapshot, accounting_report, mapping = _fixture(disposition=disposition)
    report, source = original()
    observations = tuple(
        f.model_copy(
            update={
                "entity_identifier": source.cik,
                "security_scope": "unspecified",
                **(source_changes or {}),
            }
        )
        for f in accounting_report.facts
    )
    # Rebind source-reference digests after changing the explicitly synthetic scope.
    digests = {
        sha256_digest(old): sha256_digest(new)
        for old, new in zip(accounting_report.facts, observations, strict=True)
    }
    rule_payload = mapping.accounting_rules.model_dump(mode="json")
    raw = json.dumps(rule_payload)
    for old, new in digests.items():
        raw = raw.replace(old, new)
    rule_payload = json.loads(raw)
    profile = ArelleValidationProfileV1(
        profile_id="synthetic-issuer-accounting",
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path("edgar"),
        xule_plugin_dir=Path("xule"),
        dqc_ruleset_path=Path("ruleset"),
        edgar_plugin_sha256="a" * 64,
        xule_plugin_sha256="b" * 64,
        dqc_ruleset_sha256="c" * 64,
    )
    report = report.model_copy(
        update={
            "facts": (*report.facts, *observations),
            "validation_profile": profile,
            "validation_profile_digest": profile.digest(),
            "validation_engines": accounting_report.validation_engines,
        }
    )
    claim = evaluate_original_issuer(report, source=source, decision_at=DECISION)
    view = compose_issuer_operating_source((claim,), valuation_timestamp=DECISION)
    rule_payload.update(
        {
            "protocol": "sec-accounting-role-issuer-v1",
            "security_id": None,
            "issuer_id": source.cik,
            "accession_number": source.accession_number,
            "raw_content_hash": source.content_hash,
            "parser_input_hash": source.parser_input_hash,
            "parser_fact_digest": fact_semantic_digest(report),
        }
    )
    mapping = mapping.model_copy(
        update={
            "accounting_rules": IssuerAccountingRoleRuleSetV1.model_validate(
                rule_payload
            ),
        }
    )
    return view, mapping, security_snapshot


def candidates(view, mapping):
    return parsed_facts_to_candidates(
        view.originals[0].report,
        source=view.originals[0].source,
        issuer_id=view.identity.issuer_id,
        normalized_field=mapping.normalized_field,
        mapping=mapping,
    )


@pytest.mark.parametrize(
    "disposition,value",
    (
        ("derived", "120"),
        ("confirmed_absent", "0"),
        ("disclosed", "2000000"),
    ),
)
def test_issuer_accounting_reuses_evaluator_and_retains_sources(disposition, value):
    view, mapping, security = issuer_rule(disposition)
    mapping = CanonicalMappingV1.model_validate_json(canonical_bytes(mapping))
    (candidate,) = candidates(view, mapping)
    fact = candidate.canonical_fact(quality=QualityStatus.PROVISIONAL)
    restored = CanonicalFactV1.model_validate_json(canonical_bytes(fact))
    assert restored == fact and fact.value == Decimal(value)
    assert fact.security_id is None and fact.security_scope == "issuer"
    assert fact.accounting_evidence.source_facts
    verify_accounting_role_evidence(fact, mapping, view)
    with pytest.raises(SnapshotError) as error:
        verify_accounting_role_evidence(fact, mapping, security)
    assert error.value.code == "ACCOUNTING_ROLE_SCOPE_MISMATCH"
    assert candidates(view, mapping) == (candidate,)


@pytest.mark.parametrize("disposition", ("unknown", "unsupported"))
def test_unresolved_issuer_roles_preserve_disposition_without_numeric_placeholder(
    disposition,
):
    view, mapping, _ = issuer_rule(disposition)
    assert candidates(view, mapping) == ()
    assert mapping.accounting_rules.periods[0].disposition == disposition


@pytest.mark.parametrize(
    "changes",
    (
        {"security_scope": "security"},
        {"dimensions": (("us-gaap:StatementBusinessSegmentsAxis", "example:Other"),)},
    ),
)
def test_issuer_role_rejects_security_or_segment_components(changes):
    view, mapping, _ = issuer_rule(source_changes=changes)
    with pytest.raises(SnapshotError) as error:
        candidates(view, mapping)
    assert error.value.code == "ACCOUNTING_ROLE_SCOPE_MISMATCH"


@pytest.mark.parametrize(
    "field,value",
    (
        ("issuer_id", "0000000002"),
        ("accession_number", "0000000001-24-000002"),
        ("raw_content_hash", "c" * 64),
        ("parser_input_hash", "d" * 64),
        ("parser_fact_digest", "e" * 64),
    ),
)
def test_issuer_rules_cannot_swap_original_binding(field, value):
    view, mapping, _ = issuer_rule()
    mapping = mapping.model_copy(
        update={
            "accounting_rules": mapping.accounting_rules.model_copy(
                update={field: value}
            ),
        }
    )
    with pytest.raises(SnapshotError) as error:
        candidates(view, mapping)
    assert error.value.code == "ACCOUNTING_ROLE_SOURCE_MISMATCH"
