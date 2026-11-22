"""Completed mapping reports must not overlap independent release verification."""

from contextvars import copy_context
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
import weakref

import pytest

from fundamental_service.automatic_release_evidence import (
    require_automatic_release_sources,
)
from fundamental_service.data_releases import DataReleaseError
from fundamental_service.contracts import SecMappingReferenceV1
from fundamental_service.mapping_input_identity import MappingInputDigests
from fundamental_service.original_issuer import OriginalIssuerEvidenceChecks
from fundamental_service.preparation_release import assemble_preparation_release
from fundamental_service.preparation_runner import (
    SourcePreparationRunner,
    _PreparedPlanFacts,
)
from fundamental_service.serialization import canonical_bytes
from test_automatic_mapping import case
from test_preparation_release import assembly_case
from test_preparation_runner import _fixture, _reviewed_candidate, _runner


def retain_mapping_report(runner, tmp_path):
    request = case(tmp_path)[0]
    originals, identities = OriginalIssuerEvidenceChecks(), MappingInputDigests()
    raw = canonical_bytes(request.original.report.model_dump(mode="json"))
    report = originals.resolve_report(raw).report
    assert identities.report_bytes(report) == raw
    runner._mapping_inputs.set((originals, identities))
    return weakref.ref(report), copy_context()


@pytest.mark.parametrize("fail", (False, True))
def test_generated_release_releases_mapping_reports_and_keeps_original_checks(
    tmp_path, monkeypatch, fail
):
    options, acquisition, _ = assembly_case(tmp_path, monkeypatch)
    expected = assemble_preparation_release(**options)
    mappings = SimpleNamespace(get_mapping=acquisition.metadata.mappings.__getitem__)
    boundary_checks = []
    verify_original = acquisition.verify_original_boundary

    def original_boundary():
        verify_original()
        boundary_checks.append("original")

    monkeypatch.setattr(acquisition, "verify_original_boundary", original_boundary)
    publication = options["artifacts"].put_with_receipt(
        "synthetic-refused-release", {"refused": True}
    )

    def sign(request, *, deadline_at):
        assert boundary_checks == ["original"]
        assert captured_context.get(runner._mapping_inputs) is not None
        assert report_ref() is None
        assert canonical_bytes(request) == canonical_bytes(expected)
        assert require_automatic_release_sources(
            request.manifest,
            request.content,
            snapshots=SimpleNamespace(get=lambda _: options["snapshot"]),
            mappings=mappings,
            artifacts=options["artifacts"],
            validation_profile_digest=options["policy"].validation_profile_digest,
        )
        if fail:
            raise DataReleaseError("SYNTHETIC_VERIFIER_FAILURE", "refused")
        return SimpleNamespace(
            decision_publication=publication,
            decision=SimpleNamespace(status="refused", issue_codes=("REFUSED",)),
            candidate_publication=None,
        )

    runner = SourcePreparationRunner(
        application=SimpleNamespace(artifact_store=options["artifacts"]),
        metadata=mappings,
        acquisition=acquisition,
        artifacts=options["artifacts"],
        canary=None,
        automatic_release=SimpleNamespace(verify_and_sign=sign),
        automatic_release_policy=options["policy"],
    )
    report_ref, captured_context = retain_mapping_report(runner, tmp_path / "mapping")
    prepared = _PreparedPlanFacts(
        options["plan"].digest,
        options["snapshot"].manifest_digest,
        (
            tuple(
                SecMappingReferenceV1(
                    decision_id=mapping.decision_id,
                    mapping_version=mapping.mapping_version,
                    normalized_field=mapping.normalized_field,
                )
                for mapping in options["mappings"]
            ),
        ),
        options["facts"],
    )

    def run():
        return runner._automatic_candidate(
            options["plan"],
            options["snapshot"],
            (SimpleNamespace(mapping_evidence_ref=options["batch_refs"][0]),),
            (),
            prepared_facts=prepared,
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )

    if fail:
        with pytest.raises(DataReleaseError) as caught:
            run()
        assert caught.value.code == "SYNTHETIC_VERIFIER_FAILURE"
    else:
        candidate, reference, issues = run()
        assert candidate is None and issues == ("REFUSED",)
        assert reference.content_hash == publication.artifact.content_hash
    assert report_ref() is None
    prepared.require_scope(options["plan"], options["snapshot"])


@pytest.mark.parametrize("fail", (False, True))
def test_supplied_candidate_releases_mapping_reports_before_canary(
    tmp_path, monkeypatch, fail
):
    fixture = _fixture(tmp_path, released=False)
    candidate, canary = _reviewed_candidate(fixture)
    runner = _runner(fixture, canary=canary)
    report_ref, captured_context = retain_mapping_report(runner, tmp_path / "mapping")
    validate = canary.validate

    def independent(manifest, verification):
        assert captured_context.get(runner._mapping_inputs) is not None
        assert report_ref() is None
        if fail:
            raise DataReleaseError("SYNTHETIC_CANARY_FAILURE", "refused")
        return validate(manifest, verification)

    monkeypatch.setattr(canary, "validate", independent)

    def activate():
        runner._activate(
            candidate,
            actor_id="operator",
            organization_id="operators",
            correlation_id="lifetime-test",
            plan=fixture.plan,
            deadline_at=datetime.now(UTC) + timedelta(seconds=30),
        )

    if fail:
        with pytest.raises(DataReleaseError) as caught:
            activate()
        assert caught.value.code == "SYNTHETIC_CANARY_FAILURE"
        assert fixture.state.publications == 0 and fixture.state.active is None
    else:
        activate()
        assert fixture.state.publications == 1
        assert fixture.state.active.manifest == candidate.manifest
    assert report_ref() is None
