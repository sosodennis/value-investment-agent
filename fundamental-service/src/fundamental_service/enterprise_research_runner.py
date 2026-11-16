"""Persist conditional enterprise research through the existing evidence stores."""

from __future__ import annotations

import argparse
import hashlib
import platform
import sys
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import Field
from sqlalchemy.exc import SQLAlchemyError

from .command_artifacts import EvidenceArtifactStore, command_artifacts
from .contracts import StrictModel
from .data_releases import DataReleaseError
from .enterprise_research import (
    EnterpriseResearchReportV1,
    EnterpriseResearchRequestV1,
    research_enterprise_value,
)
from .replay import ArtifactRecordV1
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError


class EnterpriseExecutionInputV1(StrictModel):
    protocol: Literal["persistent-enterprise-research-v1"] = (
        "persistent-enterprise-research-v1"
    )
    declared_source_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    installed_source_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    runtime_pins: dict[str, str]
    request_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class EnterpriseExecutionV1(StrictModel):
    input: EnterpriseExecutionInputV1
    request_ref: ArtifactRecordV1
    result_ref: ArtifactRecordV1


class EnterpriseResearchPublicationV1(StrictModel):
    input_digest: str
    output_digest: str
    execution: EnterpriseExecutionV1
    execution_ref: ArtifactRecordV1
    wrote: bool


def installed_research_runtime() -> tuple[str, dict[str, str]]:
    root = Path(__file__).parent
    sources = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.suffix in {".py", ".sql"}
    }
    pins = {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "system": platform.system(),
        **{
            package: version(package)
            for package in (
                "pydantic",
                "arelle-release",
                "cryptography",
                "sqlalchemy",
                "asyncpg",
            )
        },
    }
    return sha256_digest(sources), pins


def _evaluate(
    request: EnterpriseResearchRequestV1, source_revision: str
) -> tuple[EnterpriseExecutionInputV1, EnterpriseResearchReportV1]:
    source_digest, pins = installed_research_runtime()
    inputs = EnterpriseExecutionInputV1(
        declared_source_revision=source_revision,
        installed_source_digest=source_digest,
        runtime_pins=pins,
        request_digest=sha256_digest(request),
    )
    return inputs, research_enterprise_value(request)


def _publish(
    request: EnterpriseResearchRequestV1,
    inputs: EnterpriseExecutionInputV1,
    result: EnterpriseResearchReportV1,
    artifacts: EvidenceArtifactStore,
) -> EnterpriseResearchPublicationV1:
    request_publication = artifacts.put_with_receipt(
        f"enterprise-research-input:{inputs.request_digest}", request
    )
    result_publication = artifacts.put_with_receipt(
        f"enterprise-research-result:{result.output_digest}",
        result,
        dependency_hashes=(inputs.request_digest,),
    )
    execution = EnterpriseExecutionV1(
        input=inputs,
        request_ref=request_publication.artifact,
        result_ref=result_publication.artifact,
    )
    input_digest = sha256_digest(inputs)
    publication = artifacts.put_with_receipt(
        f"enterprise-research-execution:{input_digest}",
        execution,
        dependency_hashes=(inputs.request_digest, result.output_digest),
    )
    return EnterpriseResearchPublicationV1(
        input_digest=input_digest,
        output_digest=result.output_digest,
        execution=execution,
        execution_ref=publication.artifact,
        wrote=request_publication.wrote
        or result_publication.wrote
        or publication.wrote,
    )


def persist_enterprise_research(
    request: EnterpriseResearchRequestV1,
    *,
    source_revision: str,
    artifacts: EvidenceArtifactStore,
) -> EnterpriseResearchPublicationV1:
    """Retain official conditional results and execution identity without approval."""
    request = EnterpriseResearchRequestV1.model_validate_json(canonical_bytes(request))
    inputs, result = _evaluate(request, source_revision)
    return _publish(request, inputs, result, artifacts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--request-digest", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--artifacts-root", type=Path)
    args = parser.parse_args(argv)
    try:
        raw = args.request.read_bytes()
        request = EnterpriseResearchRequestV1.model_validate_json(raw)
        if (
            raw != canonical_bytes(request)
            or sha256_digest(request) != args.request_digest
        ):
            raise ValueError(
                "research requires canonical request bytes and exact digest"
            )
        inputs, result = _evaluate(request, args.source_revision)
        with command_artifacts(args.artifacts_root) as artifacts:
            receipt = _publish(request, inputs, result, artifacts)
    except (DataReleaseError, SnapshotError) as error:
        print(canonical_bytes({"error_code": error.code}).decode(), file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print('{"error_code":"ENTERPRISE_RESEARCH_STORAGE_FAILED"}', file=sys.stderr)
        return 2
    except OSError:
        print('{"error_code":"ENTERPRISE_RESEARCH_IO_FAILED"}', file=sys.stderr)
        return 2
    except (ValueError, TypeError):
        print('{"error_code":"ENTERPRISE_RESEARCH_INPUT_INVALID"}', file=sys.stderr)
        return 2
    print(canonical_bytes(receipt).decode())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
