"""Inspect retained SEC ownership originals; never approve award completeness."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import platform
import subprocess
from pathlib import Path

from fundamental_service.sec_ownership import (
    SecOwnershipRequestV1,
    inspect_sec_ownership_sources,
)
from fundamental_service.serialization import canonical_bytes
from fundamental_service.snapshots import FilesystemContentStore

from plan_history_study_precision import ROOT, DesignError, publish_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        request = SecOwnershipRequestV1.model_validate_json(
            arguments.manifest.read_bytes()
        )
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"],
            cwd=ROOT,
            text=True,
        )
        if request.source_revision != head or dirty:
            raise DesignError(
                "ownership inspection requires the exact clean manifest commit"
            )
        if not arguments.content_root.is_dir():
            raise DesignError(
                "ownership inspection requires an existing retained content root"
            )
        evidence = inspect_sec_ownership_sources(
            request, content=FilesystemContentStore(arguments.content_root)
        )
        report = {
            "exact_commit": head,
            "runtime": {
                "python": platform.python_version(),
                "lxml": importlib.metadata.version("lxml"),
                "pydantic": importlib.metadata.version("pydantic"),
            },
            "evidence": evidence.model_dump(mode="json"),
        }
        receipt = publish_report(
            arguments.output_directory, json.loads(canonical_bytes(report))
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "failed", "message": str(error)}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {
                **receipt,
                "exact_commit": head,
                "input_digest": evidence.input_digest,
                "output_digest": evidence.output_digest,
                "parsed": sum(result.status == "parsed" for result in evidence.results),
                "refused": sum(
                    result.status == "refused" for result in evidence.results
                ),
                "complete_inventory": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
