from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest

import fundamental_service.parser_action_identity as action_identity
import fundamental_service.parser_actions as parser_module
import fundamental_service.source_acquisition as acquisition_module
from fundamental_service.arelle_parser import ArelleFindingV1, _directory_hash
from fundamental_service.dqc_rulesets import DqcRulesetBindingV1, DqcRulesetCatalogV1
from fundamental_service.fiscal_parser_evidence import read_fiscal_parser_actions
from fundamental_service.fiscal_validation_contracts import FISCAL_TAXONOMY_CACHE_SHA256
from fundamental_service.ingestion import SecIngestionService
from fundamental_service.parser_action_contracts import ParserBuildIdentityV1
from fundamental_service.parser_actions import ParserActions
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import _SecResponse
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import FilesystemSnapshotRepository, SnapshotError
from fundamental_service.source_acquisition import (
    SecAcquisitionSettings,
    SecAcquisitionUseCase,
)

from test_fiscal_discovery import DiscoveryHarness
from test_fiscal_source_closure import _selection
from test_fiscal_source_contracts import _case
from test_parser_actions import Index

NAMESPACE = "http://fasb.org/us-gaap/2024"


def test_fiscal_parser_evidence_requires_a_complete_action_set(tmp_path: Path) -> None:
    with pytest.raises(SnapshotError, match="complete parser actions"):
        read_fiscal_parser_actions(
            (),
            relation="exact",
            artifacts=ArtifactStore(tmp_path),
            build_checks=action_identity.ParserBuildChecks(),
            delivery_revision="a" * 40,
        )


@pytest.mark.parametrize("blocked", [False, True])
def test_configured_fiscal_validation_and_retained_replay(
    tmp_path, monkeypatch, blocked
):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    request = _selection(discovery, published)
    filing = discovery.selection.selected[0]
    archive_name = f"{filing.accession_number}-xbrl.zip"
    folder = (
        f"https://www.sec.gov/Archives/edgar/data/{int(filing.cik)}/"
        f"{filing.accession_number.replace('-', '')}"
    )
    primary = f"""<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:link="http://www.xbrl.org/2003/linkbase"
      xmlns:xlink="http://www.w3.org/1999/xlink"
      xmlns:us-gaap="{NAMESPACE}"><body><ix:header><ix:references>
      <link:schemaRef xlink:href="quarter.xsd"/>
      </ix:references></ix:header></body></html>
""".encode()
    schema = (
        f'<schema xmlns="http://www.w3.org/2001/XMLSchema">'
        f'<import namespace="{NAMESPACE}"/></schema>'
    ).encode()
    archive = BytesIO()
    with ZipFile(archive, "w") as package:
        package.writestr(filing.primary_document, primary)
        package.writestr("quarter.xsd", schema)
    archive_data = archive.getvalue()
    raw_primary = (
        primary.replace(
            b"</body>",
            b'<script type="text/javascript" src="/synthetic-edge"></script></body>',
        )
        if blocked
        else primary
    )
    index = canonical_bytes(
        {
            "directory": {
                "item": [
                    {"name": name, "size": str(len(content))}
                    for name, content in (
                        (filing.primary_document, primary),
                        ("quarter.xsd", schema),
                        (archive_name, archive_data),
                    )
                ]
            }
        }
    )
    submission = (
        (
            f"<SEC-DOCUMENT>{filing.accession_number}.txt\n<DOCUMENT>\n"
            f"<TYPE>{filing.form}\n<FILENAME>{filing.primary_document}\n<TEXT>\n"
        ).encode()
        + primary
        + b"</TEXT>\n</DOCUMENT>\n</SEC-DOCUMENT>\n"
    )
    portions = {
        "index.json": (index, "application/json"),
        f"{filing.accession_number}.txt": (submission, "text/plain"),
        filing.primary_document: (raw_primary, "text/html"),
        archive_name: (archive_data, "application/zip"),
    }
    fetch_catalog = harness.provider._request
    fetches = []

    def fetch(uri, *, deadline_at):
        if not uri.startswith(folder):
            return fetch_catalog(uri, deadline_at=deadline_at)
        assert deadline_at == harness.deadline
        fetches.append(uri)
        payload, media = portions[uri.rsplit("/", 1)[1]]
        return _SecResponse(
            content=payload,
            http_status=200,
            media_type=media,
            available_at=harness.now + timedelta(microseconds=len(fetches)),
            response_headers=(
                (("x-akamai-transformed", "0 - 0 -"),)
                if blocked and uri.endswith(filing.primary_document)
                else ()
            ),
            declared_size=len(payload),
        )

    monkeypatch.setattr(harness.provider, "_request", fetch)
    edgar, xule, taxonomy = (tmp_path / name for name in ("EDGAR", "xule", "taxonomy"))
    for resource in (edgar, xule, taxonomy):
        resource.mkdir()
        (resource / "fixture").write_bytes(resource.name.encode())
    ruleset = tmp_path / "v31.zip"
    ruleset.write_bytes(b"synthetic compiled rules")
    rules_hash = sha256(ruleset.read_bytes()).hexdigest()
    binding = DqcRulesetBindingV1(
        taxonomy_namespace=NAMESPACE, path=ruleset, sha256=rules_hash
    )
    catalog = DqcRulesetCatalogV1(bindings=(binding,))
    monkeypatch.setattr(
        acquisition_module,
        "_directory_hash",
        lambda path: FISCAL_TAXONOMY_CACHE_SHA256
        if path == taxonomy
        else _directory_hash(path),
    )
    resource_digests = action_identity._resource_digests

    def fixture_digests(path):
        content, closure = resource_digests(path)
        return (FISCAL_TAXONOMY_CACHE_SHA256 if path == taxonomy else content), closure

    monkeypatch.setattr(action_identity, "_resource_digests", fixture_digests)
    build = ParserBuildIdentityV1(
        implementation_digest="1" * 64,
        runtime_digest="2" * 64,
        output_schema_digest="3" * 64,
    )
    monkeypatch.setattr(
        action_identity.ParserBuildChecks, "current", lambda self: build
    )
    parsed = []

    def parse(
        path,
        *,
        profile,
        taxonomy_version,
        taxonomy_cache_dir,
        source_content_hash,
        deadline_at,
    ):
        assert deadline_at == harness.deadline
        assert taxonomy_cache_dir == taxonomy
        parsed.append(path.name)
        report, _, _ = _case(form=filing.form, period_end=filing.report_period_end)
        return report.model_copy(
            update={
                "filing_path": str(path),
                "taxonomy_version": taxonomy_version,
                "taxonomy_cache_hash": FISCAL_TAXONOMY_CACHE_SHA256,
                "source_content_hash": source_content_hash,
                "validation_profile": profile,
                "validation_profile_digest": profile.digest(),
                "dqc_filing_context": None,
                "validation_evidence": (
                    *report.validation_evidence[:2],
                    f"dqc-full-taxonomy-ruleset-v1:{NAMESPACE}:{rules_hash}",
                ),
                "parsed_at": datetime.now(UTC),
                "findings": (
                    ArelleFindingV1(
                        code="DQC.US.0015.5970",
                        severity="error",
                        message="Synthetic raw block",
                    ),
                )
                if blocked
                else (),
                "facts": tuple(
                    fact.model_copy(
                        update={
                            "period_start": date(filing.report_period_end.year, 1, 1)
                        }
                    )
                    for fact in report.facts
                ),
            }
        )

    monkeypatch.setattr(parser_module, "parse_filing_offline", parse)
    locks = Index()
    settings = SecAcquisitionSettings(
        taxonomy_cache_dir=taxonomy,
        taxonomy_manifest_id="synthetic-fiscal-resources",
        taxonomy_version="us-gaap-2024",
        taxonomy_cache_sha256=FISCAL_TAXONOMY_CACHE_SHA256,
        edgar_plugin_dir=edgar,
        xule_plugin_dir=xule,
        dqc_ruleset_path=ruleset,
        edgar_plugin_sha256=_directory_hash(edgar),
        xule_plugin_sha256=_directory_hash(xule),
        dqc_ruleset_sha256=rules_hash,
        supported_filing_years=harness.request.supported_filing_years,
        supported_filing_forms=("10-K", "10-Q"),
        dqc_ruleset_catalog=catalog,
    )
    acquisition = SecAcquisitionUseCase(
        adapter=harness.provider,
        ingestion=SecIngestionService(
            source_adapter=harness.provider,
            content_store=harness.content,
            snapshot_repository=FilesystemSnapshotRepository(tmp_path / "snapshots"),
            audit_store=harness.artifacts,
            parser_actions=ParserActions(index=locks, artifacts=harness.artifacts),
        ),
        metadata=locks,
        content_store=harness.content,
        settings=settings,
        authorized_organizations=frozenset(),
        capture_store=harness.artifacts,
    )
    closure = acquisition.fiscal_source_closure(
        declared_source_revision=harness.request.declared_source_revision
    )
    evidence, receipt = closure.execute(request, deadline_at=harness.deadline)
    assert receipt.wrote
    assert evidence.outcome.kind == (
        "complete_refused" if blocked else "complete_matched"
    ), evidence.outcome
    assert evidence.outcome.claim.metadata_status == "matched"
    assert evidence.outcome.claim.filing.form == "10-Q"
    assert evidence.outcome.claim.report.blocking_finding_codes() == (
        ("DQC.US.0015.5970",) if blocked else ()
    )
    if blocked:
        assert evidence.outcome.rejection_ref is not None
        assert evidence.outcome.rejection_ref.content_hash in evidence.dependencies
    assert evidence.outcome.integrity.integrity_relation == (
        "normalized" if blocked else "exact"
    )
    assert len(parsed) == (2 if blocked else 1)
    assert len(fetches) == 4
    before = harness.inventory()
    assert closure.read(evidence.artifact_id, deadline_at=harness.deadline) == evidence
    repeated, publication = closure.execute(request, deadline_at=harness.deadline)
    assert (repeated, publication.wrote) == (evidence, False)
    assert len(parsed) == (2 if blocked else 1)
    assert len(fetches) == 4
    assert harness.inventory() == before
    original_build = build
    build = build.model_copy(update={"runtime_digest": "4" * 64})
    with pytest.raises(SnapshotError, match="retained fiscal runtime differs"):
        closure.read(evidence.artifact_id, deadline_at=harness.deadline)
    build = original_build

    delivery = next(
        ref
        for ref in evidence.outcome.action_refs
        if ref.role == "sec-parser-action-delivery-v2"
    )
    if blocked:
        delivery = evidence.outcome.rejection_ref
    real_verify = action_identity.ParserBuildChecks.verify
    checks = 0

    def revoke_at_final_check(self):
        nonlocal checks
        real_verify(self)
        checks += 1
        if checks == (2 if blocked else 3):
            harness.artifacts.invalidate(delivery.artifact_id)

    monkeypatch.setattr(
        action_identity.ParserBuildChecks, "verify", revoke_at_final_check
    )
    with pytest.raises(SnapshotError, match="metadata changed"):
        closure.read(evidence.artifact_id, deadline_at=harness.deadline)
