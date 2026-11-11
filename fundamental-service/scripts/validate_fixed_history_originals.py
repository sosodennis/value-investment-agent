"""Run the fixed original inventory against the configured retained SEC runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

import fundamental_service
from fundamental_service.arelle_parser import (
    ArelleValidationProfileV1,
    ParserResourcePolicy,
    _directory_hash,
)
from fundamental_service.historical_dqc import (
    HISTORICAL_PROFILE_ID,
    V1_PROFILE,
    V3_PROFILE,
    historical_profile,
)
from fundamental_service.history_original_validation import (
    capture_scope,
    original_inventory,
    retained_original_result,
    validate_original,
)
from fundamental_service.history_replay import _write_content_addressed
from fundamental_service.ingestion import SecIngestionService
from fundamental_service.metadata import (
    PostgresArtifactStore,
    PostgresContentStore,
    PostgresMetadataStore,
)
from fundamental_service.contracts import SourceSnapshotV1
from fundamental_service.snapshots import SnapshotError
from fundamental_service.sec_capture import RetainedSecSourceAdapter
from fundamental_service.sec_source import (
    SecEdgarSourceAdapter,
    SecRequestPolicy,
    _open_sec,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest
from sqlalchemy import text


class NoCanonicalPublication:
    def get(self, snapshot_id: str) -> SourceSnapshotV1:
        raise SnapshotError("SNAPSHOT_NOT_FOUND", "diagnostics do not expose snapshots")

    def publish(self, snapshot: SourceSnapshotV1) -> None:
        raise RuntimeError("original diagnostics cannot publish a canonical snapshot")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cohort-root", type=Path, required=True)
    parser.add_argument("--runtime-pins", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument(
        "--validation-profile",
        choices=(V1_PROFILE.profile_id, V3_PROFILE.profile_id),
        default=HISTORICAL_PROFILE_ID,
    )
    arguments = parser.parse_args()
    selected_profile = historical_profile(arguments.validation_profile)
    assert selected_profile is not None
    pins = json.loads(arguments.runtime_pins.read_bytes())
    if not isinstance(pins.get("source_commit"), str) or not re.fullmatch(
        r"[0-9a-f]{40}", pins["source_commit"]
    ):
        raise ValueError("original validation requires an exact source commit")
    source = Path(fundamental_service.__file__).parent
    actual = {
        str(p.relative_to(source)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(source.rglob("*.py"))
    }
    runtime = {
        "python": platform.python_version(),
        "arelle-release": version("arelle-release"),
        "pydantic": version("pydantic"),
    }
    if actual != pins["source_files"] or runtime != pins["runtime"]:
        raise ValueError("installed source/runtime differs from exact commit pins")
    if (
        hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        != pins["executor_sha256"]
    ):
        raise ValueError("batch executor differs from exact commit pins")
    manifest = (
        arguments.cohort_root
        / "docs/acceptance/issue-359-sec-cohort-v1/capture_manifest.json"
    )
    inventory = original_inventory(arguments.cohort_root, manifest)
    root = arguments.output_directory
    before_files = {
        str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()
    }
    inventory_ref = _write_content_addressed(root, "inventory", inventory)
    cache = Path(os.environ["FUNDAMENTAL_SEC_TAXONOMY_CACHE_DIR"])
    profile = ArelleValidationProfileV1(
        profile_id=selected_profile.profile_id,
        dqc_version=selected_profile.dqc_version,
        validation_mode="sec-efm-dqc",
        edgar_plugin_dir=Path(os.environ["FUNDAMENTAL_SEC_EDGAR_PLUGIN_DIR"]),
        xule_plugin_dir=Path(os.environ["FUNDAMENTAL_SEC_XULE_PLUGIN_DIR"]),
        dqc_ruleset_path=Path(os.environ["FUNDAMENTAL_SEC_DQC_RULESET_PATH"]),
        edgar_plugin_sha256=os.environ["FUNDAMENTAL_SEC_EDGAR_PLUGIN_SHA256"],
        xule_plugin_sha256=os.environ["FUNDAMENTAL_SEC_XULE_PLUGIN_SHA256"],
        dqc_ruleset_sha256=os.environ["FUNDAMENTAL_SEC_DQC_RULESET_SHA256"],
        historical_dqc_dir=Path(os.environ["FUNDAMENTAL_SEC_HISTORICAL_DQC_DIR"]),
        historical_dqc_sha256=selected_profile.source_sha256,
    )
    cache_digest = _directory_hash(cache)
    if cache_digest != os.environ["FUNDAMENTAL_SEC_TAXONOMY_CACHE_SHA256"]:
        raise ValueError("original validation taxonomy cache changed")
    metadata = PostgresMetadataStore(
        os.environ["FUNDAMENTAL_SERVICE_DATABASE_URL"], auto_migrate=False
    )
    metadata.start()
    try:

        async def table_counts():
            async with metadata._runner._engine.connect() as connection:
                return {
                    table: int(
                        (
                            await connection.execute(
                                text("SELECT count(*) FROM fundamental." + table)
                            )
                        ).scalar_one()
                    )
                    for table in (
                        "artifact_references",
                        "content_objects",
                        "snapshot_manifests",
                        "canonical_facts",
                        "snapshot_facts",
                        "sec_ingestion_acquisitions",
                        "data_release_manifests",
                        "source_acquisition_audits",
                    )
                }

        before_counts = metadata._runner.run(table_counts())
        content = PostgresContentStore(root / "content", metadata)
        artifacts = PostgresArtifactStore(metadata, content)
        network_attempts = 0

        def opener(request, *, timeout):
            nonlocal network_attempts
            network_attempts += 1
            return _open_sec(request, timeout=timeout)

        request_policy = SecRequestPolicy(
            user_agent=os.environ["FUNDAMENTAL_SEC_USER_AGENT"]
        )
        provider = SecEdgarSourceAdapter(
            request_policy,
            opener=opener,
            request_slot=metadata.reserve_sec_provider_request_slot,
        )

        @contextmanager
        def lock(key):
            lease = metadata.try_acquire_ingestion_lock(key)
            if lease is None:
                raise RuntimeError(
                    "this original evidence acquisition is already running"
                )
            try:
                yield
            finally:
                metadata.release_ingestion_lock(lease)

        common = {
            "schema_version": "fixed-original-validation-input.v1",
            "pins": pins,
            "inventory_digest": inventory_ref["sha256"],
            "profile_digest": profile.digest(),
            "cache_digest": cache_digest,
            "parser_resource_policy": asdict(ParserResourcePolicy.from_env()),
            "request_policy": {
                k: v for k, v in asdict(request_policy).items() if k != "user_agent"
            },
            "user_agent_sha256": hashlib.sha256(
                request_policy.user_agent.encode()
            ).hexdigest(),
            "target_deadline_seconds": 180,
        }
        rows = []
        writes = 0
        for index, target in enumerate(inventory["targets"], 1):
            adapter = RetainedSecSourceAdapter(
                provider,
                scope=capture_scope(target),
                receipts=artifacts,
                content=content,
                capture_lock=lock,
            )
            service = SecIngestionService(
                source_adapter=adapter,
                content_store=content,
                snapshot_repository=NoCanonicalPublication(),
                audit_store=artifacts,
            )
            inputs = {**common, "target": target}
            with lock(sha256_digest(inputs)):
                result, wrote = retained_original_result(
                    inputs,
                    artifacts=artifacts,
                    evaluate=lambda: validate_original(
                        target,
                        service=service,
                        adapter=adapter,
                        profile=profile,
                        cache=cache,
                        deadline_at=datetime.now(UTC) + timedelta(seconds=180),
                    ),
                )
            writes += wrote
            ref = _write_content_addressed(root, "results", result)
            row = {
                "target": target,
                "input_digest": result["input_digest"],
                "output_digest": result["output_digest"],
                "result_digest": ref["sha256"],
                "status": result["output"]["status"],
                "code": result["output"].get("code"),
            }
            rows.append(row)
            print(
                canonical_bytes(
                    {
                        "completed": index,
                        "total": len(inventory["targets"]),
                        "issuer_id": target.issuer_id,
                        "accession": target.accession,
                        "status": row["status"],
                        "code": row["code"],
                        "wrote": wrote,
                    }
                ).decode(),
                flush=True,
            )
        output = {
            "rows": rows,
            "issuer_count": len(inventory["issuers"]),
            "missing_first_original_labels": sum(
                i["label_accession"] is None for i in inventory["issuers"]
            ),
            "status_counts": dict(
                sorted(Counter(str(r["status"]) for r in rows).items())
            ),
            "failure_counts": dict(
                sorted(Counter(str(r["code"]) for r in rows if r["code"]).items())
            ),
            "canonical_snapshot_published": False,
            "canonical_release_published": False,
            "composer_replay_completed": False,
            "supported_history_threshold": None,
        }
        report = {
            "source_commit": pins["source_commit"],
            "input_digest": sha256_digest(common),
            "output_digest": sha256_digest(output),
            "inputs": common,
            "output": output,
        }
        ref = _write_content_addressed(root, "report", report)
        after_counts = metadata._runner.run(table_counts())
        after_files = {
            str(p): p.stat().st_mtime_ns for p in root.rglob("*") if p.is_file()
        }
        for table in (
            "snapshot_manifests",
            "canonical_facts",
            "snapshot_facts",
            "sec_ingestion_acquisitions",
            "data_release_manifests",
        ):
            if before_counts[table] != after_counts[table]:
                raise RuntimeError("original diagnostics published canonical data")
        print(
            canonical_bytes(
                {
                    "report": ref,
                    "new_result_count": writes,
                    "network_attempt_count": network_attempts,
                    "new_file_count": len(set(after_files) - set(before_files)),
                    "existing_mtimes_unchanged": all(
                        after_files.get(p) == m for p, m in before_files.items()
                    ),
                    "database_row_deltas": {
                        t: after_counts[t] - before_counts[t] for t in before_counts
                    },
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                }
            ).decode(),
            flush=True,
        )
    finally:
        metadata.close()


if __name__ == "__main__":
    main()
