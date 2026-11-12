"""Report prospective sample-size scenarios; never approve a history threshold."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import platform
import subprocess
import tempfile
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal, localcontext
from pathlib import Path
from statistics import NormalDist
from typing import cast

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "issue-377-operating-protocol-proposal-v3"
MANIFEST_DIGEST = "448f496b10e51a2ed351a7a37deb36e0d4b9672c1fbc5ed3b0b845c8cd54da3a"


class DesignError(ValueError):
    """The input cannot describe this frozen-population, unapproved design."""


@dataclass(frozen=True)
class PlanningDesign:
    alpha: Decimal
    power: Decimal
    half_width: Decimal
    difference: Decimal
    standard_deviations: tuple[Decimal, ...]
    hypotheses: int = 32
    maximum_pairs: int = 90
    legacy_required_pairs: int = 100


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or not all(isinstance(k, str) for k in value):
        raise DesignError("expected a JSON object")
    return cast(dict[str, object], value)


def _positive_decimal(value: object) -> Decimal:
    if not isinstance(value, str):
        raise DesignError("planning values must be finite positive decimal strings")
    try:
        number = Decimal(value)
    except ArithmeticError as error:
        raise DesignError("invalid decimal planning value") from error
    if not number.is_finite() or number <= 0:
        raise DesignError("planning values must be finite and positive")
    return number


def decode_design(value: object) -> PlanningDesign:
    proposal = _object(value)
    required = {
        "schema_version": SCHEMA,
        "status": "proposal_requires_review",
        "promotion_enabled": False,
        "supported_history_threshold": None,
        "fixed_manifest_digest": MANIFEST_DIGEST,
        "selected_issuers": 100,
        "filing_targets": 589,
        "maximum_eligible_label_pairs": 90,
        "legacy_minimum_complete_pairs": 100,
        "models": ["fcff_dcf", "transition_fcff_dcf"],
        "targets": ["next_annual_revenue", "next_annual_undiscounted_fcff"],
        "history_years": [3, 4, 5],
    }
    if any(
        key not in proposal or type(proposal[key]) is not type(v) or proposal[key] != v
        for key, v in required.items()
    ):
        raise DesignError("population, proposal status or execution arms changed")
    planning = _object(proposal.get("planning"))
    if planning.get("family_hypotheses") != 32:
        raise DesignError("all 32 prespecified hypotheses belong to one family")
    if planning.get("selected_planning_sd") is not None:
        raise DesignError("variance scenarios are not approved planning evidence")
    alpha = _positive_decimal(planning.get("familywise_alpha"))
    power = _positive_decimal(planning.get("power"))
    if not Decimal("0.000001") <= alpha < Decimal("0.5"):
        raise DesignError("alpha is outside the supported planning range")
    if not Decimal("0.5") < power < Decimal("0.999999"):
        raise DesignError("power is outside the supported planning range")
    values = planning.get("sd_scenarios_mase")
    if not isinstance(values, list) or not 1 <= len(values) <= 32:
        raise DesignError("one to 32 standard-deviation scenarios are required")
    deviations = tuple(_positive_decimal(v) for v in values)
    if tuple(sorted(set(deviations))) != deviations:
        raise DesignError("variance scenarios must be sorted and distinct")
    return PlanningDesign(
        alpha=alpha,
        power=power,
        half_width=_positive_decimal(planning.get("ci_half_width_mase")),
        difference=_positive_decimal(planning.get("detectable_difference_mase")),
        standard_deviations=deviations,
    )


def plan_precision(design: PlanningDesign) -> dict[str, object]:
    """Known-SD normal approximations, not finite-sample or achieved guarantees."""
    with localcontext() as context:
        context.prec = 34
        critical_probability = 1 - design.alpha / (2 * design.hypotheses)
        critical = Decimal(str(NormalDist().inv_cdf(float(critical_probability))))
        power_quantile = Decimal(str(NormalDist().inv_cdf(float(design.power))))
        rows = []
        for sd in design.standard_deviations:
            precision_n = int(
                ((critical * sd / design.half_width) ** 2).to_integral_value(
                    rounding=ROUND_CEILING
                )
            )
            power_n = int(
                (
                    ((critical + power_quantile) * sd / design.difference) ** 2
                ).to_integral_value(rounding=ROUND_CEILING)
            )
            required_n = max(2, precision_n, power_n)
            rows.append(
                {
                    "assumed_sd_mase": str(sd),
                    "precision_pairs_normal_approximation": max(2, precision_n),
                    "power_pairs_normal_approximation": max(2, power_n),
                    "required_pairs_normal_approximation": required_n,
                    "possible_with_at_most_90_pairs_under_assumption": (
                        required_n <= design.maximum_pairs
                    ),
                }
            )
    return {
        "interpretation": "prospective_assumptions_not_measured_power_or_precision",
        "normal_critical_value": str(critical),
        "normal_power_quantile": str(power_quantile),
        "family_hypotheses": design.hypotheses,
        "scenarios": rows,
        "legacy_gate_feasible": design.maximum_pairs >= design.legacy_required_pairs,
        "legacy_minimum_complete_pairs": design.legacy_required_pairs,
        "maximum_eligible_label_pairs": design.maximum_pairs,
        "legacy_gate_changed": False,
        "protocol_approved": False,
        "formal_forecasts_measured": 0,
        "empirical_power_or_precision_measured": False,
        "promotion_enabled": False,
        "supported_history_threshold": None,
    }


def publish_report(
    directory: Path, report: object, repository: Path = ROOT
) -> dict[str, object]:
    directory = directory.resolve()
    if (
        directory == repository.resolve()
        or repository.resolve() in directory.parents
        or any((parent / ".git").exists() for parent in (directory, *directory.parents))
    ):
        raise DesignError("generated reports must be outside the checkout")
    raw = canonical_bytes(report)
    report_digest = digest(raw)
    destination = directory / f"{report_digest}.json"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".publication.lock").open("a") as publication_lock:
        fcntl.flock(publication_lock, fcntl.LOCK_EX)
        if destination.exists():
            if destination.read_bytes() != raw:
                raise DesignError("existing content-addressed report is corrupt")
            return {"report_digest": report_digest, "wrote": False}
        with tempfile.NamedTemporaryFile(dir=directory, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
    return {"report_digest": report_digest, "wrote": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        dirty = subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        )
        if head != arguments.exact_commit or dirty:
            raise DesignError("exact clean implementation commit is required")
        raw = arguments.proposal.read_bytes()
        proposal: object = json.loads(raw)
        design = decode_design(proposal)
        inputs = {
            "issue": 377,
            "exact_commit": head,
            "tool_digest": digest(Path(__file__).read_bytes()),
            "proposal_bytes_digest": digest(raw),
            "proposal_canonical_digest": digest(canonical_bytes(proposal)),
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "normal_quantile": "statistics.NormalDist.inv_cdf",
                "decimal_precision": 34,
            },
        }
        output = plan_precision(design)
        report = {
            "inputs": inputs,
            "input_digest": digest(canonical_bytes(inputs)),
            "output": output,
            "output_digest": digest(canonical_bytes(output)),
        }
        result = publish_report(arguments.output_directory, report)
        print(
            json.dumps(
                {
                    **result,
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
                },
                sort_keys=True,
            )
        )
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(2, f"history-study design failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
