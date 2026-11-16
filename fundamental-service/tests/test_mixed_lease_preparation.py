"""Synthetic integration fixture for retained mixed-period preparation."""

from types import SimpleNamespace
from decimal import Decimal

import fundamental_service.ingestion as ingestion
from fundamental_service.data_releases import MappingRefV1
from fundamental_service.facts import canonical_fact_digest
from fundamental_service.serialization import sha256_digest
from test_api import _release_manifest_for
from test_automatic_source_preparation import runner_case, run


def test_mixed_lease_mappings_reach_preparation_facts_and_release(
    tmp_path, monkeypatch
):
    plan, runner, _, metadata, _ = runner_case(tmp_path, monkeypatch)
    parser = ingestion.parse_filing_offline
    saved = {}

    def mixed_parser(*args, **kwargs):
        report = parser(*args, **kwargs)
        base = next(
            f
            for f in report.facts
            if f.is_numeric and f.instant is not None and f.unit == "iso4217:USD"
        )
        historical = base.instant.replace(year=base.instant.year - 1)
        total = base.model_copy(
            update={
                "concept": "us-gaap:OperatingLeaseLiability",
                "value": "100",
                "instant": historical,
                "decimals": "0",
            }
        )
        current = total.model_copy(
            update={
                "context_id": "current-location",
                "value": "20",
                "dimensions": (
                    (
                        "us-gaap:BalanceSheetLocationAxis",
                        "us-gaap:OtherCurrentLiabilitiesMember",
                    ),
                ),
                "consolidation_scope": "segmented",
                "security_scope": "segmented",
            }
        )
        direct = base.model_copy(
            update={
                "concept": "us-gaap:OperatingLeaseLiabilityCurrent",
                "value": "33",
                "decimals": "0",
            }
        )
        report = report.model_copy(
            update={"facts": (*report.facts, total, current, direct)}
        )
        saved.update(historical=historical, current=base.instant)
        return report

    monkeypatch.setattr(ingestion, "parse_filing_offline", mixed_parser)
    run(runner, plan)
    acquired = next(iter(metadata.acquisitions.values()))
    snapshot = metadata.snapshots[acquired.snapshot_id]
    groups = runner._plan_mappings(plan)
    selected = {
        m.decision_id: m
        for m in metadata.mappings.values()
        if m.normalized_field == "current_operating_lease_liabilities"
    }
    assert len(selected) == 2
    assert selected.keys() <= {ref.decision_id for ref in groups[0]}
    facts = [
        fact for fact in metadata.facts.values() if fact.mapping_decision_id in selected
    ]
    stored = dict(metadata.facts)
    runner._application.fact_repository = SimpleNamespace(
        list=lambda: tuple(stored.values()), get=stored.__getitem__
    )
    metadata.get_mapping = metadata.mappings.__getitem__
    selected_facts = runner._plan_facts(plan, snapshot)
    assert {
        (f.period_end, f.value)
        for f in selected_facts
        if f.normalized_field == "current_operating_lease_liabilities"
    } == {
        (saved["historical"], Decimal("20")),
        (saved["current"], Decimal("33")),
    }
    manifest = _release_manifest_for(snapshot, facts)
    payload = manifest.model_dump(exclude={"manifest_digest"})
    payload["mapping_refs"] = tuple(
        MappingRefV1(mapping_id=m.decision_id, mapping_digest=sha256_digest(m))
        for m in sorted(metadata.mappings.values(), key=lambda m: m.decision_id)
    )
    manifest = type(manifest)(**payload, manifest_digest=sha256_digest(payload))
    assert runner._matches_release(plan, snapshot, manifest)
    foreign = facts[-1].model_copy(
        update={
            "fact_id": "foreign-mapping-fact",
            "mapping_decision_id": "unapproved-mapping",
        }
    )
    stored[foreign.fact_id] = foreign
    assert foreign not in runner._plan_facts(plan, snapshot)
    payload = manifest.model_dump(exclude={"manifest_digest"})
    refs = manifest.snapshot_refs[0].facts
    ref = type(refs[0])(
        fact_id=foreign.fact_id, fact_digest=canonical_fact_digest(foreign)
    )
    payload["snapshot_refs"] = (
        manifest.snapshot_refs[0].model_copy(
            update={
                "facts": (*refs, ref),
                "fact_set_digest": sha256_digest((*refs, ref)),
            }
        ),
    )
    foreign_manifest = type(manifest)(**payload, manifest_digest=sha256_digest(payload))
    assert not runner._matches_release(plan, snapshot, foreign_manifest)
