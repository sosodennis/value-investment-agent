"""Source mapping shares only its operation's independently checked image proof."""

import pytest

from fundamental_service.automatic_mapping_evidence import (
    AutomaticMappingEvidenceChecks,
)
from fundamental_service.parser_action_identity import (
    IncompleteParserClosure,
    ParserBuildChecks,
)
from test_automatic_source_mapping import source_case
from test_issuer_operating_release import inventory


def build_probe(monkeypatch):
    import fundamental_service.automatic_source_mapping as source
    import fundamental_service.parser_action_identity as identity

    configuration = ["fixed image"]
    proofs = []
    boundaries = []

    def boundary():
        boundaries.append(True)
        return configuration[0], ()

    monkeypatch.setattr(identity, "_immutable_build_configuration", boundary)
    monkeypatch.setattr(
        identity, "_runtime_identity", lambda **kwargs: proofs.append(True) or "2" * 64
    )
    require = source.require_parser_action_evidence
    check = AutomaticMappingEvidenceChecks.require_parser_actions

    def require_actions(original, **kwargs):
        builds = kwargs.get("build_checks") or ParserBuildChecks()
        builds.current()
        return require(original, **kwargs)

    def check_actions(self, request, **kwargs):
        self.builds.current()
        return check(self, request, **kwargs)

    monkeypatch.setattr(source, "require_parser_action_evidence", require_actions)
    monkeypatch.setattr(
        AutomaticMappingEvidenceChecks, "require_parser_actions", check_actions
    )
    return configuration, proofs, boundaries


def test_source_batch_and_next_operation_independently_check_shared_image_value(
    tmp_path, monkeypatch
):
    request, authority, validated, artifacts, _ = source_case(tmp_path)
    _, proofs, boundaries = build_probe(monkeypatch)
    builds = ParserBuildChecks()
    builds.current()
    expected = authority.resolver_for(request, build_checks=builds).resolve(validated)
    assert expected.mappings and len(proofs) == 1
    before = inventory(artifacts.root)
    previous_checks = len(boundaries)
    assert authority.resolver_for(request).resolve(validated) == expected
    assert len(proofs) == 1
    assert len(boundaries) > previous_checks
    assert inventory(artifacts.root) == before


def test_changed_image_after_batch_read_refuses_domain_mapping_publication(
    tmp_path, monkeypatch
):
    request, authority, validated, artifacts, mappings = source_case(tmp_path)
    configuration, _, _ = build_probe(monkeypatch)
    read = artifacts.read

    def replace_image(identity):
        raw = read(identity)
        if identity.startswith("automatic-mapping-batch-decision-"):
            configuration[0] = "replaced image"
        return raw

    monkeypatch.setattr(artifacts, "read", replace_image)
    with pytest.raises(IncompleteParserClosure, match="configuration changed"):
        authority.resolver_for(request).resolve(validated)
    assert not mappings


def test_acquisition_mapping_and_parser_use_the_same_operation_build(
    tmp_path, monkeypatch
):
    from test_automatic_source_acquisition import acquisition_case, acquire
    import fundamental_service.automatic_source_mapping as source

    request, acquisition, _, metadata, _ = acquisition_case(tmp_path, monkeypatch)
    build_probe(monkeypatch)
    require = source.require_parser_action_evidence
    prepare = acquisition.ingestion.prepare_filing
    seen = []

    def require_actions(original, **kwargs):
        seen.append(kwargs.get("build_checks"))
        return require(original, **kwargs)

    def prepare_filing(**kwargs):
        seen.append(kwargs["build_checks"])
        return prepare(**kwargs)

    monkeypatch.setattr(source, "require_parser_action_evidence", require_actions)
    monkeypatch.setattr(acquisition.ingestion, "prepare_filing", prepare_filing)
    with acquisition.evidence_operation():
        builds = acquisition._original_reads.get().builds
        result = acquire(request, acquisition)
        assert len(seen) == 2 and all(value is builds for value in seen)
    assert result.snapshot_id in metadata.snapshots
    assert acquisition._original_reads.get() is None
