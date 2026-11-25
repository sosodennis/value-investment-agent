from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from io import BytesIO
from uuid import uuid4
from zipfile import ZipFile

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from lxml import etree

from fundamental_service.arelle_parser import (
    ArelleFindingV1,
    ParsedXbrlFactV1,
    fact_semantic_digest,
)
from fundamental_service.artifact_evidence import read_retained_artifact
from fundamental_service.contracts import QualityStatus
from fundamental_service.fiscal_admission_authority import FiscalAuthorityOwner
from fundamental_service.fiscal_admission_history import PostgresFiscalAdmissionHistory
from fundamental_service.fiscal_authority_contracts import (
    FiscalAuthorityDeploymentV1,
    FiscalAuthorityIdentityV1,
    FiscalConfiguredAuthorityV1,
    FiscalConfiguredRegistryRootV1,
    FiscalGrantAuthorityCommandV1,
    FiscalRegistryRootIdentityV1,
    FiscalRevokeAuthorityCommandV1,
)
from fundamental_service.fiscal_candidate_contracts import FiscalSourceUseScopeV1
from fundamental_service.fiscal_classification_contracts import (
    FiscalClassifierActorV1,
    FiscalClassifierReviewExecutionV1,
    FiscalRecordClassificationCommandV1,
    FiscalReviewFactV1,
    FiscalSourceAccountingReviewV1,
    FiscalSourcePreparationExecutionV1,
    FiscalReconciliationTermV1,
    FiscalSourceReconciliationV1,
    SignedFiscalSourcePreparationExecutionV1,
)
from fundamental_service.fiscal_classification_source import FiscalClassificationSource
from fundamental_service.fiscal_diagnostic_focus import ArelleActualFocusFactV1
from fundamental_service.fiscal_focus_witness import (
    FiscalDiagnosticFocusWitnessV1,
    FiscalFocusActionBindingV1,
    SignedFiscalDiagnosticFocusWitnessV1,
)
from fundamental_service.fiscal_source_classification import (
    FiscalSourceClassificationOwner,
)
from fundamental_service.fiscal_source_contracts import evaluate_fiscal_issuer
from fundamental_service.fiscal_statement_contracts import (
    FiscalObservationV1,
    FiscalReportingBasisV1,
    FiscalSourceLocatorV1,
    ReportedInstantV1,
)
from fundamental_service.fiscal_statement_mapping import (
    fiscal_display_profile_digest,
    fiscal_mapping_policy_digest,
)
from fundamental_service.fiscal_validation_contracts import (
    FiscalOriginalValidationEvidenceV1,
    FiscalValidationCompleteRefusedV1,
    FiscalValidationPinV1,
    ResolvedFiscalValidationRequestV1,
)
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.parser_action_contracts import (
    ParserActionDeliveryV2,
    ParserActionInputV3,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import SnapshotError
from test_fiscal_admission_authority import (
    SyntheticRegistrySigner,
    public_key,
    reference,
    change_status,
)
from test_fiscal_admission_history import _temporary_database
from test_fiscal_discovery import DiscoveryHarness
from test_fiscal_source_closure import SyntheticCompleteSource, _selection


def deadline():
    return datetime.now(UTC) + timedelta(seconds=30)


def retained(store, identity, value, role):
    return reference(store.put_with_receipt(identity, value).artifact, role)


def synthetic_source(tmp_path, store, focus_key):
    harness = DiscoveryHarness(tmp_path)
    discovery, published = harness.publish()
    request = ResolvedFiscalValidationRequestV1(
        selection=_selection(discovery, published),
        filing=discovery.selection.selected[0],
        valuation_timestamp=discovery.request.valuation_timestamp,
        pin=FiscalValidationPinV1(
            declared_source_revision=harness.request.declared_source_revision,
            taxonomy_manifest_id="synthetic-fiscal-cache",
        ),
    )
    base = SyntheticCompleteSource(harness).validate(
        request, deadline_at=harness.deadline
    )
    filing = request.filing
    ns = "http://fasb.org/us-gaap/2024"
    primary = f'''<html xmlns="http://www.w3.org/1999/xhtml" xmlns:ix="http://www.xbrl.org/2013/inlineXBRL" xmlns:xbrli="http://www.xbrl.org/2003/instance" xmlns:us-gaap="{ns}" xmlns:iso4217="http://www.xbrl.org/2003/iso4217"><body><ix:header><xbrli:context id="synthetic-context"><xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">{filing.cik}</xbrli:identifier></xbrli:entity><xbrli:period><xbrli:instant>{filing.report_period_end}</xbrli:instant></xbrli:period></xbrli:context><xbrli:unit id="USD"><xbrli:measure>iso4217:USD</xbrli:measure></xbrli:unit></ix:header><table><tr><td><ix:nonFraction id="synthetic-focus" name="us-gaap:ShortTermInvestments" contextRef="synthetic-context" unitRef="USD" scale="6" sign="-" decimals="-6">1</ix:nonFraction></td></tr><tr><td><ix:nonFraction id="synthetic-other" name="us-gaap:CashAndCashEquivalentsAtCarryingValue" contextRef="synthetic-context" unitRef="USD" scale="6" decimals="-6">4</ix:nonFraction></td></tr><tr><td><ix:nonFraction id="synthetic-total" name="us-gaap:AssetsCurrent" contextRef="synthetic-context" unitRef="USD" scale="6" decimals="-6">3</ix:nonFraction></td></tr></table></body></html>'''.encode()
    member_hash = hashlib.sha256(primary).hexdigest()
    archive_io = BytesIO()
    with ZipFile(archive_io, "w") as package:
        package.writestr(filing.primary_document, primary)
    archive = archive_io.getvalue()
    archive_hash = hashlib.sha256(archive).hexdigest()
    parsed = tuple(
        ParsedXbrlFactV1(
            concept=concept,
            namespace_uri=ns,
            value=value,
            context_id="synthetic-context",
            unit="iso4217:USD",
            decimals="-6",
            entity_scheme="http://www.sec.gov/CIK",
            entity_identifier=filing.cik,
            instant=filing.report_period_end,
            is_numeric=True,
            scale=6,
            consolidation_scope="consolidated",
            security_scope="unspecified",
        )
        for concept, value in (
            ("us-gaap:ShortTermInvestments", "-1000000"),
            ("us-gaap:CashAndCashEquivalentsAtCarryingValue", "4000000"),
            ("us-gaap:AssetsCurrent", "3000000"),
        )
    )
    finding = ArelleFindingV1(
        code="DQC.US.0015.5970",
        severity="warning",
        rule_severity="error",
        rule_effective_date=filing.filing_date - timedelta(days=1),
        message="Synthetic diagnostic focus",
    )
    report = base.claim.report.model_copy(
        update={
            "facts": (*base.claim.report.facts, *parsed),
            "findings": (finding,),
            "finding_codes": (finding.code,),
            "source_content_hash": member_hash,
        }
    )
    original = base.claim.source.model_copy(
        update={"content_hash": member_hash, "parser_input_hash": member_hash}
    )
    claim = evaluate_fiscal_issuer(
        report,
        filing=filing,
        source=original,
        decision_at=request.valuation_timestamp,
        request_digest=request.digest,
    )
    responses = tuple(
        receipt.model_copy(
            update={
                "content_hash": member_hash,
                "declared_size": len(primary),
                "received_size": len(primary),
            }
        )
        if receipt.uri == original.uri
        else receipt.model_copy(
            update={
                "content_hash": archive_hash,
                "declared_size": len(archive),
                "received_size": len(archive),
            }
        )
        if receipt.uri == base.integrity.archive_uri
        else receipt
        for receipt in base.responses
    )
    integrity = base.integrity.model_copy(
        update={
            "raw_content_hash": member_hash,
            "raw_received_size": len(primary),
            "declared_primary_size": len(primary),
            "archive_hash": archive_hash,
            "archive_size": len(archive),
            "archive_member_hash": member_hash,
            "archive_member_size": len(primary),
            "normalized_content_hash": member_hash,
            "normalized_content_size": len(primary),
            "parser_input_hash": member_hash,
            "normalized_fact_count": len(report.facts),
            "normalized_fact_digest": fact_semantic_digest(report),
            "archive_fact_count": len(report.facts),
            "archive_fact_digest": fact_semantic_digest(report),
        }
    )
    outcome = FiscalValidationCompleteRefusedV1.model_validate_json(
        canonical_bytes(
            base.model_copy(
                update={
                    "claim": claim,
                    "integrity": integrity,
                    "responses": responses,
                    "issue_codes": claim.issue_codes,
                }
            ).model_dump(mode="json")
        )
    )
    evidence = FiscalOriginalValidationEvidenceV1(request=request, outcome=outcome)
    source_ref = reference(
        store.put_with_receipt(
            evidence.artifact_id,
            evidence.model_dump(mode="json"),
            evidence.dependencies,
        ).artifact,
        "fiscal-original-validation",
    )
    binding = sha256_digest(evidence.model_dump(mode="json"))
    action_refs = []
    for old in outcome.action_refs:
        raw = harness.artifacts.read(old.artifact_id)
        publication = store.put_bytes_with_receipt(
            old.artifact_id,
            raw,
            harness.artifacts.get(old.artifact_id).dependency_hashes,
            media_type=old.media_type,
        )
        action_refs.append(reference(publication.artifact, old.role))
    refs = {ref.role: ref for ref in action_refs}
    action_request = ParserActionInputV3(
        representation="normalized",
        entrypoint=filing.primary_document,
        files=((filing.primary_document, member_hash),),
        normalization_inputs=(),
        resources=(),
        profile_digest=report.validation_profile_digest,
        taxonomy_version=report.taxonomy_version,
        source_content_hash=member_hash,
        build=outcome.runtime.parser_build,
    )
    delivery = ParserActionDeliveryV2(
        action_key=action_request.digest,
        result_artifact_id=refs["sec-parser-action-result-v2"].artifact_id,
        report_content_hash=refs["sec-parser-action-report-v1"].content_hash,
        delivery_revision=outcome.runtime.delivery_revision,
        build=outcome.runtime.parser_build,
    )
    action = FiscalFocusActionBindingV1(
        representation="normalized",
        request=action_request,
        result_ref=refs["sec-parser-action-result-v2"],
        report_ref=refs["sec-parser-action-report-v1"],
        delivery_ref=refs["sec-parser-action-delivery-v2"],
        delivery=delivery,
        report_digest=sha256_digest(report.model_dump(mode="json")),
    )
    body = FiscalDiagnosticFocusWitnessV1(
        source_validation_ref=source_ref,
        request_digest=request.digest,
        filing=filing,
        cutoff=request.valuation_timestamp,
        source_available_at=original.available_at,
        integrity=integrity,
        runtime=outcome.runtime,
        source_responses=responses,
        raw_report_digest=sha256_digest(report.model_dump(mode="json")),
        raw_report_fact_digest=fact_semantic_digest(report),
        raw_report_findings_digest=sha256_digest(
            sorted(report.findings, key=sha256_digest)
        ),
        raw_finding=finding,
        actions=(action,),
        filing_context=report.dqc_filing_context,
        actual_focus=ArelleActualFocusFactV1(
            fact_id="synthetic-focus", fact=parsed[0], numeric_value="-1000000"
        ),
        worker_module_sha256="a" * 64,
        applicability_policy_digest="b" * 64,
    )
    now = datetime.now(UTC)
    witness = SignedFiscalDiagnosticFocusWitnessV1(
        witness=body,
        authority_id="synthetic-focus",
        principal_id="machine:synthetic-focus",
        key_id=hashlib.sha256(focus_key.public_key().public_bytes_raw()).hexdigest(),
        signed_at=now,
        expires_at=now + timedelta(hours=1),
        signature="0" * 128,
    )
    witness = witness.model_copy(
        update={"signature": focus_key.sign(witness.signing_bytes()).hex()}
    )
    witness_ref = retained(
        store, witness.artifact_id, witness, "fiscal-diagnostic-focus-witness-v1"
    )
    observation = FiscalObservationV1(
        observation_id="synthetic-observation",
        row_id="short_term_investments",
        statement="balance_sheet",
        source_artifact_id=source_ref.artifact_id,
        accession_number=filing.accession_number,
        form=filing.form,
        issuer_id=filing.cik,
        accepted_at=filing.accepted_at,
        available_at=filing.accepted_at,
        filing_date=filing.filing_date,
        report_date=filing.report_period_end,
        period=ReportedInstantV1(instant=filing.report_period_end),
        basis=FiscalReportingBasisV1(
            issuer_id=filing.cik,
            security_id=None,
            security_scope="issuer",
            entity_scope=filing.cik,
            currency="USD",
            unit="iso4217:USD",
            consolidation_scope="consolidated",
        ),
        source_locator=FiscalSourceLocatorV1(
            primary_document_sha256=member_hash,
            context_id="synthetic-context",
            fact_index=0,
            table_index=0,
            row_index=0,
        ),
        concept=parsed[0].concept,
        namespace_uri=ns,
        source_fact_key="synthetic-focus",
        raw_text="1",
        value=Decimal("-1000000"),
        scale=6,
        sign="-",
        decimals=-6,
        quality=QualityStatus.PROVISIONAL,
        source_binding_digest=binding,
        parser_action_digest=sha256_digest(action_refs),
        mapping_digest=fiscal_mapping_policy_digest(),
    )
    scope = FiscalSourceUseScopeV1(
        source_validation_ref=source_ref,
        validation_kind="complete_refused",
        source_binding_digest=binding,
        issuer_id=filing.cik,
        accession_number=filing.accession_number,
        cutoff_at=request.valuation_timestamp,
        runtime=outcome.runtime,
        raw_report_digest=sha256_digest(report.model_dump(mode="json")),
        parser_action_refs=outcome.action_refs,
        witness_ref=witness_ref,
        display_profile_digest=fiscal_display_profile_digest(),
        mapping_policy_digest=fiscal_mapping_policy_digest(),
        permitted_inputs=(observation,),
    )
    root = etree.fromstring(primary)
    table = root.xpath('//*[local-name()="table"]')[0]
    rows = table.xpath('.//*[local-name()="tr"]')
    facts = tuple(
        FiscalReviewFactV1(
            fact_id=node.get("id"),
            fact=fact,
            table_index=0,
            row_index=index,
            table_sha256=hashlib.sha256(
                etree.tostring(table, method="c14n")
            ).hexdigest(),
            row_sha256=hashlib.sha256(
                etree.tostring(rows[index], method="c14n")
            ).hexdigest(),
            raw_lexical=node.text,
            raw_sign=node.get("sign"),
            raw_scale=6,
            raw_decimals="-6",
            value=Decimal(fact.value),
        )
        for index, (node, fact) in enumerate(
            zip(root.xpath('//*[local-name()="nonFraction"]'), parsed, strict=True)
        )
    )
    review = FiscalSourceAccountingReviewV1(
        scope=scope,
        facts=facts,
        reconciliations=(
            FiscalSourceReconciliationV1(
                description="Synthetic disclosed signed components",
                terms=(
                    FiscalReconciliationTermV1(
                        fact_id="synthetic-focus", coefficient=1
                    ),
                    FiscalReconciliationTermV1(
                        fact_id="synthetic-other", coefficient=1
                    ),
                ),
                result_fact_id="synthetic-total",
                residual=Decimal(0),
                precision_allowance=Decimal("1500000"),
            ),
        ),
        limitations=(
            "Synthetic test only. Tag appropriateness unresolved; no display or valuation approval.",
        ),
    )
    return FiscalClassificationSource(scope, evidence, witness, archive), review


class SyntheticSourceResolver:
    def __init__(self, source, key):
        self.source, self.key = source, key
        self.on_resolve = lambda: None

    def resolve(
        self,
        source_ref,
        witness_ref,
        security_id,
        *,
        reader,
        check_deadline,
        deadline_at,
    ):
        self.on_resolve()
        check_deadline()
        assert security_id is None
        source = self.source
        assert source_ref == source.scope.source_validation_ref
        assert witness_ref == source.scope.witness_ref
        assert read_retained_artifact(reader, source_ref) == canonical_bytes(
            source.evidence.model_dump(mode="json")
        )
        assert read_retained_artifact(reader, witness_ref) == canonical_bytes(
            source.witness
        )
        self.key.public_key().verify(
            bytes.fromhex(source.witness.signature), source.witness.signing_bytes()
        )
        if datetime.now(UTC) >= source.witness.expires_at:
            raise SnapshotError(
                "SYNTHETIC_WITNESS_EXPIRED", "synthetic witness expired"
            )
        for ref in source.scope.parser_action_refs:
            read_retained_artifact(reader, ref)
        return source


class SyntheticClassifierSigner:
    def __init__(self, store, identity, key):
        self.store, self.identity, self.key = store, identity, key
        self.sign_calls = 0
        self.on_sign = lambda: None
        self.execution_update = lambda execution: execution

    def authenticate(self, command, review, *, issuance, deadline_at):
        now = datetime.now(UTC)
        identity = self.identity
        execution = FiscalClassifierReviewExecutionV1(
            authority_id=identity.authority_id,
            principal_id=identity.principal_id,
            principal_kind=identity.principal_kind,
            key_id=identity.key_id,
            execution_id="synthetic-review:" + uuid4().hex,
            issuance=issuance,
            command_digest=command.command_digest,
            scope_digest=review.scope.scope_digest,
            review_ref=command.review_ref,
            started_at=now,
            completed_at=now,
        )
        execution = self.execution_update(execution)
        ref = retained(
            self.store,
            execution.execution_id,
            execution,
            "fiscal-classifier-review-execution-v1",
        )
        return FiscalClassifierActorV1(
            authority_id=identity.authority_id,
            principal_id=identity.principal_id,
            principal_kind=identity.principal_kind,
            key_id=identity.key_id,
            execution_ref=ref,
        )

    def sign(self, message, *, actor, deadline_at):
        self.sign_calls += 1
        self.on_sign()
        return self.key.sign(message).hex()


@pytest.fixture
def environment(tmp_path):
    url = os.getenv("FUNDAMENTAL_TEST_DATABASE_URL")
    if url is None:
        pytest.skip("requires disposable PostgreSQL classification storage")
    with _temporary_database(url) as database:
        metadata = PostgresMetadataStore(database, auto_migrate=True)
        metadata.start()
        try:
            store = PostgresArtifactStore(
                metadata, PostgresContentStore(tmp_path / "pg-content", metadata)
            )
            now = datetime.now(UTC)
            registry_key, preparer_key, classifier_key, focus_key = (
                Ed25519PrivateKey.generate() for _ in range(4)
            )
            root = FiscalRegistryRootIdentityV1(
                root_id="synthetic-root",
                principal_id="machine:synthetic-root",
                principal_kind="machine",
                public_key_ed25519_base64=public_key(registry_key),
                valid_from=now - timedelta(minutes=1),
                valid_until=now + timedelta(days=1),
            )
            identities = tuple(
                FiscalAuthorityIdentityV1(
                    authority_id="synthetic-" + role,
                    principal_id="machine:synthetic-" + role,
                    principal_kind="machine",
                    public_key_ed25519_base64=public_key(key),
                    role=role,
                )
                for role, key in (
                    ("source_preparer", preparer_key),
                    ("classifier", classifier_key),
                )
            )
            deployment = FiscalAuthorityDeploymentV1(
                roots=(
                    FiscalConfiguredRegistryRootV1(
                        identity=root,
                        evidence_ref=retained(
                            store, "synthetic-root", root, "fiscal-registry-root-v1"
                        ),
                    ),
                ),
                authorities=tuple(
                    FiscalConfiguredAuthorityV1(
                        identity=identity,
                        provisioning_ref=retained(
                            store,
                            identity.authority_id,
                            identity,
                            "fiscal-authority-provisioning-v1",
                        ),
                    )
                    for identity in identities
                ),
            )
            history = PostgresFiscalAdmissionHistory(metadata)
            authorities = FiscalAuthorityOwner(
                artifacts=store,
                history=history,
                deployment=lambda: deployment,
                signer=SyntheticRegistrySigner(store, root, registry_key),
            )
            grants = {
                identity.role: authorities.grant(
                    FiscalGrantAuthorityCommandV1(
                        command_id="synthetic-grant-" + identity.role,
                        authority_id=identity.authority_id,
                        expires_at=now + timedelta(hours=2),
                    ),
                    expected_head=None,
                    deadline_at=deadline(),
                )
                for identity in identities
            }
            source, review = synthetic_source(tmp_path / "source", store, focus_key)
            resolver = SyntheticSourceResolver(source, focus_key)
            preparation = FiscalSourcePreparationExecutionV1(
                source_validation_ref=source.scope.source_validation_ref,
                source_binding_digest=source.scope.source_binding_digest,
                runtime=source.scope.runtime,
                authority_id=identities[0].authority_id,
                authority_grant_ref=reference(
                    grants["source_preparer"].publication.artifact,
                    "fiscal-authority-record-v1",
                ),
                principal_id=identities[0].principal_id,
                principal_kind="machine",
                key_id=identities[0].key_id,
                execution_id="synthetic-preparation-execution",
                issuance=history.read_epoch(deadline_at=deadline()).issuance_context,
                started_at=datetime.now(UTC),
                completed_at=datetime.now(UTC),
            )
            signed = SignedFiscalSourcePreparationExecutionV1(
                execution=preparation, signature="0" * 128
            )
            signed = signed.model_copy(
                update={"signature": preparer_key.sign(signed.signing_bytes()).hex()}
            )
            preparer_ref = retained(
                store,
                preparation.execution_id,
                signed,
                "fiscal-source-preparation-execution-v1",
            )
            review_ref = retained(
                store,
                "synthetic-source-review",
                review,
                "fiscal-source-accounting-review-v1",
            )
            command = FiscalRecordClassificationCommandV1(
                command_id="synthetic-classify",
                authority_id=identities[1].authority_id,
                source_validation_ref=source.scope.source_validation_ref,
                witness_ref=source.scope.witness_ref,
                review_ref=review_ref,
                preparer_execution_ref=preparer_ref,
                expires_at=datetime.now(UTC) + timedelta(minutes=30),
            )
            signer = SyntheticClassifierSigner(store, identities[1], classifier_key)
            owner = FiscalSourceClassificationOwner(
                artifacts=store,
                history=history,
                authorities=authorities,
                sources=resolver,
                signer=signer,
            )

            class Environment:
                pass

            env = Environment()
            env.owner, env.signer, env.command, env.source, env.review, env.resolver = (
                owner,
                signer,
                command,
                source,
                review,
                resolver,
            )
            env.store, env.history, env.metadata, env.grants, env.authorities = (
                store,
                history,
                metadata,
                grants,
                authorities,
            )
            env.database_url, env.preparer_key = database, preparer_key
            yield env
        finally:
            metadata.close()


def test_signed_classification_candidate_and_same_command_retry(environment):
    env = environment
    first = env.owner.record_classification(
        env.command, expected_head=None, deadline_at=deadline()
    )
    ref = reference(first.publication.artifact, "fiscal-source-classification-v1")
    admitted = env.owner.require_candidate_source(
        env.source.scope, (ref,), deadline_at=deadline()
    )
    assert admitted.kind == "classified_provisional"
    assert admitted.scope.permitted_inputs[0].value == Decimal("-1000000")
    assert admitted.scope.validation_kind == "complete_refused"
    assert admitted.scope.permitted_inputs[0].quality is QualityStatus.PROVISIONAL
    repeated = env.owner.record_classification(
        env.command, expected_head=None, deadline_at=deadline()
    )
    assert first.signed_classification == repeated.signed_classification
    assert not repeated.publication.wrote and env.signer.sign_calls == 1
    grant = env.grants["classifier"]
    env.authorities.revoke(
        FiscalRevokeAuthorityCommandV1(
            command_id="synthetic-revoke",
            authority_id=env.command.authority_id,
            grant_ref=reference(
                grant.publication.artifact, "fiscal-authority-record-v1"
            ),
            reason="Synthetic test revocation",
        ),
        expected_head=next(
            h for h in grant.history_heads if h.stream_kind == "control"
        ),
        deadline_at=deadline(),
    )
    with pytest.raises(SnapshotError, match="revoked"):
        env.owner.require_candidate_source(
            env.source.scope, (ref,), deadline_at=deadline()
        )


def publish_classification(env):
    result = env.owner.record_classification(
        env.command, expected_head=None, deadline_at=deadline()
    )
    return result, reference(
        result.publication.artifact, "fiscal-source-classification-v1"
    )


@pytest.mark.parametrize(
    "change",
    [
        "sign",
        "lexical",
        "precision",
        "value",
        "context",
        "period",
        "mapping",
        "profile",
        "residual",
        "allowance",
        "other-finding",
    ],
)
def test_rejects_changed_review_original_scope_and_reconciliation(environment, change):
    env = environment
    review = env.review
    if change in {"sign", "lexical", "precision", "value", "context", "period"}:
        fact = review.facts[0]
        updates = {
            "sign": {"raw_sign": "+"},
            "lexical": {"raw_lexical": "2"},
            "precision": {"raw_decimals": "INF"},
            "value": {"value": Decimal("1000000")},
            "context": {"fact": fact.fact.model_copy(update={"context_id": "other"})},
            "period": {
                "fact": fact.fact.model_copy(
                    update={"instant": fact.fact.instant - timedelta(days=1)}
                )
            },
        }[change]
        review = review.model_copy(
            update={"facts": (fact.model_copy(update=updates), *review.facts[1:])}
        )
    elif change in {"mapping", "profile"}:
        field = (
            "mapping_policy_digest" if change == "mapping" else "display_profile_digest"
        )
        review = review.model_copy(
            update={"scope": review.scope.model_copy(update={field: "0" * 64})}
        )
    elif change in {"residual", "allowance"}:
        field = "residual" if change == "residual" else "precision_allowance"
        reconciliation = review.reconciliations[0].model_copy(
            update={field: Decimal(1)}
        )
        review = review.model_copy(update={"reconciliations": (reconciliation,)})
    else:
        outcome = env.source.evidence.outcome
        report = outcome.claim.report.model_copy(
            update={
                "findings": (
                    *outcome.claim.report.findings,
                    ArelleFindingV1(
                        code="synthetic.critical",
                        severity="error",
                        rule_severity="critical",
                        message="Synthetic critical finding",
                    ),
                )
            }
        )
        claim = outcome.claim.model_copy(update={"report": report})
        env.resolver.source = replace(
            env.source,
            evidence=env.source.evidence.model_copy(
                update={"outcome": outcome.model_copy(update={"claim": claim})}
            ),
        )
    if change != "other-finding":
        ref = retained(
            env.store,
            "synthetic-mutated-review",
            review,
            "fiscal-source-accounting-review-v1",
        )
        env.command = env.command.model_copy(update={"review_ref": ref})
    with pytest.raises((SnapshotError, AssertionError)):
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=deadline()
        )
    with pytest.raises(SnapshotError) as absent:
        env.store.get(env.command.artifact_id)
    assert absent.value.code == "ARTIFACT_NOT_FOUND"


@pytest.mark.parametrize(
    "change",
    [
        "command",
        "scope",
        "review",
        "key",
        "principal",
        "execution-time",
        "same-execution",
    ],
)
def test_rejects_unbound_classifier_execution(environment, change):
    env = environment

    def changed(execution):
        updates = {
            "command": {"command_digest": "0" * 64},
            "scope": {"scope_digest": "0" * 64},
            "review": {"review_ref": env.command.witness_ref},
            "key": {"key_id": "0" * 64},
            "principal": {"principal_id": "human:impostor", "principal_kind": "human"},
            "execution-time": {
                "started_at": datetime.now(UTC) + timedelta(hours=1),
                "completed_at": datetime.now(UTC) + timedelta(hours=2),
            },
            "same-execution": {"execution_id": "synthetic-preparation-execution"},
        }[change]
        return execution.model_copy(update=updates)

    env.signer.execution_update = changed
    with pytest.raises(SnapshotError):
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=deadline()
        )
    assert env.signer.sign_calls == 0


@pytest.mark.parametrize(
    "field",
    [
        "mapping_policy_digest",
        "display_profile_digest",
        "cutoff_at",
        "witness_ref",
        "permitted_inputs",
    ],
)
def test_candidate_requires_exact_classified_scope(environment, field):
    env = environment
    _, ref = publish_classification(env)
    value = {
        "mapping_policy_digest": "0" * 64,
        "display_profile_digest": "0" * 64,
        "cutoff_at": env.source.scope.cutoff_at + timedelta(days=1),
        "witness_ref": env.command.review_ref,
        "permitted_inputs": (
            env.source.scope.permitted_inputs[0].model_copy(
                update={"value": Decimal(1)}
            ),
        ),
    }[field]
    wrong = env.source.scope.model_copy(update={field: value})
    with pytest.raises(SnapshotError):
        env.owner.require_candidate_source(wrong, (ref,), deadline_at=deadline())


def test_same_command_cannot_renew_or_change_review(environment):
    env = environment
    result, _ = publish_classification(env)
    modified = env.command.model_copy(
        update={"expires_at": env.command.expires_at + timedelta(seconds=1)}
    )
    with pytest.raises(SnapshotError) as failure:
        env.owner.record_classification(
            modified, expected_head=None, deadline_at=deadline()
        )
    assert failure.value.code == "FISCAL_CLASSIFICATION_COMMAND_REUSED"
    assert env.signer.sign_calls == 1
    assert env.store.read(result.publication.artifact.artifact_id) == canonical_bytes(
        result.signed_classification
    )


def test_current_source_revocation_and_read_do_not_publish(environment, monkeypatch):
    env = environment
    _, ref = publish_classification(env)

    def no_write(*args, **kwargs):
        raise AssertionError("current classification read must not publish or seal")

    monkeypatch.setattr(env.store, "put_bytes_with_receipt", no_write)
    monkeypatch.setattr(env.history, "checkpoint", no_write)
    monkeypatch.setattr(env.history, "append_once", no_write)
    monkeypatch.setattr(env.history, "seal_pending", no_write)
    env.owner.require_candidate_source(env.source.scope, (ref,), deadline_at=deadline())
    change_status(env, env.command.source_validation_ref.artifact_id, "invalidated")
    with pytest.raises(SnapshotError):
        env.owner.require_candidate_source(
            env.source.scope, (ref,), deadline_at=deadline()
        )


def test_orphan_retries_original_signature_and_execution(environment, monkeypatch):
    env = environment
    original = env.history.append_once
    monkeypatch.setattr(
        env.history,
        "append_once",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            RuntimeError("synthetic crash after immutable publication")
        ),
    )
    with pytest.raises(RuntimeError):
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=deadline()
        )
    record = env.store.get(env.command.artifact_id)
    raw = env.store.read(record.artifact_id)
    ref = reference(record, "fiscal-source-classification-v1")
    with pytest.raises(SnapshotError):
        env.owner.require_candidate_source(
            env.source.scope, (ref,), deadline_at=deadline()
        )
    monkeypatch.setattr(env.history, "append_once", original)
    retried = env.owner.record_classification(
        env.command, expected_head=None, deadline_at=deadline()
    )
    assert not retried.publication.wrote
    assert raw == env.store.read(record.artifact_id) and env.signer.sign_calls == 1


@pytest.mark.parametrize("operation", ["record", "read"])
def test_deadline_is_checked_after_final_history_head_check(
    environment, monkeypatch, operation
):
    env = environment
    result, ref = publish_classification(env)
    request_deadline = deadline()
    now = datetime.now(UTC)
    env.owner.clock = lambda: now
    original = env.history.require_heads

    def crossing(*args, **kwargs):
        nonlocal now
        original(*args, **kwargs)
        if any(
            head.subject_id.startswith("fiscal-classification:") for head in args[0]
        ):
            now = request_deadline

    monkeypatch.setattr(env.history, "require_heads", crossing)
    with pytest.raises(SnapshotError) as failure:
        if operation == "record":
            env.owner.record_classification(
                env.command, expected_head=None, deadline_at=request_deadline
            )
        else:
            env.owner.require_candidate_source(
                env.source.scope, (ref,), deadline_at=request_deadline
            )
    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
    assert env.store.read(ref.artifact_id) == canonical_bytes(
        result.signed_classification
    )


def test_signer_wrong_key_and_deadline_cannot_publish(environment):
    env = environment
    env.signer.key = Ed25519PrivateKey.generate()
    with pytest.raises(SnapshotError):
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=deadline()
        )
    with pytest.raises(SnapshotError) as failure:
        env.owner.record_classification(
            env.command, expected_head=None, deadline_at=datetime.now(UTC)
        )
    assert failure.value.code == "REQUEST_DEADLINE_EXCEEDED"
