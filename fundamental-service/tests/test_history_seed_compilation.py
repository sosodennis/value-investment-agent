"""Older originals cannot alter the existing forecast basis or grant authority."""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from fundamental_service.facts import MappingObservationScopeV1
from fundamental_service.operating_scenarios import replay_operating_scenarios
from fundamental_service.original_issuer import evaluate_original_issuer
from fundamental_service.serialization import canonical_bytes, sha256_digest
from test_history_study_windows import extend_history
from test_operating_labels import comparison_request

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import compile_history_study_seed as compiler  # noqa: E402
import replay_history_study_windows as windows  # noqa: E402


def extension_inputs():
    seed = comparison_request()
    longer = extend_history(seed, 2022)
    previous = longer.decision.source.originals[0]
    accession = "0000000001-26-000002"
    source = previous.source.model_copy(
        update={
            "accession_number": accession,
            "uri": "https://www.sec.gov/Archives/edgar/data/1/000000000126000002/older.xml",
            "content_hash": "c" * 64,
            "parser_input_hash": "d" * 64,
        }
    )
    report = previous.report.model_copy(update={"source_content_hash": "d" * 64})
    original = evaluate_original_issuer(
        report, source=source, decision_at=previous.decision_at
    )
    mappings = []
    for mapping in seed.decision.mappings:
        observed = tuple(
            fact
            for fact in original.report.facts
            if fact.concept == mapping.source_concept
            and (
                fact.period_start == date(2022, 1, 1)
                or fact.instant == date(2022, 12, 31)
            )
        )
        assert len(observed) == 1
        scope = MappingObservationScopeV1(
            issuer_id=source.cik,
            accession_number=accession,
            raw_content_hash=source.content_hash,
            parser_input_hash=source.parser_input_hash,
            parser_replay_digest=original.report.replay_digest(),
            observation_digests=(sha256_digest(observed[0]),),
        )
        mappings.append(
            mapping.model_copy(
                update={
                    "decision_id": mapping.decision_id + "-older",
                    "observation_scope": scope,
                }
            )
        )
    extension = compiler.SeedExtension(
        schema_version="history-study-seed-extension.v1",
        original=original,
        mappings=tuple(mappings),
        fiscal_year=2022,
        period_start=date(2022, 1, 1),
        period_end=date(2022, 12, 31),
        mapping_version="extended-test-v2",
        scenarios=tuple(
            compiler.ExtendedScenario(
                scenario_id=prior.scenario_id + suffix,
                parent_scenario_id=prior.scenario_id,
                older_continuing_capex_fraction=fraction,
            )
            for prior in seed.decision.scenarios
            for suffix, fraction in (
                ("-low", Decimal("0.25")),
                ("-high", Decimal("0.75")),
            )
        ),
        scope_assumptions=(
            "Two explicitly conditional older capex allocations; neither is an observed classification.",
        ),
    )
    return seed, extension


def test_old_forecasts_labels_and_original_values_survive_new_mapping_identity():
    seed, extension = extension_inputs()
    before = canonical_bytes(seed)
    result = compiler.compile_seed(seed, extension)
    repeated = compiler.compile_seed(seed, extension)
    assert canonical_bytes(result) == canonical_bytes(repeated)
    assert canonical_bytes(seed) == before
    assert result.label == seed.label
    assert result.filing_inventory == seed.filing_inventory
    assert result.inventory_evidence_digest == seed.inventory_evidence_digest
    assert result.decision.model_versions == seed.decision.model_versions
    assert result.decision.policy_digest == seed.decision.policy_digest
    assert [p.fiscal_year for p in result.decision.periods] == [2022, 2023, 2024, 2025]
    assert result.decision.mapping_version != seed.decision.mapping_version
    assert all(f.quality.value == "provisional" for f in result.decision.facts)
    assert all(m.status == "provisional" for m in result.decision.mappings)
    assert set(seed.decision.scope_assumption_evidence_digests) <= set(
        result.decision.scope_assumption_evidence_digests
    )
    baseline = replay_operating_scenarios(seed.decision)
    shorter = replay_operating_scenarios(windows.trailing_request(result, 3).decision)
    parents = {
        item.scenario_id: item.parent_scenario_id for item in extension.scenarios
    }
    expected = {(item.scenario_id, item.model_id): item for item in baseline.results}
    for actual in shorter.results:
        prior = expected[parents[actual.scenario_id], actual.model_id]
        assert actual.status == prior.status
        assert [(n.node_id, n.value) for n in actual.nodes] == [
            (n.node_id, n.value) for n in prior.nodes
        ]
        assert actual.supported_history_threshold is None
        assert actual.issue_codes == prior.issue_codes


@pytest.mark.parametrize(
    "fault",
    ["gap", "version", "omitted_scenario", "collision", "future", "observation"],
)
def test_invalid_extensions_refuse_before_publication(fault):
    seed, extension = extension_inputs()
    if fault == "gap":
        extension = extension.model_copy(update={"fiscal_year": 2021})
    elif fault == "version":
        extension = extension.model_copy(
            update={"mapping_version": seed.decision.mapping_version}
        )
    elif fault == "omitted_scenario":
        extension = extension.model_copy(update={"scenarios": ()})
    elif fault == "collision":
        extension = extension.model_copy(
            update={"original": seed.decision.source.originals[0]}
        )
    elif fault == "future":
        original = extension.original
        future = original.source.available_at.replace(year=2030)
        changed = evaluate_original_issuer(
            original.report,
            source=original.source.model_copy(
                update={"available_at": future, "captured_at": future}
            ),
            decision_at=future,
        )
        extension = extension.model_copy(update={"original": changed})
    else:
        first = extension.mappings[0]
        scope = first.observation_scope.model_copy(
            update={"observation_digests": ("0" * 64,)}
        )
        extension = extension.model_copy(
            update={
                "mappings": (
                    first.model_copy(update={"observation_scope": scope}),
                    *extension.mappings[1:],
                )
            }
        )
    with pytest.raises(ValueError):
        compiler.compile_seed(seed, extension)


def test_unapproved_extension_cannot_claim_approved_mapping():
    _, extension = extension_inputs()
    payload = extension.model_dump(mode="json")
    payload["mappings"][0]["status"] = "approved"
    payload["mappings"][0]["confidence"] = "high"
    with pytest.raises(ValueError, match="cannot grant mapping approval"):
        compiler.SeedExtension.model_validate_json(canonical_bytes(payload))
