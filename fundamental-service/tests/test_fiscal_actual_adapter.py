from datetime import UTC, date, datetime, timedelta
import base64
import os
import json
from asyncio import CancelledError
from contextlib import redirect_stderr, redirect_stdout
from functools import partial
from hashlib import sha256
from io import BytesIO, StringIO, TextIOWrapper
from pathlib import Path
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import fundamental_service.parser_action_identity as action_identity
import fundamental_service.parser_actions as parser_module
import fundamental_service.source_acquisition as acquisition_module
import fundamental_service.fiscal_focus_witness as witness_module
from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    _directory_hash,
    fact_semantic_digest,
)
from fundamental_service.data_releases import ArtifactRefV1
from fundamental_service.dqc_rulesets import DqcRulesetBindingV1, DqcRulesetCatalogV1
from fundamental_service.fiscal_parser_evidence import read_fiscal_parser_actions
from fundamental_service.fiscal_diagnostic_focus import (
    ArelleActualFocusEventV1,
    ArelleActualFocusFactV1,
    FiscalDiagnosticFocusExecutionV1,
)
from fundamental_service.fiscal_focus_witness import (
    FiscalDiagnosticFocusWitnessOwner,
    FiscalFocusValidatorAuthorityV1,
)
from fundamental_service.fiscal_source_validation import (
    resolve_fiscal_validation_profile,
)
from fundamental_service.fiscal_source_runner import main as fiscal_command
from fundamental_service.fiscal_validation_contracts import FISCAL_TAXONOMY_CACHE_SHA256
from fundamental_service.ingestion import SecIngestionService
from fundamental_service.metadata import _check_metadata_budget
from fundamental_service.parser_action_contracts import ParserBuildIdentityV1
from fundamental_service.parser_action_identity import ParserBuildChecks
from fundamental_service.parser_actions import ParserActions
from fundamental_service.replay import ArtifactStore
from fundamental_service.sec_source import _SecResponse
from fundamental_service.serialization import canonical_bytes, sha256_digest
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


@pytest.mark.parametrize(
    ("blocked", "witness_case"),
    [(False, "valid")]
    + [
        (True, case)
        for case in (
            "valid",
            "configured-cli",
            "action-revoked",
            "source-revoked",
            "discovery-revoked",
            "worker-incomplete",
            "worker-multiple-focus",
            "worker-other-finding",
            "worker-error",
            "worker-cancelled",
            "worker-expired",
            "worker-build-drift",
            "first-staging-error",
            "second-staging-error",
            "authority-revoked",
            "authority-expired",
            "authority-key-mismatch",
            "authority-revoked-in-worker",
            "authority-expired-in-worker",
            "execute-metadata-expired",
            "read-metadata-expired",
            "publication-source-revoked",
            "publication-authority-revoked",
            "read-source-revoked",
            "read-envelope-revoked",
            "read-authority-revoked",
            "read-authority-expired",
            "read-authority-wrong-key",
            "read-authority-revoked-during-read",
            "read-envelope-expired-during-read",
            "execute-existing-envelope-expired",
            "publication-envelope-expired-before-return",
        )
    ],
)
def test_configured_fiscal_validation_and_retained_replay(
    tmp_path, monkeypatch, blocked, witness_case
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
                        severity="warning",
                        rule_severity="error",
                        rule_effective_date=date(2017, 3, 28),
                        message="Synthetic raw block",
                    ),
                )
                if blocked
                else (),
                "finding_codes": ("DQC.US.0015.5970",) if blocked else (),
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
        signing_key = Ed25519PrivateKey.generate()
        authority = FiscalFocusValidatorAuthorityV1(
            authority_id="synthetic-focus-validator",
            principal_id="synthetic-service-principal",
            public_key_ed25519_base64=base64.b64encode(
                signing_key.public_key().public_bytes(
                    serialization.Encoding.Raw,
                    serialization.PublicFormat.Raw,
                )
            ).decode("ascii"),
            valid_until=harness.now + timedelta(days=1),
        )
        retained_actions = read_fiscal_parser_actions(
            evidence.outcome.integrity.validation_evidence,
            relation=evidence.outcome.integrity.integrity_relation,
            artifacts=harness.artifacts,
            build_checks=ParserBuildChecks(),
            delivery_revision=evidence.outcome.runtime.delivery_revision,
        )
        worker_reports = iter(
            action.report
            for action in (retained_actions.normalized, retained_actions.archive)
            if action is not None
        )
        worker_calls = []
        scratch_root = tmp_path / "focus-scratch"
        scratch_root.mkdir()
        created_directories = []
        temporary_directory = witness_module.TemporaryDirectory

        def retain_directory(**kwargs):
            temporary = temporary_directory(dir=scratch_root, **kwargs)
            created_directories.append(temporary)
            return temporary

        monkeypatch.setattr(witness_module, "TemporaryDirectory", retain_directory)

        def synthetic_focus_worker(path, **_kwargs):
            nonlocal authority, build
            worker_calls.append(path)
            revoke_ids = {
                "action-revoked": retained_actions.normalized.refs[0].artifact_id,
                "source-revoked": evidence.artifact_id,
                "discovery-revoked": discovery.artifact_id,
            }
            if witness_case in revoke_ids:
                harness.artifacts.invalidate(revoke_ids[witness_case])
            if witness_case == "worker-error":
                raise RuntimeError("synthetic official worker failure")
            if witness_case == "worker-cancelled":
                raise CancelledError
            if witness_case == "worker-expired":
                harness.now = harness.deadline + timedelta(microseconds=1)
            if witness_case == "worker-build-drift":
                build = build.model_copy(update={"runtime_digest": "4" * 64})
            if witness_case == "authority-revoked-in-worker":
                authority = authority.model_copy(update={"status": "revoked"})
            if witness_case == "authority-expired-in-worker":
                authority = authority.model_copy(update={"valid_until": harness.now})
            source_report = next(worker_reports)
            report = source_report.model_copy(
                update={
                    "validation_evidence": tuple(
                        marker
                        for marker in source_report.validation_evidence
                        if not marker.startswith("sec-parser-action-")
                    )
                }
            )
            if witness_case == "worker-incomplete":
                report = report.model_copy(
                    update={"validation_evidence": ("strict-sec-efm-profile-selected",)}
                )
            if witness_case == "worker-other-finding":
                report = report.model_copy(
                    update={
                        "findings": (
                            *report.findings,
                            ArelleFindingV1(
                                code="EFM.extra",
                                severity="error",
                                message="Synthetic extra error",
                            ),
                        ),
                        "finding_codes": (*report.finding_codes, "EFM.extra"),
                    }
                )
            fact = next(item for item in report.facts if item.is_numeric)
            focus = ArelleActualFocusFactV1(
                fact_id="synthetic-official-focus",
                fact=fact,
                numeric_value=fact.value,
            )
            return FiscalDiagnosticFocusExecutionV1(
                report=report.model_copy(
                    update={"filing_path": str(path), "parsed_at": datetime.now(UTC)}
                ),
                events=(
                    ArelleActualFocusEventV1(
                        level="ERROR",
                        facts=(focus, focus)
                        if witness_case == "worker-multiple-focus"
                        else (focus,),
                    ),
                ),
                complete_fact_digest=fact_semantic_digest(report),
                complete_findings_digest=sha256_digest(
                    sorted(report.findings, key=sha256_digest)
                ),
            )

        if witness_case == "configured-cli":
            from test_fiscal_source_runner import _install_acquisition

            authority_path = tmp_path / "focus-authority.json"
            authority_path.write_bytes(canonical_bytes(authority))
            key_path = tmp_path / "focus-key.pem"
            key_path.write_bytes(
                signing_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            key_path.chmod(0o600)
            monkeypatch.setenv(
                "FUNDAMENTAL_FISCAL_FOCUS_AUTHORITY_FILE", str(authority_path)
            )
            monkeypatch.setenv(
                "FUNDAMENTAL_FISCAL_FOCUS_PRIVATE_KEY_FILE", str(key_path)
            )
            monkeypatch.setattr(
                acquisition_module,
                "run_fiscal_diagnostic_focus",
                synthetic_focus_worker,
            )
            _install_acquisition(monkeypatch, acquisition)

            def command(*args, revision=harness.request.declared_source_revision):
                output = TextIOWrapper(BytesIO(), encoding="utf-8")
                error = StringIO()
                with redirect_stdout(output), redirect_stderr(error):
                    code = fiscal_command(["--source-revision", revision, *args])
                raw = output.buffer.getvalue()
                return code, raw, error.getvalue()

            wrong_key = Ed25519PrivateKey.generate()
            key_path.write_bytes(
                wrong_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            before_wrong_key = harness.inventory()
            code, raw, error = command(
                "focus-witness", "--source-artifact-id", evidence.artifact_id
            )
            assert code == 2 and not raw
            assert (
                json.loads(error)["error_code"] == "FISCAL_FOCUS_AUTHORITY_KEY_MISMATCH"
            )
            assert harness.inventory() == before_wrong_key
            worker_reports = iter(
                action.report
                for action in (retained_actions.normalized, retained_actions.archive)
                if action is not None
            )
            worker_calls.clear()
            key_path.write_bytes(
                signing_key.private_bytes(
                    serialization.Encoding.PEM,
                    serialization.PrivateFormat.PKCS8,
                    serialization.NoEncryption(),
                )
            )
            code, raw, error = command(
                "focus-witness", "--source-artifact-id", evidence.artifact_id
            )
            assert (code, error) == (0, "")
            wire = json.loads(raw)
            assert raw == canonical_bytes(wire) + b"\n"
            assert (
                wire["evidence"]["protocol"]
                == "fundamental.signed-fiscal-diagnostic-focus-witness.v1"
            )
            assert wire["evidence"]["principal_id"] == "synthetic-service-principal"
            assert wire["publication"]["wrote"]
            witness_id = wire["publication"]["artifact"]["artifact_id"]
            assert (
                wire["evidence"]["witness"]["raw_finding"]["code"] == "DQC.US.0015.5970"
            )
            assert (
                wire["evidence"]["witness"]["integrity"]["quality_decision"] == "block"
            )
            assert len(worker_calls) == 2
            before_read = harness.inventory()
            source_fetches = list(fetches)
            code, repeated_raw, error = command(
                "focus-witness", "--source-artifact-id", evidence.artifact_id
            )
            assert (code, error) == (0, "")
            repeated_wire = json.loads(repeated_raw)
            assert repeated_wire["evidence"] == wire["evidence"]
            assert not repeated_wire["publication"]["wrote"]
            code, read_raw, error = command(
                "read-focus-witness", "--artifact-id", witness_id
            )
            assert (code, error) == (0, "")
            assert json.loads(read_raw) == {"evidence": wire["evidence"]}
            assert harness.inventory() == before_read
            assert fetches == source_fetches
            assert len(worker_calls) == 2
            for args in (
                ("focus-witness", "--source-artifact-id", discovery.artifact_id),
                ("read-focus-witness", "--artifact-id", witness_id),
            ):
                code, raw, error = command(*args, revision="b" * 40)
                assert code == 2 and not raw
                assert json.loads(error)["error_code"] in {
                    "FISCAL_VALIDATION_INVALID",
                    "FISCAL_VALIDATION_INPUT_INVALID",
                }
            for changed in (
                authority.model_copy(update={"status": "revoked"}),
                authority.model_copy(
                    update={"valid_until": harness.now - timedelta(seconds=1)}
                ),
                authority.model_copy(
                    update={
                        "public_key_ed25519_base64": base64.b64encode(
                            wrong_key.public_key().public_bytes_raw()
                        ).decode()
                    }
                ),
            ):
                authority_path.write_bytes(canonical_bytes(changed))
                code, raw, error = command(
                    "read-focus-witness", "--artifact-id", witness_id
                )
                assert code == 2 and not raw
                assert (
                    json.loads(error)["error_code"] == "FISCAL_FOCUS_AUTHORITY_INVALID"
                )
            authority_path.write_bytes(canonical_bytes(authority))
            monkeypatch.delenv("FUNDAMENTAL_FISCAL_FOCUS_AUTHORITY_FILE")
            code, raw, error = command(
                "read-focus-witness", "--artifact-id", witness_id
            )
            assert code == 2 and not raw
            assert (
                json.loads(error)["error_code"] == "FISCAL_FOCUS_AUTHORITY_UNCONFIGURED"
            )
            assert not tuple(scratch_root.iterdir())
            return

        owner = FiscalDiagnosticFocusWitnessOwner(
            closure=closure,
            artifacts=harness.artifacts,
            content=harness.content,
            taxonomy_cache_dir=taxonomy,
            authority=lambda: authority,
            private_key=lambda: (
                Ed25519PrivateKey.generate()
                if witness_case == "authority-key-mismatch"
                else signing_key
            ),
            current_time=lambda: harness.now,
            worker=synthetic_focus_worker,
            profile_resolver=partial(resolve_fiscal_validation_profile, acquisition),
        )
        source_record = harness.artifacts.get(evidence.artifact_id)
        source_ref = ArtifactRefV1(
            role="fiscal-original-validation",
            artifact_id=source_record.artifact_id,
            content_hash=source_record.content_hash,
            media_type=source_record.media_type,
        )
        envelope_expiry_cases = {
            "read-envelope-expired-during-read",
            "execute-existing-envelope-expired",
            "publication-envelope-expired-before-return",
        }
        if witness_case in envelope_expiry_cases:
            original_sign = owner._sign

            def sign_short_lived_witness(*args):
                signed = original_sign(*args)
                unsigned = signed.model_copy(
                    update={"expires_at": signed.signed_at + timedelta(seconds=1)}
                )
                return unsigned.model_copy(
                    update={
                        "signature": signing_key.sign(unsigned.signing_bytes()).hex()
                    }
                )

            monkeypatch.setattr(owner, "_sign", sign_short_lived_witness)

        def witness_records():
            return [
                json.loads(line)
                for line in (harness.artifacts.root / ".artifact-records.jsonl")
                .read_text()
                .splitlines()
                if json.loads(line)["artifact_id"].startswith(
                    "fiscal-diagnostic-focus-witness-v1:"
                )
            ]

        def assert_scratch_clean():
            assert not tuple(scratch_root.iterdir())
            assert all(not Path(item.name).exists() for item in created_directories)

        def expire_metadata_lookup():
            original_get = harness.artifacts.get

            def get(artifact_id):
                harness.now = harness.deadline + timedelta(microseconds=1)
                _check_metadata_budget()
                return original_get(artifact_id)

            monkeypatch.setattr(harness.artifacts, "get", get)

        if witness_case == "execute-metadata-expired":
            expire_metadata_lookup()
            with pytest.raises(SnapshotError) as failure:
                owner.execute(source_ref, deadline_at=harness.deadline)
            assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
            _check_metadata_budget()
            assert not worker_calls
            assert not witness_records()
            assert_scratch_clean()
            return
        if witness_case in {"first-staging-error", "second-staging-error"}:
            original_input = witness_module.parser_action_input
            staged_calls = 0

            def fail_staged_input(*args, **kwargs):
                nonlocal staged_calls
                staged_calls += 1
                expected_calls = 1 if witness_case == "first-staging-error" else 2
                if staged_calls == expected_calls:
                    raise OSError("synthetic staged input failure")
                return original_input(*args, **kwargs)

            monkeypatch.setattr(
                witness_module, "parser_action_input", fail_staged_input
            )
            with pytest.raises(OSError, match="staged input failure"):
                owner.execute(source_ref, deadline_at=harness.deadline)
            assert len(created_directories) == staged_calls
            assert not worker_calls
            assert not witness_records()
            assert_scratch_clean()
            return
        if witness_case == "authority-revoked":
            authority = authority.model_copy(update={"status": "revoked"})
        if witness_case == "authority-expired":
            authority = authority.model_copy(update={"valid_until": harness.now})
        expected_errors = {
            "action-revoked": "FISCAL_VALIDATION_INVALID",
            "source-revoked": "FISCAL_VALIDATION_INVALID",
            "discovery-revoked": "FISCAL_VALIDATION_INVALID",
            "worker-incomplete": "VALIDATION_EVIDENCE_MISSING",
            "worker-multiple-focus": "FISCAL_FOCUS_OBJECT_AMBIGUOUS",
            "worker-other-finding": "FISCAL_FOCUS_REPORT_MISMATCH",
            "worker-expired": "REQUEST_DEADLINE_EXCEEDED",
            "worker-build-drift": "FISCAL_FOCUS_RUNTIME_CHANGED",
            "authority-revoked": "FISCAL_FOCUS_AUTHORITY_INVALID",
            "authority-expired": "FISCAL_FOCUS_AUTHORITY_INVALID",
            "authority-key-mismatch": "FISCAL_FOCUS_AUTHORITY_KEY_MISMATCH",
            "authority-revoked-in-worker": "FISCAL_FOCUS_AUTHORITY_INVALID",
            "authority-expired-in-worker": "FISCAL_FOCUS_AUTHORITY_INVALID",
        }
        if witness_case in expected_errors:
            with pytest.raises(SnapshotError) as failure:
                owner.execute(source_ref, deadline_at=harness.deadline)
            assert failure.value.code == expected_errors[witness_case]
            assert not witness_records()
            assert_scratch_clean()
            return
        if witness_case in {"worker-error", "worker-cancelled"}:
            error = RuntimeError if witness_case == "worker-error" else CancelledError
            with pytest.raises(error):
                owner.execute(source_ref, deadline_at=harness.deadline)
            assert not witness_records()
            assert_scratch_clean()
            return
        if witness_case in {
            "publication-source-revoked",
            "publication-authority-revoked",
        }:
            original_put = harness.artifacts.put_with_receipt

            def revoke_at_publication(*args, **kwargs):
                nonlocal authority
                if witness_case == "publication-authority-revoked":
                    authority = authority.model_copy(update={"status": "revoked"})
                publication = original_put(*args, **kwargs)
                harness.artifacts.invalidate(evidence.artifact_id)
                return publication

            monkeypatch.setattr(
                harness.artifacts, "put_with_receipt", revoke_at_publication
            )
            with pytest.raises(SnapshotError) as failure:
                owner.execute(source_ref, deadline_at=harness.deadline)
            if witness_case == "publication-source-revoked":
                assert failure.value.code == "FISCAL_VALIDATION_INVALID"
                (retained_witness,) = witness_records()
                with pytest.raises(SnapshotError):
                    owner.read(
                        retained_witness["artifact_id"], deadline_at=harness.deadline
                    )
            else:
                assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_INVALID"
                assert not witness_records()
            assert_scratch_clean()
            return
        if witness_case == "publication-envelope-expired-before-return":
            original_check_current = owner._check_current

            def expire_before_return(*args):
                original_check_current(*args)
                if witness_records():
                    harness.now += timedelta(seconds=2)

            monkeypatch.setattr(owner, "_check_current", expire_before_return)
            with pytest.raises(SnapshotError) as failure:
                owner.execute(source_ref, deadline_at=harness.deadline)
            assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_INVALID"
            assert harness.now < authority.valid_until
            assert harness.now < harness.deadline
            (retained_witness,) = witness_records()
            with pytest.raises(SnapshotError, match="expired"):
                owner.read(
                    retained_witness["artifact_id"], deadline_at=harness.deadline
                )
            assert_scratch_clean()
            return
        published_witness = owner.execute(source_ref, deadline_at=harness.deadline)
        assert published_witness.publication.wrote
        assert published_witness.witness.witness.actual_focus.fact == next(
            item for item in evidence.outcome.claim.report.facts if item.is_numeric
        )
        assert published_witness.witness.witness.raw_finding.severity == "warning"
        if witness_case in {
            "read-envelope-expired-during-read",
            "execute-existing-envelope-expired",
        }:
            original_stage_inputs = owner._stage_inputs

            def expire_during_staging(*args):
                staged = original_stage_inputs(*args)
                harness.now += timedelta(seconds=2)
                return staged

            monkeypatch.setattr(owner, "_stage_inputs", expire_during_staging)
            before_expired_operation = harness.inventory()
            with pytest.raises(SnapshotError) as failure:
                if witness_case == "read-envelope-expired-during-read":
                    owner.read(
                        published_witness.witness.artifact_id,
                        deadline_at=harness.deadline,
                    )
                else:
                    owner.execute(source_ref, deadline_at=harness.deadline)
            assert failure.value.code == "FISCAL_FOCUS_AUTHORITY_INVALID"
            assert published_witness.witness.expires_at <= harness.now
            assert harness.now < authority.valid_until
            assert harness.now < harness.deadline
            assert harness.inventory() == before_expired_operation
            assert len(worker_calls) == 2
            assert_scratch_clean()
            return
        observation = None
        if witness_case in {
            "valid",
            "read-source-revoked",
            "read-authority-revoked",
            "read-authority-expired",
            "read-authority-wrong-key",
        }:
            observation = owner.observe(
                published_witness.witness.artifact_id, deadline_at=harness.deadline
            )
            assert observation.witness == published_witness.witness
            observation.check_current()
        if witness_case == "read-metadata-expired":
            expire_metadata_lookup()
            expected_read_error = "REQUEST_DEADLINE_EXCEEDED"
        elif witness_case == "read-source-revoked":
            harness.artifacts.invalidate(evidence.artifact_id)
            expected_read_error = "FISCAL_VALIDATION_INVALID"
        elif witness_case == "read-envelope-revoked":
            original_read = harness.artifacts.read

            def revoke_envelope(artifact_id):
                raw = original_read(artifact_id)
                if artifact_id == published_witness.witness.artifact_id:
                    harness.artifacts.invalidate(artifact_id)
                return raw

            monkeypatch.setattr(harness.artifacts, "read", revoke_envelope)
            expected_read_error = "FISCAL_VALIDATION_INVALID"
        elif witness_case == "read-authority-revoked-during-read":
            original_read = harness.artifacts.read

            def revoke_authority(artifact_id):
                nonlocal authority
                raw = original_read(artifact_id)
                if artifact_id == evidence.artifact_id:
                    authority = authority.model_copy(update={"status": "revoked"})
                return raw

            monkeypatch.setattr(harness.artifacts, "read", revoke_authority)
            expected_read_error = "FISCAL_FOCUS_AUTHORITY_INVALID"
        elif witness_case in {
            "read-authority-revoked",
            "read-authority-expired",
            "read-authority-wrong-key",
        }:
            if witness_case == "read-authority-revoked":
                authority = authority.model_copy(update={"status": "revoked"})
            elif witness_case == "read-authority-expired":
                authority = authority.model_copy(update={"valid_until": harness.now})
            else:
                wrong_key = Ed25519PrivateKey.generate()
                authority = authority.model_copy(
                    update={
                        "public_key_ed25519_base64": base64.b64encode(
                            wrong_key.public_key().public_bytes_raw()
                        ).decode("ascii")
                    }
                )
            expected_read_error = "FISCAL_FOCUS_AUTHORITY_INVALID"
        else:
            expected_read_error = None
        if expected_read_error is not None:
            with pytest.raises(SnapshotError) as failure:
                owner.read(
                    published_witness.witness.artifact_id, deadline_at=harness.deadline
                )
            assert failure.value.code == expected_read_error
            if observation is not None:
                with pytest.raises(SnapshotError) as current_failure:
                    observation.check_current()
                assert current_failure.value.code == expected_read_error
            _check_metadata_budget()
            assert len(worker_calls) == 2
            assert_scratch_clean()
            return
        before_replay = harness.inventory()
        if observation is not None:
            observation.check_current()
            original_rules_stat = ruleset.stat()
            original_rules = ruleset.read_bytes()
            try:
                ruleset.write_bytes(original_rules + b"changed")
                with pytest.raises(SnapshotError):
                    observation.check_current()
            finally:
                ruleset.write_bytes(original_rules)
                os.utime(
                    ruleset,
                    ns=(
                        original_rules_stat.st_atime_ns,
                        original_rules_stat.st_mtime_ns,
                    ),
                )
            raw_receipt = next(
                item
                for item in evidence.outcome.responses
                if item.uri == evidence.outcome.integrity.primary_document_uri
            )
            raw_path = harness.content._path(
                raw_receipt.content_hash, raw_receipt.media_type
            )
            original_content_stat = raw_path.stat()
            original_content = raw_path.read_bytes()
            try:
                raw_path.write_bytes(original_content[:-1] + b"!")
                with pytest.raises(SnapshotError):
                    observation.check_current()
            finally:
                raw_path.write_bytes(original_content)
                os.utime(
                    raw_path,
                    ns=(
                        original_content_stat.st_atime_ns,
                        original_content_stat.st_mtime_ns,
                    ),
                )
            observation.check_current()
        assert (
            owner.read(
                published_witness.witness.artifact_id, deadline_at=harness.deadline
            )
            == published_witness.witness
        )
        repeated = owner.execute(source_ref, deadline_at=harness.deadline)
        assert not repeated.publication.wrote
        assert repeated.witness == published_witness.witness
        assert harness.inventory() == before_replay
        assert len(worker_calls) == 2
        assert_scratch_clean()
        harness.replace_value(
            published_witness.witness.artifact_id,
            published_witness.witness.model_copy(
                update={"signature": "0" * 128}
            ).model_dump(mode="json"),
        )
        with pytest.raises(SnapshotError) as invalid_signature:
            owner.read(
                published_witness.witness.artifact_id,
                deadline_at=harness.deadline,
            )
        assert invalid_signature.value.code == "FISCAL_FOCUS_SIGNATURE_INVALID"
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
    source_observation = closure.observe(
        evidence.artifact_id, deadline_at=harness.deadline
    )
    source_observation.check_current()
    original_build = build
    build = build.model_copy(update={"runtime_digest": "4" * 64})
    with pytest.raises(SnapshotError):
        source_observation.check_current()
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
