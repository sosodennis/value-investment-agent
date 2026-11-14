"""Evaluate fixed-cohort loss observations; never authenticate or promote them."""

from __future__ import annotations

import argparse
import json
import math
import platform
import random
import subprocess
from dataclasses import dataclass
from decimal import Decimal, localcontext
from pathlib import Path
from typing import cast

from plan_history_study_precision import (
    MANIFEST_DIGEST,
    ROOT,
    DesignError,
    canonical_bytes,
    digest,
    publish_report,
)

MODELS = ("fcff_dcf", "transition_fcff_dcf")
TARGETS = ("next_annual_revenue", "next_annual_undiscounted_fcff")
WINDOWS = (3, 4, 5)
METHOD = "fixed100-paired-percentile-bootstrap-v1"
REPLICATES = 100_000
ALPHA = 0.05
FAMILY_SIZE = 32


def object_value(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise DesignError("expected an object")
    return cast(dict[str, object], value)


def read_document(path: Path) -> object:
    def unique_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result = dict(pairs)
        if len(result) != len(pairs):
            raise DesignError("duplicate JSON fields cannot silently discard evidence")
        return result

    return json.loads(path.read_bytes(), object_pairs_hook=unique_fields)


def list_value(value: object) -> list[object]:
    if not isinstance(value, list):
        raise DesignError("expected an array")
    return cast(list[object], value)


def text_value(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise DesignError("expected nonempty text")
    return value


def hash_value(value: object) -> str:
    value = text_value(value)
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise DesignError("expected SHA-256 identity")
    return value


def number_value(value: object) -> Decimal:
    try:
        number = Decimal(text_value(value))
    except ArithmeticError as error:
        raise DesignError("invalid decimal observation") from error
    if not number.is_finite() or abs(number) > Decimal("1e50"):
        raise DesignError("observation must be finite and within numerical range")
    return number


def text_array(value: object) -> tuple[str, ...]:
    values = tuple(text_value(v) for v in list_value(value))
    if tuple(sorted(set(values))) != values:
        raise DesignError("identities and reasons must be sorted and unique")
    return values


@dataclass(frozen=True)
class Observation:
    model: str
    target: str
    years: int
    status: str
    label_kind: str
    input_policy: str
    comparison_key: str
    signed_error: Decimal | None
    naive_absolute_error: Decimal | None
    scale: Decimal | None
    reasons: tuple[str, ...]
    evidence_digests: tuple[str, ...]

    @property
    def exact(self) -> bool:
        return self.status == "scored" and self.label_kind == "exact_original"

    @property
    def scaled(self) -> bool:
        return self.exact and self.scale is not None and self.scale > 0


@dataclass(frozen=True)
class Case:
    issuer: str
    origin: str
    frozen_reasons: tuple[str, ...]
    observations: tuple[Observation, ...]


def decode_observation(value: object) -> Observation:
    row = object_value(value)
    expected = {
        "model",
        "target",
        "years",
        "status",
        "label_kind",
        "input_policy",
        "comparison_key",
        "signed_error",
        "naive_absolute_error",
        "scale",
        "reasons",
        "evidence_digests",
    }
    if set(row) != expected:
        raise DesignError("observation fields differ from the versioned contract")
    model, target = text_value(row["model"]), text_value(row["target"])
    years = row["years"]
    if (
        model not in MODELS
        or target not in TARGETS
        or not isinstance(years, int)
        or isinstance(years, bool)
        or years not in WINDOWS
    ):
        raise DesignError("unknown model, target or explicit history window")
    status, kind = text_value(row["status"]), text_value(row["label_kind"])
    if status not in ("scored", "abstained", "missing") or kind not in (
        "exact_original",
        "conditional_scenario",
        "unavailable",
    ):
        raise DesignError("unknown disposition or label quality")
    reasons = text_array(row["reasons"])
    evidence = text_array(row["evidence_digests"])
    for item in evidence:
        hash_value(item)
    numbers = tuple(row[k] for k in ("signed_error", "naive_absolute_error", "scale"))
    error: Decimal | None
    naive: Decimal | None
    scale: Decimal | None
    if status == "scored":
        if kind == "unavailable" or not evidence or reasons:
            raise DesignError("scored losses need evidence and a declared label kind")
        error, naive = (number_value(v) for v in numbers[:2])
        scale = number_value(numbers[2]) if numbers[2] is not None else None
        if naive < 0 or (
            scale is not None and (scale < 0 or (scale and scale < Decimal("1e-50")))
        ):
            raise DesignError("naive loss and scale must be nonnegative and in range")
    else:
        if not reasons or any(v is not None for v in numbers):
            raise DesignError("unscored observations retain reasons and no losses")
        error = naive = scale = None
    return Observation(
        model,
        target,
        cast(int, years),
        status,
        kind,
        text_value(row["input_policy"]),
        hash_value(row["comparison_key"]),
        error,
        naive,
        scale,
        reasons,
        evidence,
    )


def decode_panel(value: object, manifest: object) -> tuple[Case, ...]:
    panel, frozen = object_value(value), object_value(manifest)
    if digest(canonical_bytes(manifest)) != MANIFEST_DIGEST:
        raise DesignError("fixed 100-issuer manifest digest differs")
    if set(panel) != {
        "schema_version",
        "analysis_scope",
        "fixed_manifest_digest",
        "cases",
    }:
        raise DesignError("panel fields differ from the versioned contract")
    if (
        panel["schema_version"] != "history-study-loss-panel.v1"
        or panel["analysis_scope"] != "exploratory_method_validation"
        or panel["fixed_manifest_digest"] != MANIFEST_DIGEST
    ):
        raise DesignError("this tool cannot grant confirmatory or release authority")
    decisions = {
        text_value(r["issuer_id"]): r
        for v in list_value(frozen["issuer_decisions"])
        for r in (object_value(v),)
    }
    if len(decisions) != 100:
        raise DesignError("fixed manifest must retain 100 independent issuers")
    cases = []
    policies: dict[tuple[str, str], str] = {}
    for value in list_value(panel["cases"]):
        row = object_value(value)
        if set(row) != {"issuer_id", "decision_at", "observations"}:
            raise DesignError("case fields differ from the versioned contract")
        issuer = text_value(row["issuer_id"])
        if (
            issuer not in decisions
            or row["decision_at"] != decisions[issuer]["decision_at"]
        ):
            raise DesignError("issuer replacement or decision-date substitution")
        observations = tuple(
            decode_observation(v) for v in list_value(row["observations"])
        )
        keys = [(o.model, o.target, o.years) for o in observations]
        if keys != [(m, t, y) for m in MODELS for t in TARGETS for y in WINDOWS]:
            raise DesignError(
                "every issuer retains all 12 unique model/target/history cells"
            )
        reasons = []
        decision = decisions[issuer]
        if decision["label_accession"] is None:
            reasons.append("FROZEN_FIRST_ORIGINAL_LABEL_MISSING")
        if decision["label_horizon_matches_forecast"] is not True:
            reasons.append("FROZEN_LABEL_HORIZON_MISMATCH")
        if reasons and any(o.status == "scored" for o in observations):
            raise DesignError(
                "missing or mismatched frozen labels cannot acquire scored losses"
            )
        for model in MODELS:
            for target in TARGETS:
                group = [
                    o for o in observations if (o.model, o.target) == (model, target)
                ]
                if len({(o.comparison_key, o.input_policy) for o in group}) != 1:
                    raise DesignError(
                        "history arms must share label, mapping, model and input policy identity"
                    )
                scored = [o for o in group if o.status == "scored"]
                if (
                    len(
                        {
                            (o.scale, o.naive_absolute_error, o.label_kind)
                            for o in scored
                        }
                    )
                    > 1
                ):
                    raise DesignError(
                        "paired arms must share training scale, baseline and label quality"
                    )
                policy_key = model, target
                if (
                    policies.setdefault(policy_key, group[0].input_policy)
                    != group[0].input_policy
                ):
                    raise DesignError("cannot pool different primary input policies")
        cases.append(
            Case(
                issuer,
                text_value(row["decision_at"]),
                tuple(sorted(reasons)),
                observations,
            )
        )
    if len(cases) != 100 or len({c.issuer for c in cases}) != 100:
        raise DesignError(
            "retain every selected issuer exactly once; scenarios are not issuers"
        )
    if [(c.issuer, c.origin) for c in cases] != sorted(
        (c.issuer, c.origin) for c in cases
    ):
        raise DesignError("cases must use canonical issuer/origin ordering")
    return tuple(cases)


def percentile(values: list[float], probability: float) -> float:
    """Sorted linear interpolation at (B - 1) * p, including both endpoints."""
    index = (len(values) - 1) * probability
    lower = math.floor(index)
    upper = math.ceil(index)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)


def paired_intervals(
    vectors: tuple[tuple[float, ...], ...], seed: str, replicates: int = REPLICATES
) -> list[dict[str, object]]:
    """Resample independent issuer vectors, preserving all within-issuer pairs."""
    n = len(vectors)
    dimensions = len(vectors[0]) if vectors else 8
    if n < 2:
        return [
            {
                "status": "INSUFFICIENT_INDEPENDENT_ISSUERS",
                "lower": None,
                "upper": None,
                "half_width": None,
            }
            for _ in range(dimensions)
        ]
    if any(
        len(v) != dimensions or any(not math.isfinite(x) for x in v) for v in vectors
    ):
        raise DesignError("bootstrap vectors must be rectangular and finite")
    rng = random.Random(int(seed, 16))
    columns: list[list[float]] = [[] for _ in range(dimensions)]
    for _ in range(replicates):
        indices = [rng.randrange(n) for _ in range(n)]
        for j in range(dimensions):
            columns[j].append(math.fsum(vectors[i][j] for i in indices) / n)
    tail = ALPHA / (2 * FAMILY_SIZE)
    results: list[dict[str, object]] = []
    for j, samples in enumerate(columns):
        if len({v[j] for v in vectors}) == 1:
            results.append(
                {
                    "status": "DEGENERATE_EMPIRICAL_DISTRIBUTION",
                    "lower": None,
                    "upper": None,
                    "half_width": None,
                }
            )
            continue
        samples.sort()
        lower, upper = percentile(samples, tail), percentile(samples, 1 - tail)
        estimate = math.fsum(v[j] for v in vectors) / n
        results.append(
            {
                "status": "EXPLORATORY_NOMINAL_BONFERRONI_PERCENTILE",
                "lower": str(lower),
                "upper": str(upper),
                "half_width": str(max(estimate - lower, upper - estimate)),
            }
        )
    return results


def raw_statistics(rows: list[Observation]) -> dict[str, object]:
    errors = [o.signed_error for o in rows if o.signed_error is not None]
    if not errors:
        return {
            "independent_issuers": 0,
            "signed_mean_USD": None,
            "MAE_USD": None,
            "RMSE_USD": None,
        }
    count = Decimal(len(errors))
    return {
        "independent_issuers": len(errors),
        "signed_mean_USD": str(sum(errors, Decimal(0)) / count),
        "MAE_USD": str(sum(map(abs, errors), Decimal(0)) / count),
        "RMSE_USD": str((sum((e * e for e in errors), Decimal(0)) / count).sqrt()),
    }


def scaled_vector(rows: list[Observation]) -> tuple[float, ...]:
    losses, differences = [], []
    for row in rows:
        assert (
            row.scale
            and row.signed_error is not None
            and row.naive_absolute_error is not None
        )
        loss = abs(row.signed_error) / row.scale
        losses.append(float(loss))
        differences.append(
            float((abs(row.signed_error) - row.naive_absolute_error) / row.scale)
        )
    return (*losses, *differences, losses[0] - losses[2], losses[1] - losses[2])


def analyze(
    cases: tuple[Case, ...], protocol_digest: str, panel_digest: str
) -> dict[str, object]:
    if len(cases) != 100 or len({c.issuer for c in cases}) != 100:
        raise DesignError("analysis requires 100 unique retained issuers")
    with localcontext() as context:
        context.prec = 34
        groups = []
        retained = []
        for case in cases:
            retained.append(
                {
                    "issuer_id": case.issuer,
                    "decision_at": case.origin,
                    "frozen_reasons": case.frozen_reasons,
                    "cells": [
                        {
                            "model": o.model,
                            "target": o.target,
                            "years": o.years,
                            "status": o.status,
                            "label_kind": o.label_kind,
                            "input_policy": o.input_policy,
                            "comparison_key": o.comparison_key,
                            "reasons": sorted(
                                set(o.reasons)
                                | ({"ZERO_TRAINING_SCALE"} if o.scale == 0 else set())
                                | (
                                    {"MISSING_TRAINING_SCALE"}
                                    if o.status == "scored" and o.scale is None
                                    else set()
                                )
                                | (
                                    {"CONDITIONAL_LABEL_EXCLUDED_FROM_EXACT_STUDY"}
                                    if o.label_kind == "conditional_scenario"
                                    else set()
                                )
                            ),
                            "evidence_digests": o.evidence_digests,
                        }
                        for o in case.observations
                    ],
                }
            )
        for model in MODELS:
            for target in TARGETS:
                rows_by_case = [
                    (
                        c,
                        [
                            o
                            for o in c.observations
                            if (o.model, o.target) == (model, target)
                        ],
                    )
                    for c in cases
                ]
                common = [
                    (c, rows)
                    for c, rows in rows_by_case
                    if len(rows) == 3 and all(o.scaled for o in rows)
                ]
                vectors = tuple(scaled_vector(rows) for _, rows in common)
                seed = digest(
                    canonical_bytes(
                        {
                            "protocol_digest": protocol_digest,
                            "panel_digest": panel_digest,
                            "model": model,
                            "target": target,
                            "common_issuers": [c.issuer for c, _ in common],
                        }
                    )
                )
                intervals = paired_intervals(vectors, seed)
                names = [
                    *(f"mean_mase_{y}" for y in WINDOWS),
                    *(f"model_minus_naive_{y}" for y in WINDOWS),
                    "three_minus_five",
                    "four_minus_five",
                ]
                hypotheses = [
                    {
                        "name": name,
                        "independent_issuers": len(common),
                        "mean": str(math.fsum(v[j] for v in vectors) / len(vectors))
                        if vectors
                        else None,
                        "interval": intervals[j],
                        "all_selected_mean_identification": "unidentified_unbounded_missing_losses"
                        if len(common) < 100
                        else "observed_fixed_cohort_mean",
                        "all_selected_lower": str(
                            math.fsum(v[j] for v in vectors) / 100
                        )
                        if j < 3
                        else None,
                        "all_selected_upper": None,
                    }
                    for j, name in enumerate(names)
                ]
                arms = []
                for i, years in enumerate(WINDOWS):
                    exact = [rows[i] for _, rows in rows_by_case if rows[i].exact]
                    scaled = [o for o in exact if o.scaled]
                    arms.append(
                        {
                            "years": years,
                            "all_selected_denominator": 100,
                            "declared_exact_raw": raw_statistics(exact),
                            "scaled_loss_issuers": len(scaled),
                            "per_arm_mean_MASE": str(
                                sum(
                                    (
                                        abs(o.signed_error) / o.scale
                                        for o in scaled
                                        if o.signed_error is not None and o.scale
                                    ),
                                    Decimal(0),
                                )
                                / len(scaled)
                            )
                            if scaled
                            else None,
                            "conditional_label_cells_excluded": sum(
                                rows[i].label_kind == "conditional_scenario"
                                for _, rows in rows_by_case
                            ),
                            "abstained_or_missing": sum(
                                rows[i].status != "scored" for _, rows in rows_by_case
                            ),
                            "zero_scale_issuers": sum(o.scale == 0 for o in exact),
                            "missing_scale_issuers": sum(
                                o.scale is None for o in exact
                            ),
                        }
                    )
                groups.append(
                    {
                        "model": model,
                        "target": target,
                        "arms": arms,
                        "common_issuer_ids": [c.issuer for c, _ in common],
                        "seed_digest": seed,
                        "executed_bootstrap_replicates": REPLICATES
                        if len(common) >= 2
                        else 0,
                        "hypotheses": hypotheses,
                    }
                )
    return {
        "schema_version": "history-study-analysis.v1",
        "method_version": METHOD,
        "analysis_scope": "exploratory_method_validation",
        "evidence_authority": "declared_loss_observations_not_authenticated_by_this_tool",
        "selected_issuers": 100,
        "retained_filing_targets": 589,
        "maximum_eligible_original_label_pairs": 90,
        "legacy_minimum_complete_pairs": 100,
        "legacy_gate_changed": False,
        "sample_status": "UNDERPOWERED_LEGACY_COMPLETE_PAIR_GATE_INFEASIBLE",
        "empirical_power_claim": False,
        "family_hypotheses": FAMILY_SIZE,
        "replicates": REPLICATES,
        "familywise_coverage_guaranteed": False,
        "missingness_assumption": "none_no_MAR_no_finite_unobserved_loss_bound",
        "retained_cases": retained,
        "groups": groups,
        "protocol_review_approved": False,
        "promotion_enabled": False,
        "supported_history_threshold": None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("protocol", "manifest", "panel", "output-directory"):
        parser.add_argument(f"--{name}", type=Path, required=True)
    parser.add_argument("--exact-commit", required=True)
    args = parser.parse_args()
    try:
        head = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip()
        if head != args.exact_commit or subprocess.check_output(
            ["git", "status", "--porcelain"], cwd=ROOT, text=True
        ):
            raise DesignError("exact clean implementation commit is required")
        pinned = ROOT / "docs/research/issue-377-methods-v4.json"
        if args.protocol.read_bytes() != pinned.read_bytes():
            raise DesignError("protocol differs from the executable pinned methods")
        protocol = read_document(pinned)
        manifest, panel = (read_document(p) for p in (args.manifest, args.panel))
        protocol_digest, panel_digest = (
            digest(canonical_bytes(v)) for v in (protocol, panel)
        )
        cases = decode_panel(panel, manifest)
        inputs = {
            "issue": 377,
            "exact_commit": head,
            "protocol_digest": protocol_digest,
            "fixed_manifest_digest": MANIFEST_DIGEST,
            "panel_digest": panel_digest,
            "tool_digest": digest(Path(__file__).read_bytes()),
            "publication_tool_digest": digest(
                (ROOT / "scripts/plan_history_study_precision.py").read_bytes()
            ),
            "runtime": {
                "python": platform.python_version(),
                "implementation": platform.python_implementation(),
                "machine": platform.machine(),
                "system": platform.system(),
                "random": "CPython_Random_MT19937_integer_seed_randrange",
                "decimal_precision": 34,
            },
        }
        output = analyze(cases, protocol_digest, panel_digest)
        report = {
            "inputs": inputs,
            "input_digest": digest(canonical_bytes(inputs)),
            "output": output,
            "output_digest": digest(canonical_bytes(output)),
        }
        publication = publish_report(args.output_directory, report)
        print(
            json.dumps(
                {
                    **publication,
                    "input_digest": report["input_digest"],
                    "output_digest": report["output_digest"],
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
        parser.exit(2, f"history-study analysis failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
