"""Immutable provenance artifacts, cache lifecycle, and offline replay."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from threading import Condition, RLock
from time import monotonic
from typing import Any, Callable, Literal

import fcntl

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .calculator import CalculationRefusal, calculate
from .contracts import CalculationArtifactV1, ReleaseManifestV1, ValuationInputV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError
from .snapshots import SnapshotRepository

SERVICE_VERSION = "0.1.0"


class ProvenanceEdgeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    relation: Literal["derived_from", "selected_from", "resolved_from", "calculated_by"]
    expression: str | None = None
    input_ids: tuple[str, ...] = ()
    code_version: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    quality_status: str = Field(min_length=1)


class ProvenanceNodeV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    node_id: str = Field(min_length=1)
    node_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    quality_status: str = Field(min_length=1)
    observed_at: datetime


class ProvenanceGraphV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    graph_id: str = Field(min_length=1)
    nodes: tuple[ProvenanceNodeV1, ...] = ()
    edges: tuple[ProvenanceEdgeV1, ...] = ()
    graph_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_graph(self) -> "ProvenanceGraphV1":
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("provenance graph contains duplicate node IDs")
        declared = set(node_ids)
        adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for edge in self.edges:
            if edge.source_id not in declared or edge.target_id not in declared:
                raise ValueError("provenance edge references an undeclared node")
            if any(input_id not in declared for input_id in edge.input_ids):
                raise ValueError("provenance edge input references an undeclared node")
            adjacency[edge.source_id].add(edge.target_id)
        visited: set[str] = set()
        active: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in active:
                raise ValueError("provenance graph must be acyclic")
            if node_id in visited:
                return
            active.add(node_id)
            for child in adjacency[node_id]:
                visit(child)
            active.remove(node_id)
            visited.add(node_id)

        for node_id in node_ids:
            visit(node_id)
        expected_digest = sha256_digest(self.model_dump(exclude={"graph_digest"}))
        if self.graph_digest != expected_digest:
            raise ValueError("graph_digest does not match graph contents")
        return self


class DependencyManifestV1(BaseModel):
    """Pinned dependencies required to explain a replay result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    runtime_version: str = Field(min_length=1)
    parser_version: str = Field(min_length=1)
    taxonomy_version: str = Field(min_length=1)
    model_version: str = Field(min_length=1)
    policy_version: str | None = None
    calculation_version: str = Field(min_length=1)
    source_content_hashes: tuple[str, ...] = ()


class ReplayReportV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    status: Literal["match", "mismatch", "abstain"]
    expected_result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    actual_result_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    expected_input_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    actual_input_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    first_difference: str | None = None
    changed_dependency: str | None = None
    dependency_versions: dict[str, str] = Field(default_factory=dict)
    offline: bool = True


class ReplayEnvelopeV1(BaseModel):
    """The complete caller-supplied offline replay input."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest: ReleaseManifestV1
    request: ValuationInputV1
    expected: CalculationArtifactV1


class ArtifactRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str = Field(min_length=1)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    dependency_hashes: tuple[str, ...] = ()
    media_type: str = Field(default="application/json", min_length=1)
    status: Literal["valid", "stale", "invalidated"] = "valid"
    retention: Literal["evidence", "operational_cache"] = "evidence"

    @field_validator("dependency_hashes", mode="before")
    @classmethod
    def validate_hashes(cls, value: object) -> tuple[str, ...]:
        values = tuple(value or ())
        if any(
            len(item) != 64 or any(char not in "0123456789abcdef" for char in item)
            for item in values
        ):
            raise ValueError("dependency_hashes must contain SHA-256 digests")
        return tuple(sorted(set(values)))


class ArtifactStore:
    """Content-addressed immutable artifacts with append-only record history."""

    _record_log_name = ".artifact-records.jsonl"
    _record_lock_name = ".artifact-records.lock"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._record_log = self.root / self._record_log_name
        self._record_lock = self.root / self._record_lock_name
        self._records: dict[str, ArtifactRecordV1] = {}
        self._loaded = False
        self._lock = RLock()
        self._load_records()

    @contextmanager
    def _exclusive_record_lock(self):
        with self._record_lock.open("a+b") as lock_handle:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _read_records_unlocked(self) -> None:
        self._records.clear()
        if not self._record_log.exists():
            self._loaded = True
            return
        lines = self._record_log.read_text(encoding="utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            try:
                record = ArtifactRecordV1.model_validate_json(line)
            except ValueError:
                if line == lines[-1]:
                    break
                raise SnapshotError(
                    "ARTIFACT_RECORD_CORRUPT", "artifact record history is corrupt"
                )
            self._records[record.artifact_id] = record
        self._loaded = True

    def _load_records(self, *, force: bool = False) -> None:
        with self._lock:
            if self._loaded and not force:
                return
            with self._record_lock.open("a+b") as lock_handle:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_SH)
                try:
                    self._read_records_unlocked()
                finally:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)

    def _repair_partial_tail_unlocked(self) -> None:
        if not self._record_log.exists():
            return
        data = self._record_log.read_bytes()
        offset = 0
        for frame in data.splitlines(keepends=True):
            try:
                ArtifactRecordV1.model_validate_json(frame.strip())
            except ValueError:
                with self._record_log.open("r+b") as handle:
                    handle.truncate(offset)
                return
            offset += len(frame)

    def _append_record_unlocked(self, record: ArtifactRecordV1) -> None:
        with self._record_log.open("ab") as handle:
            handle.write(canonical_bytes(record) + b"\n")
            handle.flush()
            os.fsync(handle.fileno())

    def _artifact_path(self, content_hash: str, media_type: str) -> Path:
        media_key = hashlib.sha256(media_type.encode("utf-8")).hexdigest()[:16]
        return self.root / f"{content_hash}.{media_key}.artifact"

    def put(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactRecordV1:
        if not artifact_id:
            raise SnapshotError("ARTIFACT_ID_INVALID", "artifact_id is required")
        payload = canonical_bytes(value)
        content_hash = hashlib.sha256(payload).hexdigest()
        path = self._artifact_path(content_hash, media_type)
        with self._lock:
            with self._exclusive_record_lock():
                self._repair_partial_tail_unlocked()
                self._read_records_unlocked()
                if path.exists() and path.read_bytes() != payload:
                    raise SnapshotError(
                        "ARTIFACT_HASH_MISMATCH",
                        "content-addressed artifact bytes changed",
                    )
                if not path.exists():
                    fd, temporary_name = tempfile.mkstemp(
                        prefix="artifact-", dir=self.root
                    )
                    try:
                        with os.fdopen(fd, "wb") as handle:
                            handle.write(payload)
                            handle.flush()
                            os.fsync(handle.fileno())
                        os.replace(temporary_name, path)
                    finally:
                        if os.path.exists(temporary_name):
                            os.unlink(temporary_name)
                previous = self._records.get(artifact_id)
                if previous is not None:
                    if (
                        previous.status != "valid"
                        or previous.content_hash != content_hash
                    ):
                        raise SnapshotError(
                            "ARTIFACT_ID_REUSED",
                            "artifact IDs are immutable; publish a new generation",
                        )
                    return previous
                record = ArtifactRecordV1(
                    artifact_id=artifact_id,
                    content_hash=content_hash,
                    dependency_hashes=dependency_hashes,
                    media_type=media_type,
                    retention=retention,
                )
                self._append_record_unlocked(record)
                self._records[artifact_id] = record
                return record

    def get(self, artifact_id: str) -> ArtifactRecordV1:
        with self._lock:
            self._load_records(force=True)
            try:
                return self._records[artifact_id]
            except KeyError as exc:
                raise SnapshotError(
                    "ARTIFACT_NOT_FOUND", f"artifact {artifact_id} is unavailable"
                ) from exc

    def read(self, artifact_id: str) -> bytes:
        record = self.get(artifact_id)
        path = self._artifact_path(record.content_hash, record.media_type)
        try:
            payload = path.read_bytes()
        except FileNotFoundError as exc:
            raise SnapshotError(
                "ARTIFACT_BYTES_UNAVAILABLE",
                f"artifact {artifact_id} bytes are unavailable",
            ) from exc
        if hashlib.sha256(payload).hexdigest() != record.content_hash:
            raise SnapshotError(
                "ARTIFACT_HASH_MISMATCH", f"artifact {artifact_id} failed verification"
            )
        return payload

    def has_content_hash(self, content_hash: str) -> bool:
        if len(content_hash) != 64:
            return False
        with self._lock:
            self._load_records(force=True)
            valid_records = {
                record.content_hash
                for record in self._records.values()
                if record.status == "valid"
            }
        if content_hash not in valid_records:
            return False
        for path in self.root.glob(f"{content_hash}.*.artifact"):
            try:
                payload = path.read_bytes()
            except OSError:
                continue
            if hashlib.sha256(payload).hexdigest() == content_hash:
                return True
        return False

    def invalidate_dependency(self, dependency_hash: str) -> tuple[str, ...]:
        invalidated: list[str] = []
        with self._lock:
            with self._exclusive_record_lock():
                self._repair_partial_tail_unlocked()
                self._read_records_unlocked()
                for artifact_id, record in tuple(self._records.items()):
                    if (
                        dependency_hash in record.dependency_hashes
                        and record.status == "valid"
                    ):
                        stale = record.model_copy(update={"status": "stale"})
                        self._append_record_unlocked(stale)
                        self._records[artifact_id] = stale
                        invalidated.append(artifact_id)
        return tuple(invalidated)

    def invalidate(self, artifact_id: str) -> ArtifactRecordV1:
        with self._lock:
            with self._exclusive_record_lock():
                self._repair_partial_tail_unlocked()
                self._read_records_unlocked()
                try:
                    record = self._records[artifact_id]
                except KeyError as exc:
                    raise SnapshotError(
                        "ARTIFACT_NOT_FOUND", f"artifact {artifact_id} is unavailable"
                    ) from exc
                if record.status == "invalidated":
                    return record
                invalidated = record.model_copy(update={"status": "invalidated"})
                self._append_record_unlocked(invalidated)
                self._records[artifact_id] = invalidated
                return invalidated

    def rebuild(
        self,
        artifact_id: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        media_type: str = "application/json",
        retention: Literal["evidence", "operational_cache"] = "evidence",
    ) -> ArtifactRecordV1:
        """Publish a new generation while preserving the prior artifact ID."""
        content_hash = hashlib.sha256(canonical_bytes(value)).hexdigest()
        generation_id = f"{artifact_id}@{content_hash[:16]}"
        return self.put(
            generation_id,
            value,
            dependency_hashes,
            media_type=media_type,
            retention=retention,
        )

    def prune_expired(self) -> tuple[str, ...]:
        """Remove only invalidated operational-cache bytes; evidence is retained."""
        removed: list[str] = []
        with self._lock:
            with self._exclusive_record_lock():
                self._repair_partial_tail_unlocked()
                self._read_records_unlocked()
                for artifact_id, record in self._records.items():
                    if (
                        record.retention != "operational_cache"
                        or record.status == "valid"
                    ):
                        continue
                    protected = any(
                        other.artifact_id != artifact_id
                        and other.content_hash == record.content_hash
                        and other.retention == "evidence"
                        for other in self._records.values()
                    )
                    if protected:
                        continue
                    path = self._artifact_path(record.content_hash, record.media_type)
                    path.unlink(missing_ok=True)
                    removed.append(artifact_id)
        return tuple(removed)

    def reset_operational_cache(self) -> None:
        """Drop lookup state only; persisted artifact bytes and records remain."""
        with self._lock:
            self._records.clear()
            self._loaded = False


@dataclass
class _CacheEntry:
    value: object
    dependency_hashes: tuple[str, ...]
    status: Literal["valid", "stale"] = "valid"
    retained: bool = False
    expires_at: float | None = None


class CacheLifecycle:
    """An expiring operational cache; it never owns release evidence."""

    def __init__(self) -> None:
        self._values: dict[str, _CacheEntry] = {}
        self._building: dict[str, Condition] = {}
        self._lock = RLock()

    def get(self, key: str) -> tuple[Literal["hit", "miss", "stale"], object | None]:
        with self._lock:
            entry = self._values.get(key)
            if entry is None:
                return "miss", None
            if entry.expires_at is not None and monotonic() >= entry.expires_at:
                entry.status = "stale"
            if entry.status == "stale":
                return "stale", None
            return "hit", entry.value

    def put(
        self,
        key: str,
        value: object,
        dependency_hashes: tuple[str, ...] = (),
        *,
        retained: bool = False,
        ttl_seconds: float | None = None,
    ) -> None:
        if ttl_seconds is not None and ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        with self._lock:
            self._values[key] = _CacheEntry(
                value,
                dependency_hashes,
                retained=retained,
                expires_at=None
                if retained or ttl_seconds is None
                else monotonic() + ttl_seconds,
            )

    def invalidate(self, key: str) -> None:
        with self._lock:
            entry = self._values.get(key)
            if entry is not None:
                entry.status = "stale"

    def invalidate_dependency(self, dependency_hash: str) -> tuple[str, ...]:
        invalidated: list[str] = []
        with self._lock:
            for key, entry in self._values.items():
                if (
                    dependency_hash in entry.dependency_hashes
                    and entry.status == "valid"
                ):
                    entry.status = "stale"
                    invalidated.append(key)
        return tuple(invalidated)

    def rebuild(
        self,
        key: str,
        factory: Callable[[], object],
        dependency_hashes: tuple[str, ...] = (),
        *,
        ttl_seconds: float | None = None,
    ) -> object:
        """Populate a missing key once when concurrent callers arrive together."""
        with self._lock:
            status, value = self.get(key)
            if status == "hit":
                return value
            condition = self._building.get(key)
            if condition is None:
                condition = Condition(self._lock)
                self._building[key] = condition
                owner = True
            else:
                owner = False
            if not owner:
                while key in self._building:
                    condition.wait()
                status, value = self.get(key)
                if status == "hit":
                    return value
                condition = Condition(self._lock)
                self._building[key] = condition
        try:
            rebuilt = factory()
            self.put(key, rebuilt, dependency_hashes, ttl_seconds=ttl_seconds)
            return rebuilt
        finally:
            with self._lock:
                current = self._building.pop(key, None)
                if current is not None:
                    current.notify_all()

    def reset(self) -> None:
        with self._lock:
            self._values.clear()


def build_release_manifest(
    *,
    release_id: str,
    service_version: str,
    snapshot_ids: tuple[str, ...],
    input_hashes: tuple[str, ...],
    artifact_hashes: tuple[str, ...],
    artifact_ids: tuple[str, ...] = (),
    dependencies: DependencyManifestV1,
    quality_policy_version: str,
    decision_timestamp: Any | None = None,
    issuer_id: str | None = None,
    security_id: str | None = None,
    canonical_fact_ids: tuple[str, ...] = (),
    assumption_ids: tuple[str, ...] = (),
    calibration_artifact_ids: tuple[str, ...] = (),
    random_seed: int | None = None,
    numerical_settings: dict[str, str] | None = None,
    quality_issue_codes: tuple[str, ...] = (),
    release_profile_thresholds: dict[str, str] | None = None,
) -> ReleaseManifestV1:
    def sorted_hashes(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    def sorted_ids(values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(sorted(set(values)))

    payload: dict[str, Any] = {
        "contract_version": "fundamental.v1",
        "release_id": release_id,
        "schema_version": "fundamental.v1",
        "service_version": service_version,
        "decision_timestamp": decision_timestamp,
        "issuer_id": issuer_id,
        "security_id": security_id,
        "snapshot_ids": sorted_ids(snapshot_ids),
        "input_hashes": sorted_hashes(input_hashes),
        "canonical_fact_ids": sorted_ids(canonical_fact_ids),
        "assumption_ids": sorted_ids(assumption_ids),
        "calibration_artifact_ids": sorted_ids(calibration_artifact_ids),
        "policy_versions": (dependencies.policy_version,)
        if dependencies.policy_version
        else (),
        "model_versions": (dependencies.model_version,),
        "parser_version": dependencies.parser_version,
        "taxonomy_version": dependencies.taxonomy_version,
        "quality_policy_version": quality_policy_version,
        "runtime_version": dependencies.runtime_version,
        "calculation_version": dependencies.calculation_version,
        "source_content_hashes": sorted_hashes(dependencies.source_content_hashes),
        "random_seed": random_seed,
        "numerical_settings": dict(sorted((numerical_settings or {}).items())),
        "quality_issue_codes": sorted_ids(quality_issue_codes),
        "release_profile_thresholds": dict(
            sorted((release_profile_thresholds or {}).items())
        ),
        "artifact_hashes": tuple(artifact_hashes),
        "artifact_ids": tuple(artifact_ids),
    }
    if len(payload["artifact_hashes"]) != len(payload["artifact_ids"]):
        raise ValueError("artifact IDs and hashes must be paired")
    return ReleaseManifestV1(**payload, manifest_digest=sha256_digest(payload))


def build_provenance_graph(
    *,
    snapshot_id: str,
    fact_ids: tuple[str, ...],
    input_digest: str,
    result_hash: str,
    assumption_ids: tuple[str, ...] = (),
    model_input_ids: tuple[str, ...] = (),
    calculation_node_ids: tuple[str, ...] = (),
    scenario_ids: tuple[str, ...] = (),
    raw_response_ids: tuple[str, ...] = (),
    filing_package_ids: tuple[str, ...] = (),
    xbrl_fact_ids: tuple[str, ...] = (),
    normalized_metric_ids: tuple[str, ...] = (),
    interval_ids: tuple[str, ...] = (),
    reported_value_id: str = "reported_intrinsic_value",
    code_version: str | None = None,
    policy_version: str | None = None,
    quality_status: str | None = None,
    node_metadata: dict[str, dict[str, Any]] | None = None,
) -> ProvenanceGraphV1:
    if not all(
        (
            raw_response_ids,
            filing_package_ids,
            xbrl_fact_ids,
            fact_ids,
            normalized_metric_ids,
            assumption_ids,
            model_input_ids,
            calculation_node_ids,
            interval_ids,
            scenario_ids,
        )
    ):
        raise ValueError("provenance graph requires every released stage")
    if not code_version or not policy_version or not quality_status:
        raise ValueError("provenance graph requires code, policy, and quality versions")
    edges: list[ProvenanceEdgeV1] = []
    metadata = node_metadata or {}
    nodes: list[ProvenanceNodeV1] = []
    declared: set[str] = set()

    def add_node(node_id: str, node_type: str) -> None:
        if node_id not in declared:
            details = metadata.get(node_id)
            if details is None:
                raise ValueError(f"provenance metadata is missing for {node_id}")
            nodes.append(
                ProvenanceNodeV1(
                    node_id=node_id,
                    node_type=node_type,
                    source_id=str(details["source_id"]),
                    unit=str(details["unit"]),
                    quality_status=str(details["quality_status"]),
                    observed_at=details["observed_at"],
                )
            )
            declared.add(node_id)

    add_node(snapshot_id, "filing_snapshot")
    add_node(input_digest, "model_input")
    add_node(result_hash, "calculation_result")
    add_node(reported_value_id, "reported_value")

    def connect(
        source_id: str,
        target_id: str,
        relation: Literal[
            "derived_from", "selected_from", "resolved_from", "calculated_by"
        ],
        expression: str,
        input_ids: tuple[str, ...] = (),
    ) -> None:
        edges.append(
            ProvenanceEdgeV1(
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                expression=expression,
                input_ids=input_ids or (source_id,),
                code_version=code_version,
                policy_version=policy_version,
                quality_status=quality_status,
            )
        )

    def add_stage(ids: tuple[str, ...], node_type: str) -> None:
        for node_id in ids:
            add_node(node_id, node_type)

    def connect_stage(
        sources: tuple[str, ...],
        targets: tuple[str, ...],
        relation: Literal[
            "derived_from", "selected_from", "resolved_from", "calculated_by"
        ],
        expression: str,
    ) -> None:
        for target_id in targets:
            if sources:
                connect(sources[0], target_id, relation, expression, sources)

    add_stage(raw_response_ids, "raw_response")
    add_stage(filing_package_ids, "filing_package")
    add_stage(xbrl_fact_ids, "parsed_xbrl_fact")
    add_stage(normalized_metric_ids, "normalized_metric")
    add_stage(interval_ids, "interval")
    connect_stage(
        raw_response_ids,
        filing_package_ids,
        "derived_from",
        "raw response fetched into filing package",
    )
    connect_stage(
        filing_package_ids,
        xbrl_fact_ids,
        "derived_from",
        "filing package parsed into XBRL facts",
    )
    connect_stage(
        xbrl_fact_ids,
        fact_ids,
        "derived_from",
        "parsed XBRL fact normalized as canonical fact",
    )
    connect_stage(
        fact_ids,
        normalized_metric_ids,
        "derived_from",
        "canonical fact normalized into metric",
    )

    for fact_id in fact_ids:
        add_node(fact_id, "canonical_fact")
        connect(
            fact_id,
            input_digest,
            "selected_from",
            "canonical fact selected for valuation input",
        )
    for assumption_id in assumption_ids:
        add_node(assumption_id, "assumption")
        connect(
            assumption_id,
            input_digest,
            "resolved_from",
            "assumption resolved into model input",
        )
    for model_input_id in model_input_ids:
        add_node(model_input_id, "model_input")
        connect(
            model_input_id,
            input_digest,
            "derived_from",
            "model input normalized from assumptions",
        )
    previous = input_digest
    for node_id in calculation_node_ids:
        add_node(node_id, "calculation_node")
        connect(
            previous, node_id, "calculated_by", "deterministic calculation graph node"
        )
        previous = node_id
    for scenario_id in scenario_ids:
        add_node(scenario_id, "scenario")
        connect(
            previous, scenario_id, "derived_from", "scenario or interval projection"
        )
        previous = scenario_id
    connect_stage(
        assumption_ids,
        model_input_ids,
        "resolved_from",
        "assumption resolved into model input",
    )
    connect_stage(
        normalized_metric_ids,
        assumption_ids,
        "resolved_from",
        "normalized metric resolved into assumption",
    )
    connect_stage(
        interval_ids, scenario_ids, "derived_from", "scenario projected into interval"
    )
    connect(
        snapshot_id,
        input_digest,
        "derived_from",
        "immutable snapshot selected by decision timestamp",
    )
    connect(
        input_digest, result_hash, "calculated_by", "deterministic calculation result"
    )
    connect(result_hash, reported_value_id, "derived_from", "reported value projection")
    graph_payload = {"nodes": nodes, "edges": edges}
    graph_id = f"graph-{sha256_digest(graph_payload)[:32]}"
    digest = sha256_digest(
        {
            "contract_version": "fundamental.v1",
            "graph_id": graph_id,
            "nodes": nodes,
            "edges": edges,
        }
    )
    return ProvenanceGraphV1(
        contract_version="fundamental.v1",
        graph_id=graph_id,
        nodes=tuple(nodes),
        edges=tuple(edges),
        graph_digest=digest,
    )


def _first_difference(
    expected: CalculationArtifactV1, actual: CalculationArtifactV1
) -> tuple[str, str | None]:
    if expected.input_digest != actual.input_digest:
        return "input_digest", "input_digest"
    if expected.model_version != actual.model_version:
        return "model_version", "model_version"
    if expected.calculation_version != actual.calculation_version:
        return "calculation_version", "calculation_version"
    expected_nodes = {node.node_id: node for node in expected.nodes}
    actual_nodes = {node.node_id: node for node in actual.nodes}
    for node in expected.nodes:
        candidate = actual_nodes.get(node.node_id)
        if candidate is None:
            return node.node_id, "calculation_nodes"
        if (
            node.value != candidate.value
            or node.formula != candidate.formula
            or node.inputs != candidate.inputs
            or node.unit != candidate.unit
            or node.trace != candidate.trace
        ):
            return node.node_id, "calculation_nodes"
    for node in actual.nodes:
        if node.node_id not in expected_nodes:
            return node.node_id, "calculation_nodes"
    if expected.intrinsic_value != actual.intrinsic_value:
        return "equity_value", "calculation_nodes"
    if expected.per_share_value != actual.per_share_value:
        return "per_share_value", "calculation_nodes"
    return "result_hash", "result_hash"


def _artifact_result_hash(artifact: CalculationArtifactV1) -> str:
    return sha256_digest(
        {
            "input_digest": artifact.input_digest,
            "intrinsic_value": artifact.intrinsic_value,
            "per_share_value": artifact.per_share_value,
            "nodes": artifact.nodes,
            "model_version": artifact.model_version,
        }
    )


def replay_manifest(
    envelope: ReplayEnvelopeV1,
    *,
    artifact_store: ArtifactStore | None = None,
    snapshot_repository: SnapshotRepository | None = None,
) -> ReplayReportV1:
    """Replay a released artifact from its pinned manifest without source access."""
    manifest = envelope.manifest
    expected = envelope.expected
    request = envelope.request
    if request.provenance.snapshot_id != request.valuation_context.data_snapshot_id:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="provenance.snapshot_id",
            changed_dependency="snapshot",
        )
    if artifact_store is None or snapshot_repository is None:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="artifact_store",
            changed_dependency="artifact_store",
        )
    if not manifest.artifact_ids:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="manifest.artifact_ids",
            changed_dependency="release_manifest",
        )
    if expected.input_digest not in manifest.input_hashes:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="manifest.input_hashes",
            changed_dependency="release_manifest",
        )
    if expected.result_hash not in manifest.artifact_hashes:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="manifest.artifact_hashes",
            changed_dependency="release_manifest",
        )
    if (
        manifest.snapshot_ids
        and request.valuation_context.data_snapshot_id not in manifest.snapshot_ids
    ):
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="snapshot_id",
            changed_dependency="snapshot",
        )
    if manifest.service_version != SERVICE_VERSION:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="service_version",
            changed_dependency="service",
        )
    if manifest.decision_timestamp != request.valuation_context.valuation_timestamp:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="decision_timestamp",
            changed_dependency="valuation_context",
        )
    if (
        manifest.issuer_id != request.identity.issuer_id
        or manifest.security_id != request.identity.security_id
    ):
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="identity",
            changed_dependency="identity",
        )
    if set(request.historical_facts) - set(manifest.canonical_fact_ids):
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="canonical_fact_ids",
            changed_dependency="facts",
        )
    if manifest.model_versions and request.model_version not in manifest.model_versions:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="model_version",
            changed_dependency="model",
        )
    if (
        manifest.policy_versions
        and (request.policy_id or "") not in manifest.policy_versions
    ):
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="policy_version",
            changed_dependency="policy",
        )
    if request.provenance.parser_version != manifest.parser_version:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="parser_version",
            changed_dependency="parser",
        )
    if request.provenance.taxonomy_version != manifest.taxonomy_version:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="taxonomy_version",
            changed_dependency="taxonomy",
        )
    if expected.calculation_version != manifest.calculation_version:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="calculation_version",
            changed_dependency="calculation",
        )
    runtime_version = f"python-{sys.version_info.major}.{sys.version_info.minor}"
    if manifest.runtime_version != runtime_version:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="runtime_version",
            changed_dependency="runtime",
        )
    try:
        snapshot = snapshot_repository.get(request.valuation_context.data_snapshot_id)
    except SnapshotError:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="snapshot_id",
            changed_dependency="snapshot_repository",
        )
    snapshot_hashes = {record.content_hash for record in snapshot.source_records}
    if (
        snapshot.snapshot_id != request.valuation_context.data_snapshot_id
        or snapshot.coverage_status.value != "verified"
        or snapshot.identity.issuer_id != request.identity.issuer_id
        or snapshot.identity.security_id != request.identity.security_id
        or snapshot.valuation_timestamp != request.valuation_context.valuation_timestamp
    ):
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="snapshot.quality",
            changed_dependency="snapshot",
        )
    if not set(manifest.source_content_hashes).issubset(snapshot_hashes):
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="snapshot.source_content_hashes",
            changed_dependency="snapshot",
        )
    if len(manifest.artifact_ids) != len(manifest.artifact_hashes):
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="manifest.artifact_refs",
            changed_dependency="release_manifest",
        )
    released_artifacts: list[CalculationArtifactV1] = []
    for artifact_id, result_hash in zip(
        manifest.artifact_ids, manifest.artifact_hashes
    ):
        try:
            record = artifact_store.get(artifact_id)
            if record.status != "valid":
                raise SnapshotError(
                    "ARTIFACT_NOT_VALID",
                    f"artifact {artifact_id} has status {record.status}",
                )
            released = CalculationArtifactV1.model_validate_json(
                artifact_store.read(artifact_id)
            )
        except (SnapshotError, ValueError):
            return ReplayReportV1(
                contract_version="fundamental.v1",
                status="mismatch",
                expected_result_hash=expected.result_hash,
                expected_input_digest=expected.input_digest,
                first_difference=f"manifest.artifact_ids[{artifact_id}]",
                changed_dependency="artifact_store",
            )
        if released.result_hash != result_hash:
            return ReplayReportV1(
                contract_version="fundamental.v1",
                status="mismatch",
                expected_result_hash=expected.result_hash,
                actual_result_hash=released.result_hash,
                expected_input_digest=expected.input_digest,
                actual_input_digest=released.input_digest,
                first_difference=f"manifest.artifact_hashes[{artifact_id}]",
                changed_dependency="artifact_store",
            )
        if released.snapshot_id != request.valuation_context.data_snapshot_id:
            return ReplayReportV1(
                contract_version="fundamental.v1",
                status="mismatch",
                expected_result_hash=expected.result_hash,
                actual_result_hash=released.result_hash,
                expected_input_digest=expected.input_digest,
                actual_input_digest=released.input_digest,
                first_difference=f"artifact.snapshot_id[{artifact_id}]",
                changed_dependency="snapshot",
            )
        released_artifacts.append(released)
    released = next(
        (
            candidate
            for candidate in released_artifacts
            if candidate.result_hash == expected.result_hash
        ),
        None,
    )
    if released is None:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="manifest.artifact_hashes",
            changed_dependency="artifact_store",
        )
    if released != expected:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            actual_result_hash=released.result_hash,
            expected_input_digest=expected.input_digest,
            actual_input_digest=released.input_digest,
            first_difference=_first_difference(expected, released)[0],
            changed_dependency="artifact_store",
        )
    return replay_calculation(request, released)


def replay_calculation(
    request: ValuationInputV1, expected: CalculationArtifactV1
) -> ReplayReportV1:
    if _artifact_result_hash(expected) != expected.result_hash:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            first_difference="result_hash",
            changed_dependency="artifact",
        )
    expected_input_digest = request.with_digest().input_digest
    if expected.input_digest != expected_input_digest:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="mismatch",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            actual_input_digest=expected_input_digest,
            first_difference="input_digest",
            changed_dependency="input_digest",
        )
    try:
        actual = calculate(request)
    except CalculationRefusal as error:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="abstain",
            expected_result_hash=expected.result_hash,
            expected_input_digest=expected.input_digest,
            actual_input_digest=expected_input_digest,
            first_difference=error.code,
            changed_dependency="calculation",
        )
    dependency_versions = {
        "calculator": actual.calculation_version,
        "model": actual.model_version,
        "policy": actual.policy_version or "none",
        "snapshot": actual.snapshot_id,
        "parser": request.provenance.parser_version,
        "taxonomy": request.provenance.taxonomy_version,
        "runtime": f"python-{sys.version_info.major}.{sys.version_info.minor}",
    }
    if actual.result_hash == expected.result_hash:
        return ReplayReportV1(
            contract_version="fundamental.v1",
            status="match",
            expected_result_hash=expected.result_hash,
            actual_result_hash=actual.result_hash,
            expected_input_digest=expected.input_digest,
            actual_input_digest=actual.input_digest,
            dependency_versions=dependency_versions,
        )
    first_difference, changed_dependency = _first_difference(expected, actual)
    return ReplayReportV1(
        contract_version="fundamental.v1",
        status="mismatch",
        expected_result_hash=expected.result_hash,
        actual_result_hash=actual.result_hash,
        expected_input_digest=expected.input_digest,
        actual_input_digest=actual.input_digest,
        first_difference=first_difference,
        changed_dependency=changed_dependency,
        dependency_versions=dependency_versions,
    )
