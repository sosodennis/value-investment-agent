from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from fundamental_service.contracts import (
    FiscalPeriodSelectorV1,
    QualityStatus,
    SecHistoryIntegrityEvidenceV1,
    SecIntegrityEvidenceV1,
    SourceSnapshotV1,
)
from fundamental_service.history_composition import (
    compose_original_history,
    verify_history_components,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemSnapshotRepository, SnapshotError
from fundamental_service.valuation_preparation import prepare_automatic_valuation
from fundamental_service.uncertainty import run_uncertainty
from test_valuation_preparation import _facts, _market_policy
from test_postgres_metadata import _snapshot

VALUATION_TIME = datetime(2026, 3, 1, tzinfo=UTC)
SELECTOR = FiscalPeriodSelectorV1(mode="latest_complete", count=3)


def _original(year: int) -> SourceSnapshotV1:
    accession = f"0000000001-{(year + 1) % 100:02d}-000001"
    uri = f"https://www.sec.gov/Archives/edgar/data/1/{accession.replace('-', '')}"
    raw_hash = sha256_digest({"synthetic_original": year})
    snapshot = _snapshot(str(year), valuation_timestamp=VALUATION_TIME)
    source = snapshot.source_records[0].model_copy(
        update={
            "source_id": "sec-filing",
            "uri": f"{uri}/original.htm",
            "accession_number": accession,
            "content_hash": raw_hash,
            "parser_input_hash": raw_hash,
            "parser_version": "2.47.4",
            "form": "10-K",
            "filed_at": datetime(year + 1, 2, 1, tzinfo=UTC),
            "available_at": datetime(year + 1, 2, 1, tzinfo=UTC),
            "captured_at": VALUATION_TIME,
        }
    )
    integrity = SecIntegrityEvidenceV1(
        accession_number=accession,
        primary_document_uri=source.uri,
        captured_at=VALUATION_TIME,
        archive_index_uri=f"{uri}/index.json",
        archive_index_hash="b" * 64,
        declared_primary_size=12,
        raw_received_size=12,
        raw_content_hash=raw_hash,
        archive_uri=f"{uri}/{accession}-xbrl.zip",
        archive_size=100,
        archive_hash="c" * 64,
        archive_member_name="original.htm",
        archive_member_size=12,
        archive_member_hash=raw_hash,
        integrity_relation="exact",
        normalized_content_size=12,
        normalized_content_hash=raw_hash,
        normalized_fact_count=10,
        normalized_fact_digest="d" * 64,
        archive_fact_count=10,
        archive_fact_digest="d" * 64,
        parser_input_hash=raw_hash,
        validation_profile_digest="e" * 64,
        validation_engines=("sec-efm", "dqc-us"),
        validation_evidence=(
            "strict-sec-efm-profile-selected",
            "dqc-dqcrt-checks-completed",
        ),
        network_attempt_count=0,
        taxonomy_manifest_hash="f" * 64,
        arelle_version="2.47.4",
        efm_profile="efm-pragmatic",
        dqc_version="v31.0.3",
        xule_version="30055",
        quality_decision="pass",
    )
    return _changed(
        snapshot,
        source_records=(source,),
        captured_at=VALUATION_TIME,
        sec_integrity_evidence=integrity,
        validation_profile_id="sec-efm-us-dqc-v31.0.3",
        validation_profile_digest="e" * 64,
        parser_version="2.47.4",
        taxonomy_manifest_id="taxonomy-modern",
    )


def _changed(snapshot, **changes):
    payload = snapshot.model_dump(exclude={"manifest_digest"})
    payload.update(changes)
    payload["manifest_digest"] = sha256_digest(
        {key: value for key, value in payload.items() if key != "snapshot_id"}
    )
    return SourceSnapshotV1.model_validate(payload)


def _repository(tmp_path):
    repository = FilesystemSnapshotRepository(tmp_path / "snapshots")
    originals = tuple(_original(year) for year in (2023, 2025))
    for snapshot in originals:
        repository.publish(snapshot)
    return repository, originals


def _compose(repository, originals):
    return compose_original_history(
        repository,
        tuple(item.snapshot_id for item in originals),
        valuation_timestamp=VALUATION_TIME,
        fiscal_period_selector=SELECTOR,
    )


def test_composition_keeps_independent_originals_and_is_idempotent(tmp_path):
    repository, originals = _repository(tmp_path)
    history = _compose(repository, originals)
    assert isinstance(history.sec_integrity_evidence, SecHistoryIntegrityEvidenceV1)
    assert verify_history_components(history, repository) == originals
    assert tuple(
        component.integrity for component in history.sec_integrity_evidence.components
    ) == tuple(item.sec_integrity_evidence for item in originals)
    before = {
        path: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in (tmp_path / "snapshots").iterdir()
    }
    assert _compose(repository, originals[::-1]) == history
    assert {
        path: (path.read_bytes(), path.stat().st_mtime_ns) for path in before
    } == before
    assert len(tuple((tmp_path / "snapshots").iterdir())) == 3
    assert SourceSnapshotV1.model_validate_json(canonical_bytes(history)) == history


def test_concurrent_composition_has_one_snapshot_and_stable_digest(tmp_path):
    repository, originals = _repository(tmp_path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = tuple(pool.map(lambda _: _compose(repository, originals), range(16)))
    assert len({item.manifest_digest for item in results}) == 1
    assert len(tuple((tmp_path / "snapshots").iterdir())) == 3


@pytest.mark.parametrize(
    "change",
    [
        "issuer",
        "security",
        "future",
        "amendment",
        "integrity",
        "profile",
        "source_hash",
        "nested",
        "quality",
        "extra_filing",
        "future_source",
    ],
)
def test_invalid_component_is_retained_without_publishing_history(tmp_path, change):
    repository, originals = _repository(tmp_path)
    original = originals[1]
    if change in {"issuer", "security"}:
        field = "issuer_id" if change == "issuer" else "security_id"
        broken = _changed(
            original, identity=original.identity.model_copy(update={field: "other"})
        )
    elif change == "future":
        broken = _changed(
            original, valuation_timestamp=datetime(2027, 1, 1, tzinfo=UTC)
        )
    elif change == "amendment":
        broken = _changed(
            original,
            source_records=(
                original.source_records[0].model_copy(
                    update={"is_amendment": True, "amendment_scope": "unknown"}
                ),
            ),
        )
    elif change == "integrity":
        broken = _changed(
            original,
            sec_integrity_evidence=original.sec_integrity_evidence.model_copy(
                update={"quality_decision": "block"}
            ),
        )
    elif change == "source_hash":
        broken = _changed(
            original,
            source_records=(
                original.source_records[0].model_copy(
                    update={"content_hash": "0" * 64}
                ),
            ),
        )
    elif change == "profile":
        broken = _changed(original, policy_version="other-policy")
    elif change == "quality":
        broken = _changed(original, coverage_status=QualityStatus.PROVISIONAL)
    elif change == "extra_filing":
        broken = _changed(
            original,
            source_records=original.source_records
            + (
                original.source_records[0].model_copy(
                    update={"source_id": "unvalidated"}
                ),
            ),
        )
    elif change == "future_source":
        broken = _changed(
            original,
            source_records=(
                original.source_records[0].model_copy(
                    update={"available_at": datetime(2027, 1, 1, tzinfo=UTC)}
                ),
            ),
        )
    else:
        broken = _compose(repository, originals)
    repository = FilesystemSnapshotRepository(tmp_path / "invalid-case")
    repository.publish(originals[0])
    repository.publish(broken)
    before = tuple(path.read_bytes() for path in sorted(repository.root.iterdir()))
    with pytest.raises((SnapshotError, ValueError)):
        _compose(repository, (originals[0], broken))
    assert (
        tuple(path.read_bytes() for path in sorted(repository.root.iterdir())) == before
    )


def test_component_is_rechecked_against_the_immutable_repository(tmp_path):
    repository, originals = _repository(tmp_path)
    history = _compose(repository, originals)
    altered = _changed(originals[0], policy_version="unexpected")
    (repository.root / f"{originals[0].snapshot_id}.json").write_bytes(
        canonical_bytes(altered)
    )
    with pytest.raises(SnapshotError, match="retained original"):
        verify_history_components(history, repository)


def test_missing_original_refuses_history_without_modifying_it(tmp_path):
    repository, originals = _repository(tmp_path)
    history = _compose(repository, originals)
    history_path = repository.root / f"{history.snapshot_id}.json"
    before = history_path.read_bytes(), history_path.stat().st_mtime_ns
    (repository.root / f"{originals[0].snapshot_id}.json").unlink()
    with pytest.raises(SnapshotError) as error:
        verify_history_components(history, repository)
    assert error.value.code == "HISTORY_COMPONENT_UNAVAILABLE"
    assert (history_path.read_bytes(), history_path.stat().st_mtime_ns) == before


def test_history_adds_required_prior_periods_to_formal_composer_without_changing_facts(
    tmp_path,
):
    repository, originals = _repository(tmp_path)
    history = _compose(repository, originals)
    from equity_award_fixtures import award_evidence

    dilution = award_evidence(history)
    facts = []
    for fact in _facts():
        if fact.period_end.year < 2022:
            continue
        original = originals[0] if fact.period_end.year <= 2023 else originals[1]
        source = original.source_records[0]
        assert fact.period_end < source.available_at.date()
        # Each original alone has only two complete annual balance-sheet dates.
        facts.append(
            fact.model_copy(
                update={
                    "issuer_id": history.identity.issuer_id,
                    "security_id": history.identity.security_id,
                    "accession_number": source.accession_number,
                    "available_at": source.available_at,
                    "filed_at": source.filed_at,
                    "source": fact.source.model_copy(
                        update={
                            "content_hash": source.content_hash,
                            "source_url": source.uri,
                            "available_at": source.available_at,
                            "filed_at": source.filed_at,
                        }
                    ),
                }
            )
        )

    def prepare(snapshot):
        return prepare_automatic_valuation(
            (*facts, *dilution.facts),
            snapshot=snapshot,
            model_id="fcff_dcf",
            model_version="fcff_dcf-v1",
            policy_id="fcff_dcf-us-gaap-public-v1",
            policy_version="fcff_dcf-v1-quality-v1",
            data_release_manifest_digest="d" * 64,
            market_policy=_market_policy(),
            equity_dilution_evidence=dilution,
        )

    for original in originals:
        result = prepare(original)
        assert result.status != "prepared"
        assert result.quality_status is QualityStatus.ABSTAIN
    prepared = prepare(history)
    assert prepared.status == "prepared"
    assert prepared.quality_status is QualityStatus.PROVISIONAL
    assert "HISTORY_THRESHOLD_UNVALIDATED" in prepared.issue_codes
    assert prepared.input is not None
    report = run_uncertainty(prepared.input, allow_provisional=True)
    assert report.base.per_share_value > 0
    assert (
        run_uncertainty(prepare(history).input, allow_provisional=True).result_hash
        == report.result_hash
    )
