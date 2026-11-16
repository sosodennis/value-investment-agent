"""Publish a source-bound field review packet at an exact clean commit."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from fundamental_service.accounting_fields import (
    AccountingFieldRequestV1,
    extract_accounting_fields,
)
from fundamental_service.serialization import canonical_bytes, sha256_digest

from export_history_study_evidence import runtime_pins
from plan_history_study_precision import ROOT, DesignError, digest, publish_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--request-digest", required=True)
    parser.add_argument("--exact-commit", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        )
        if head != args.exact_commit or dirty:
            raise DesignError("exact clean implementation commit is required")
        raw = args.request.read_bytes()
        if digest(raw) != args.request_digest:
            raise DesignError("field request content digest differs")
        request = AccountingFieldRequestV1.model_validate_json(raw)
        if canonical_bytes(request) != raw:
            raise DesignError("field request must use canonical serialization")
        output = extract_accounting_fields(request)
        inputs = {
            "exact_commit": head,
            "runtime": runtime_pins(),
            "request_digest": args.request_digest,
            "extraction_input_digest": output.input_digest,
            "policy_digest": output.policy_digest,
        }
        report = {
            "inputs": inputs,
            "input_digest": sha256_digest(inputs),
            "output": output,
            "output_digest": sha256_digest(output),
        }
        receipt = publish_report(
            args.output_directory, json.loads(canonical_bytes(report))
        )
        print(
            json.dumps(
                {
                    **receipt,
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                    "candidate_count": sum(
                        row.candidate_count for row in output.fields
                    ),
                    "conflict_count": sum(len(row.conflicts) for row in output.fields),
                },
                sort_keys=True,
            )
        )
    except (
        OSError,
        ValueError,
        ArithmeticError,
        subprocess.CalledProcessError,
    ) as error:
        parser.exit(2, f"accounting field extraction failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
