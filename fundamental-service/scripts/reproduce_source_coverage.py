"""Reproduce fixed source observations; this script grants no runtime permissions."""

from __future__ import annotations

import argparse
import html
import platform
import re
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import replace
from datetime import date
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from typing import Literal
from zipfile import ZipFile

from lxml import etree
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, TypeAdapter

from fundamental_service.arelle_parser import (
    ArelleParseReportV1,
    ArelleValidationProfileV1,
    ParsedXbrlFactV1,
    _directory_hash,
    fact_semantic_digest,
    parse_filing_offline,
)
from fundamental_service.free_source_policy import (
    default_macro_providers,
    default_reference_providers,
)
from fundamental_service.parser_computation import parser_computation
from fundamental_service.public_acquisition import (
    PublicSourceAcquisition,
    PublicSourceAcquisitionEvidenceV1,
    PublicSourceAcquisitionRequestV1,
)
from fundamental_service.public_admission import (
    PublicSourceAdmission,
    PublicSourceAdmissionRequestV1,
)
from fundamental_service.public_source import PublicSourceAdapter
from fundamental_service.regulatory_validation import require_sec_validation_evidence
from fundamental_service.replay import ArtifactStore
from fundamental_service.serialization import canonical_bytes, sha256_digest
from fundamental_service.snapshots import FilesystemContentStore, SnapshotError
from fundamental_service.source_admission import admit_macro_source
from fundamental_service.source_use_deployment import load_runtime_source_use_policy

from verify_source_research_matrix import verify_matrix

REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_COHORT = (
    REPOSITORY
    / "fundamental-service/tests/fixtures/source-coverage/issue493-cohort.json"
)
TAXONOMY_SHA256 = "c4b12e9078bae2a14f1576c9a05a2679f13f824cb02feeac94cfff77e21d278e"
TAXONOMY_VERSION = "captured-us-gaap-2024-cache-v1"
PROFILE = ArelleValidationProfileV1(profile_id="source-coverage-offline-parse-only-v1")


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Citation(FrozenModel):
    locator: str
    quote: str


class SecCase(FrozenModel):
    case_id: str
    cik: str
    company: str
    security_id: str
    security_title: str
    accession_number: str
    form: str
    period_start: date
    period_end: date
    available_at: AwareDatetime
    is_amendment: bool
    amends_accession: str | None
    filing_path: str
    archive_path: str
    source_uri: str
    selection_evidence: tuple[Citation, ...]
    expected_checks: tuple[str, ...]
    actual_coverage: Literal["unknown"]


class PublicCase(FrozenModel):
    case_id: str
    source_id: str
    provider_id: str
    metric_id: str
    source_profile: str
    source_uri: str
    terms_source_id: str
    expected_checks: tuple[str, ...]
    actual_coverage: Literal["unknown"]


class Cohort(FrozenModel):
    protocol: Literal["source-coverage-engineering-cohort-v1"]
    issue: Literal[493]
    frozen_on: date
    scope: str
    source_manifest: str
    actual_coverage: Literal["unknown"]
    supported_history_threshold: None
    cases: tuple[SecCase, ...]
    public_source_case: PublicCase


class CaptureEntry(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    path: str
    sha256: str
    bytes: int
    accession_number: str | None
    form: str | None
    is_amendment: bool
    amends_accession: str | None
    amendment_scope: str | None
    available_at: AwareDatetime
    uri: str
    report_period_end: date | None = None


class CaptureManifest(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True)
    sources: tuple[CaptureEntry, ...]


class ParserEvidence(FrozenModel):
    dependencies: tuple[str, ...]
    runtime_identity: dict[str, str]
    computation_digest: str
    fact_digest: str
    report: ArelleParseReportV1


class OriginalInventory(FrozenModel):
    inline_qnames: tuple[str, ...]
    declared_namespaces: dict[str | None, str]
    schema_resource_urls: tuple[str, ...]
    identity_texts: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    boundary: str = "Original QName presence only; no value parsing, mapping or source-use approval."


def runtime_identity() -> dict[str, str]:
    return {
        "python": platform.python_version(),
        "pydantic": version("pydantic"),
        "arelle-release": version("arelle-release"),
    }


def checked_path(root: Path, relative: str) -> Path:
    target = (root / relative).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError("evidence path escapes its source root")
    return target


def extract_resources(
    archive: Path, destination: Path, *, filing_name: str | None = None
) -> None:
    with ZipFile(archive) as source:
        for member in source.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in member.filename:
                raise ValueError("unsafe archive member")
            if member.is_dir():
                continue
            if (
                filing_name is not None
                and name.name != filing_name
                and name.suffix not in {".xsd", ".xml"}
            ):
                continue
            target = checked_path(destination, member.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read(member))


def verified_source(
    case: SecCase, entry: CaptureEntry, root: Path, *, filing: bool
) -> Path:
    path = checked_path(root, entry.path)
    raw = path.read_bytes()
    if sha256(raw).hexdigest() != entry.sha256 or len(raw) != entry.bytes:
        raise ValueError(f"source integrity failed: {entry.path}")
    if (
        entry.accession_number != case.accession_number
        or entry.form != case.form
        or entry.is_amendment != case.is_amendment
        or entry.amends_accession != case.amends_accession
        or entry.available_at != case.available_at
        or f"/edgar/data/{int(case.cik)}/" not in entry.uri
        or (
            filing
            and (
                entry.uri != case.source_uri
                or entry.report_period_end != case.period_end
            )
        )
    ):
        raise ValueError(f"source identity differs from frozen cohort: {case.case_id}")
    return path


def load_parser_evidence(
    artifacts: ArtifactStore,
    artifact_id: str,
    dependencies: tuple[str, ...],
    *,
    source_hash: str,
    taxonomy_hash: str,
) -> ArelleParseReportV1 | None:
    try:
        record = artifacts.get(artifact_id)
    except SnapshotError as error:
        if error.code == "ARTIFACT_NOT_FOUND":
            return None
        raise
    evidence = ParserEvidence.model_validate_json(artifacts.read(artifact_id))
    report = evidence.report
    if (
        record.status != "valid"
        or record.retention != "evidence"
        or record.media_type != "application/json"
        or record.dependency_hashes != dependencies
        or evidence.dependencies != dependencies
        or evidence.runtime_identity != runtime_identity()
        or report.validation_profile != PROFILE
        or report.validation_profile_digest != PROFILE.digest()
        or report.parser_version != version("arelle-release")
        or report.taxonomy_version != TAXONOMY_VERSION
        or report.taxonomy_cache_hash != taxonomy_hash
        or report.source_content_hash != source_hash
        or not report.offline
        or report.network_attempt_count != 0
        or evidence.fact_digest != fact_semantic_digest(report)
        or evidence.computation_digest
        != parser_computation(report, sha256_digest(dependencies)).report_digest
    ):
        raise ValueError("retained parser report or its dependencies changed")
    return report


def _text(raw: bytes) -> str:
    text = " ".join(html.unescape(re.sub(r"<[^>]*>", " ", raw.decode("utf-8"))).split())
    return re.sub(r"\s+([,.;:])", r"\1", text)


def original_inventory(raw: bytes, archive: Path) -> OriginalInventory:
    parser = etree.XMLParser(
        recover=True, resolve_entities=False, load_dtd=False, no_network=True
    )
    document = etree.fromstring(raw, parser)
    names = tuple(
        sorted(
            {
                element.get("name")
                for element in document.iter()
                if isinstance(element.tag, str)
                and element.tag.startswith(
                    (
                        "{http://www.xbrl.org/2013/inlineXBRL}",
                        "{http://www.xbrl.org/2008/inlineXBRL}",
                    )
                )
                and element.get("name")
            }
        )
    )
    resources: set[str] = set()
    with ZipFile(archive) as zipped:
        for name in zipped.namelist():
            if name.endswith(".xsd"):
                schema = etree.fromstring(zipped.read(name), parser)
                resources.update(
                    element.get("schemaLocation")
                    for element in schema.iter()
                    if element.get("schemaLocation")
                )
    return OriginalInventory(
        inline_qnames=names,
        declared_namespaces=document.nsmap,
        schema_resource_urls=tuple(sorted(resources)),
        identity_texts={
            concept: tuple(
                "".join(element.itertext()).strip()
                for element in document.iter()
                if element.get("name")
                and element.get("name").split(":")[-1] == concept
                and re.fullmatch(
                    r"https?://xbrl\.sec\.gov/dei/[0-9]{4}",
                    document.nsmap.get(element.get("name").partition(":")[0], ""),
                )
            )
            for concept in (
                "EntityCentralIndexKey",
                "EntityRegistrantName",
                "Security12bTitle",
                "TradingSymbol",
            )
        },
    )


def standard_observation(concept: str, namespace: str | None) -> bool:
    family = (
        "xbrl.sec.gov/dei"
        if concept == "EntityCommonStockSharesOutstanding"
        else "fasb.org/us-gaap"
    )
    return (
        namespace is not None
        and re.fullmatch(rf"https?://{re.escape(family)}/[0-9]{{4}}", namespace)
        is not None
    )


def observe_sec(
    case: SecCase,
    report: ArelleParseReportV1,
    filing: CaptureEntry,
    original: OriginalInventory,
) -> dict[str, object]:
    try:
        require_sec_validation_evidence(report)
    except SnapshotError as error:
        refusal = error.code
    else:
        raise ValueError("parse-only report unexpectedly qualified for SEC validation")
    groups: dict[str, tuple[str, ...]] = {
        "balance_sheet": ("Assets",),
        "income_statement": ("NetIncomeLoss",),
        "operating_cash_flow": ("NetCashProvidedByUsedInOperatingActivities",),
        "shares": (
            "EntityCommonStockSharesOutstanding",
            "CommonStockSharesOutstanding",
        ),
        "sbc": ("ShareBasedCompensation",),
        "claims": (
            "LongTermDebtCurrent",
            "LongTermDebtNoncurrent",
            "OperatingLeaseLiabilityNoncurrent",
        ),
    }
    observed: dict[str, tuple[ParsedXbrlFactV1, ...]] = {}
    queries: dict[str, object] = {}
    for role, concepts in groups.items():
        facts = tuple(
            fact
            for fact in report.facts
            if fact.concept.split(":")[-1] in concepts
            and standard_observation(fact.concept.split(":")[-1], fact.namespace_uri)
        )
        observed[role] = tuple(
            sorted(
                facts,
                key=lambda fact: (
                    fact.period_end != case.period_end
                    and fact.instant != case.period_end,
                    bool(fact.dimensions),
                    sha256_digest(fact),
                ),
            )[:3]
        )
        names = tuple(
            name
            for name in original.inline_qnames
            if name.split(":")[-1] in concepts
            and standard_observation(
                name.split(":")[-1],
                original.declared_namespaces.get(name.partition(":")[0]),
            )
        )
        queries[role] = {
            "original_qnames": names,
            "disposition": "observed_by_parser"
            if observed[role]
            else "present_in_original_but_not_parsed"
            if names
            else "queried_qnames_absent_from_original",
        }
    observed["segments"] = tuple(
        sorted(
            (
                fact
                for fact in report.facts
                if any(
                    axis.split(":")[-1]
                    in {
                        "ProductOrServiceAxis",
                        "StatementGeographicalAxis",
                        "StatementBusinessSegmentsAxis",
                    }
                    for axis, _ in fact.dimensions
                )
            ),
            key=sha256_digest,
        )[:5]
    )
    periods = sorted(
        {
            (fact.period_start, fact.period_end)
            for fact in report.facts
            if fact.period_start is not None and fact.period_end is not None
        }
    )
    durations = tuple(
        {"start": start, "end": end, "inclusive_days": (end - start).days + 1}
        for start, end in periods
        if start is not None and end is not None
    )
    if case.case_id == "aapl-fy2024-original" and not {
        (date(2023, 10, 1), date(2024, 9, 28)),
        (date(2022, 9, 25), date(2023, 9, 30)),
    } <= set(periods):
        raise ValueError("Apple 52/53-week original contexts were not preserved")
    if case.is_amendment and (
        filing.amendment_scope != "unknown" or observed["operating_cash_flow"]
    ):
        raise ValueError(
            "amendment missing-source check differs from frozen expectation"
        )
    return {
        "case_id": case.case_id,
        "accession_number": case.accession_number,
        "source_sha256": filing.sha256,
        "archive_integrity_admission": "not_established_by_parse_only",
        "availability": "retained_original_verified",
        "parsing": (
            "unsupported"
            if not report.facts
            else "partial"
            if report.blocking_finding_codes()
            or any(
                not observed[role]
                for role in ("balance_sheet", "income_statement", "operating_cash_flow")
            )
            else "parsed"
        ),
        "semantic_comparability": "not_established",
        "source_use": "not_evaluated_by_sec_parser",
        "calculation_qualification": refusal,
        "amendment_scope": filing.amendment_scope,
        "amends_accession": filing.amends_accession,
        "fact_digest": fact_semantic_digest(report),
        "fact_count": len(report.facts),
        "finding_codes": report.finding_codes,
        "blocking_finding_codes": report.blocking_finding_codes(),
        "namespace_inventory": tuple(
            sorted({fact.namespace_uri for fact in report.facts if fact.namespace_uri})
        ),
        "custom_qnames": tuple(
            sorted(
                {
                    fact.concept
                    for fact in report.facts
                    if fact.namespace_uri
                    and (
                        "apple.com" in fact.namespace_uri
                        or "tesla.com" in fact.namespace_uri
                    )
                }
            )
        ),
        "observations": observed,
        "original_queries": queries,
        "missing_observation_roles": tuple(
            role for role, facts in observed.items() if not facts
        ),
        "duration_contexts": durations,
        "limitations": (
            "Observation absence applies only to this retained original and queried concepts.",
            "Extension presence is not an approved accounting mapping.",
            "No complete three-statement, claims inventory or calculation approval is established.",
        ),
    }


def reproduce_sec(
    cohort: Cohort, evidence_dir: Path, *, repository: Path = REPOSITORY
) -> tuple[dict[str, object], ...]:
    manifest_path = checked_path(repository, cohort.source_manifest)
    manifest = CaptureManifest.model_validate_json(manifest_path.read_bytes())
    entries = {entry.path: entry for entry in manifest.sources}
    source_root = manifest_path.parent
    taxonomy_zip = source_root / "arelle-taxonomy-cache-2024.zip"
    if sha256(taxonomy_zip.read_bytes()).hexdigest() != TAXONOMY_SHA256:
        raise ValueError("pinned offline taxonomy bundle changed")
    artifacts = ArtifactStore(evidence_dir / "artifacts")
    completion_id = "source-coverage-sec-completed"
    try:
        completed = TypeAdapter(dict[str, str]).validate_json(
            artifacts.read(completion_id)
        )
    except SnapshotError as error:
        if error.code != "ARTIFACT_NOT_FOUND":
            raise
        completed = None
    report_hashes: dict[str, str] = {}
    results = []
    with TemporaryDirectory(prefix="source-coverage-") as temporary:
        scratch = Path(temporary)
        taxonomy = scratch / "taxonomy"
        extract_resources(taxonomy_zip, taxonomy)
        taxonomy_hash = _directory_hash(taxonomy)
        for case in cohort.cases:
            filing_entry, archive_entry = (
                entries[case.filing_path],
                entries[case.archive_path],
            )
            filing = verified_source(case, filing_entry, source_root, filing=True)
            archive = verified_source(case, archive_entry, source_root, filing=False)
            original_text = _text(filing.read_bytes())
            for citation in case.selection_evidence:
                if " ".join(citation.quote.split()) not in original_text:
                    raise ValueError(
                        f"source quotation absent: {case.case_id}: {citation.locator}"
                    )
            dependencies = tuple(
                sorted(
                    {
                        sha256_digest(cohort),
                        sha256(manifest_path.read_bytes()).hexdigest(),
                        filing_entry.sha256,
                        archive_entry.sha256,
                        TAXONOMY_SHA256,
                        taxonomy_hash,
                        PROFILE.digest(),
                        sha256_digest(runtime_identity()),
                    }
                )
            )
            artifact_id = f"source-coverage-parser:{case.case_id}"
            report = load_parser_evidence(
                artifacts,
                artifact_id,
                dependencies,
                source_hash=filing_entry.sha256,
                taxonomy_hash=taxonomy_hash,
            )
            if report is None:
                if completed is not None:
                    raise ValueError(
                        "completed coverage is missing a retained parser report"
                    )
                target = scratch / case.case_id
                filename = PurePosixPath(case.source_uri).name
                extract_resources(archive, target, filing_name=filename)
                entrypoint = target / filename
                entrypoint.write_bytes(filing.read_bytes())
                report = parse_filing_offline(
                    entrypoint,
                    profile=PROFILE,
                    taxonomy_version=TAXONOMY_VERSION,
                    taxonomy_cache_dir=taxonomy,
                    source_content_hash=filing_entry.sha256,
                )
                evidence = ParserEvidence(
                    dependencies=dependencies,
                    runtime_identity=runtime_identity(),
                    computation_digest=parser_computation(
                        report, sha256_digest(dependencies)
                    ).report_digest,
                    fact_digest=fact_semantic_digest(report),
                    report=report,
                )
                artifacts.put(artifact_id, evidence, dependencies)
                report = load_parser_evidence(
                    artifacts,
                    artifact_id,
                    dependencies,
                    source_hash=filing_entry.sha256,
                    taxonomy_hash=taxonomy_hash,
                )
                assert report is not None
            report_hashes[artifact_id] = artifacts.get(artifact_id).content_hash
            inventory = original_inventory(filing.read_bytes(), archive)
            if not (
                any(
                    int(value) == int(case.cik)
                    for value in inventory.identity_texts["EntityCentralIndexKey"]
                )
                and any(
                    " ".join(value.split()) == case.company
                    for value in inventory.identity_texts["EntityRegistrantName"]
                )
                and case.security_id in inventory.identity_texts["TradingSymbol"]
                and any(
                    case.security_title.lower() in value.lower()
                    for value in inventory.identity_texts["Security12bTitle"]
                )
            ):
                raise ValueError("original DEI identity differs from frozen cohort")
            observation = observe_sec(case, report, filing_entry, inventory)
            observation["parser_artifact_id"] = artifact_id
            observation["parser_artifact_sha256"] = report_hashes[artifact_id]
            observation["original_inventory"] = inventory
            observation["archive_sha256"] = archive_entry.sha256
            observation["taxonomy_bundle_sha256"] = TAXONOMY_SHA256
            observation["taxonomy_cache_hash"] = report.taxonomy_cache_hash
            results.append(observation)
    if completed is not None and completed != report_hashes:
        raise ValueError("completed coverage report identities changed")
    artifacts.put(completion_id, report_hashes, tuple(sorted(report_hashes.values())))
    return tuple(results)


def reproduce_public(
    case: PublicCase,
    evidence_dir: Path,
    *,
    capture_public: bool = False,
    user_agent: str | None = None,
) -> dict[str, object]:
    if capture_public and not user_agent:
        raise ValueError("--capture-public requires --user-agent with contact")
    adapter = PublicSourceAdapter(
        user_agent=user_agent or "Offline source verification <offline@example.invalid>"
    )
    artifacts = ArtifactStore(evidence_dir / "artifacts")
    acquisitions = PublicSourceAcquisition(
        provider=adapter,
        artifacts=artifacts,
        content=FilesystemContentStore(evidence_dir / "content"),
        capture_lock=lambda _: nullcontext(),
    )
    requests_path = evidence_dir / "requests.json"
    requests = TypeAdapter(tuple[PublicSourceAcquisitionRequestV1, ...]).validate_json(
        requests_path.read_bytes()
    )
    sources = tuple(
        request for request in requests if request.source_id == case.source_id
    )
    terms = tuple(
        request for request in requests if request.source_id == case.terms_source_id
    )
    if (
        len(requests) != 2
        or len(sources) != 1
        or len(terms) != 1
        or sources[0].source_profile != case.source_profile
        or sources[0].uri != case.source_uri
    ):
        raise ValueError("retained public requests differ from the frozen source case")
    captures: list[PublicSourceAcquisitionEvidenceV1] = []
    for request in requests:
        acquisitions.validate_request(request)
        artifact_id = f"public-source-acquisition:{request.digest}"
        if not capture_public:
            acquisitions.read(artifact_id)
        publication = acquisitions.execute(request)
        if not capture_public and publication.wrote:
            raise ValueError("offline replay wrote a new source acquisition")
        captures.append(acquisitions.read(publication.artifact.artifact_id))
    policy = load_runtime_source_use_policy()
    admission_owner = PublicSourceAdmission(
        acquisitions=acquisitions,
        artifacts=artifacts,
        policy=policy,
        macro_providers=default_macro_providers(),
        reference_providers=default_reference_providers(),
    )
    cutoff = max(
        *(request.valuation_timestamp for request in requests),
        *(item.available_at for item in captures if item.available_at is not None),
    )
    base = PublicSourceAdmissionRequestV1(
        kind="macro",
        provider_id=case.provider_id,
        metric_id=case.metric_id,
        valuation_at=cutoff,
        policy_version=policy.policy_version,
        policy_digest=policy.digest,
        source_request_digests=(sources[0].digest,),
        terms_request_digests=(terms[0].digest,),
    )
    cases = {
        "normal_preparation": base,
        "raw_data_redistribution": base.model_copy(
            update={"intended_use": "raw_data_redistribution"}
        ),
        "missing_terms": base.model_copy(update={"terms_request_digests": ()}),
        "wrong_policy_digest": base.model_copy(update={"policy_digest": "0" * 64}),
        "earlier_cutoff": base.model_copy(
            update={
                "valuation_at": max(request.valuation_timestamp for request in requests)
            }
        ),
    }
    outputs: dict[str, object] = {}
    for name, admission_request in cases.items():
        result, _ = admission_owner.execute(admission_request, tuple(captures))
        outputs[name] = result
    original = acquisitions.retained_source(
        next(item for item in captures if item.request.source_id == case.source_id)
    )
    retained_terms = acquisitions.retained_source(
        next(
            item for item in captures if item.request.source_id == case.terms_source_id
        )
    )
    provider = next(
        item
        for item in default_macro_providers()
        if item.provider_id == case.provider_id and item.supports(case.metric_id)
    )
    outputs["changed_terms_mutation_check"] = admit_macro_source(
        provider,
        series_id=case.metric_id,
        sources=(original,),
        terms=(
            replace(
                retained_terms, content=retained_terms.content + b"\nmutation-check"
            ),
        ),
        policy=policy,
        valuation_at=cutoff,
        intended_use="valuation_preparation",
    )
    outputs["no_policy_rule_mutation_check"] = admit_macro_source(
        provider,
        series_id=case.metric_id,
        sources=(original,),
        terms=(retained_terms,),
        policy=policy.model_copy(update={"rules": ()}),
        valuation_at=cutoff,
        intended_use="valuation_preparation",
    )
    return {
        "case_id": case.case_id,
        "policy_version": policy.policy_version,
        "policy_digest": policy.digest,
        "valuation_at": cutoff,
        "captures": tuple(captures),
        "cases": outputs,
        "mutation_boundary": "Changed terms and absent-rule cases use copied inputs; they do not describe fabricated real captures.",
    }


def reproduce(
    cohort_path: Path,
    evidence_dir: Path,
    *,
    capture_public: bool = False,
    user_agent: str | None = None,
    matrix_path: Path | None = None,
) -> dict[str, object]:
    cohort = Cohort.model_validate_json(cohort_path.read_bytes())
    if not (evidence_dir / "requests.json").is_file():
        raise ValueError(
            "retained requests.json is required; offline replay never downloads"
        )
    result: dict[str, object] = {
        "protocol": "source-coverage-observations-v1",
        "cohort_sha256": sha256(cohort_path.read_bytes()).hexdigest(),
        "runtime_identity": runtime_identity(),
        "supported_history_threshold": None,
        "sec": reproduce_sec(cohort, evidence_dir),
        "public": reproduce_public(
            cohort.public_source_case,
            evidence_dir,
            capture_public=capture_public,
            user_agent=user_agent,
        ),
    }
    if matrix_path is not None:
        acquisitions = PublicSourceAcquisition(
            provider=PublicSourceAdapter(
                user_agent="Offline matrix verifier <offline@example.invalid>"
            ),
            artifacts=ArtifactStore(evidence_dir / "artifacts"),
            content=FilesystemContentStore(evidence_dir / "content"),
            capture_lock=lambda _: nullcontext(),
        )
        result["matrix"] = verify_matrix(matrix_path, evidence_dir, acquisitions)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort", type=Path, default=DEFAULT_COHORT)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--capture-public", action="store_true")
    parser.add_argument("--user-agent")
    parser.add_argument("--matrix", type=Path)
    args = parser.parse_args(argv)
    if args.output.resolve().is_relative_to(args.evidence_dir.resolve()):
        parser.error("--output must be outside immutable evidence storage")
    try:
        result = reproduce(
            args.cohort,
            args.evidence_dir,
            capture_public=args.capture_public,
            user_agent=args.user_agent,
            matrix_path=args.matrix,
        )
    except (OSError, ValueError, SnapshotError) as error:
        parser.exit(1, f"source coverage failed: {error}\n")
    args.output.write_bytes(canonical_bytes(result) + b"\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
