"""Versioned model eligibility and explicit assumption policy resolution."""

from __future__ import annotations

from dataclasses import dataclass
import os
import tempfile
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Iterable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contracts import (
    AssumptionsV1,
    EligibilityReportV1,
    ForecastAssumptionsV1,
    PolicyResolutionV1,
    QualityInputV1,
    QualityStatus,
    ValuationInputV1,
    WaccAssumptionsV1,
)
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError


class ModelSpecV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    profile_id: Literal["us-gaap-public-v1"]
    required_fields: tuple[str, ...] = Field(min_length=1)
    forbidden_conditions: tuple[str, ...] = ()
    acceptable_ranges: dict[str, tuple[Decimal | None, Decimal | None]] = {}
    minimum_quality: tuple[QualityStatus, ...] = (QualityStatus.VERIFIED,)
    supported_archetypes: tuple[str, ...] = Field(min_length=1)
    abstention_reasons: tuple[str, ...] = ()
    owner: str = Field(min_length=1)
    validator: str = Field(min_length=1)
    lifecycle: Literal["active", "exploratory", "retired"]


class PolicyRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    profile_id: Literal["us-gaap-public-v1"]
    model_id: Literal["fcff_dcf", "transition_fcff_dcf"]
    model_version: str = Field(min_length=1)
    assumptions: AssumptionsV1 | None
    source_refs: tuple[str, ...] = Field(min_length=1)
    effective_at: datetime
    status: Literal["active", "retired"]
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digest_matches(self) -> "PolicyRecordV1":
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must include a timezone")
        payload = self.model_dump(exclude={"policy_digest"})
        if self.policy_digest != sha256_digest(payload):
            raise ValueError("policy_digest does not match policy content")
        return self


class PolicyRegistry:
    def __init__(
        self,
        models: Iterable[ModelSpecV1] = (),
        policies: Iterable[PolicyRecordV1] = (),
        model_repository: "ModelRepository | None" = None,
        repository: "PolicyRepository | None" = None,
    ) -> None:
        self._models = {(item.model_id, item.model_version): item for item in models}
        self._policies = {item.policy_id: item for item in policies}
        self._model_repository = model_repository
        self._repository = repository
        if repository is not None:
            for policy in self._policies.values():
                repository.publish(policy)

    def model(self, model_id: str, model_version: str) -> ModelSpecV1 | None:
        model = self._models.get((model_id, model_version))
        if model is not None or self._model_repository is None:
            return model
        try:
            model = self._model_repository.get_model(model_id, model_version)
        except PolicyError:
            return None
        self._models[(model_id, model_version)] = model
        return model

    def models(self) -> tuple[ModelSpecV1, ...]:
        values = {
            (model.model_id, model.model_version): model
            for model in self._models.values()
        }
        if self._model_repository is not None:
            values.update(
                {
                    (model.model_id, model.model_version): model
                    for model in self._model_repository.list_models()
                }
            )
        return tuple(values.values())

    def policy(self, policy_id: str) -> PolicyRecordV1 | None:
        policy = self._policies.get(policy_id)
        if policy is not None or self._repository is None:
            return policy
        try:
            policy = self._repository.get(policy_id)
        except PolicyError:
            return None
        self._policies[policy_id] = policy
        return policy

    def policies(self) -> tuple[PolicyRecordV1, ...]:
        values = {policy.policy_id: policy for policy in self._policies.values()}
        if self._repository is not None:
            values.update(
                {policy.policy_id: policy for policy in self._repository.list()}
            )
        return tuple(values.values())

    def select_policy(
        self,
        *,
        model_id: str,
        model_version: str,
        valuation_timestamp: datetime,
        policy_id: str | None,
    ) -> PolicyRecordV1:
        model = self.model(model_id, model_version)
        if model is None or model.lifecycle != "active":
            raise PolicyError(
                "MODEL_UNSUPPORTED", "requested model version is not active"
            )
        if policy_id is not None:
            policy = self.policy(policy_id)
            if policy is None:
                raise PolicyError("POLICY_NOT_FOUND", "policy release was not found")
            candidates = (policy,)
        else:
            candidates = tuple(
                item
                for item in self.policies()
                if item.model_id == model_id
                and item.model_version == model_version
                and item.status == "active"
                and item.effective_at <= valuation_timestamp
            )
        if len(candidates) != 1:
            code = "POLICY_NOT_FOUND" if not candidates else "POLICY_AMBIGUOUS"
            raise PolicyError(code, "no unique effective policy release is available")
        policy = candidates[0]
        if policy.model_id != model_id or policy.model_version != model_version:
            raise PolicyError(
                "POLICY_MODEL_MISMATCH",
                "policy release does not cover the requested model version",
            )
        if policy.status != "active" or policy.effective_at > valuation_timestamp:
            raise PolicyError(
                "POLICY_NOT_EFFECTIVE",
                "policy release is not active at the valuation timestamp",
            )
        return policy

    def add_policy(self, policy: PolicyRecordV1) -> None:
        existing = self.policy(policy.policy_id)
        if existing is not None and existing != policy:
            raise ValueError("policy versions are immutable")
        if self._repository is not None:
            self._repository.publish(policy)
        self._policies[policy.policy_id] = policy


class PolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ModelRepository(Protocol):
    def list_models(self) -> tuple[ModelSpecV1, ...]: ...

    def get_model(self, model_id: str, model_version: str) -> ModelSpecV1: ...

    def publish_model(self, model: ModelSpecV1) -> None: ...


class PolicyRepository:
    def list(self) -> tuple[PolicyRecordV1, ...]: ...

    def get(self, policy_id: str) -> PolicyRecordV1: ...

    def publish(self, policy: PolicyRecordV1) -> None: ...


class MetadataModelRepository:
    """Adapter for the service-owned metadata persistence port."""

    def __init__(self, metadata: object) -> None:
        self._metadata = metadata

    def list_models(self) -> tuple[ModelSpecV1, ...]:
        return tuple(self._metadata.list_models())

    def get_model(self, model_id: str, model_version: str) -> ModelSpecV1:
        try:
            return self._metadata.get_model(model_id, model_version)
        except SnapshotError as error:
            raise PolicyError(
                "MODEL_NOT_FOUND", "model release was not found"
            ) from error

    def publish_model(self, model: ModelSpecV1) -> None:
        self._metadata.publish_model(
            model, model_id=model.model_id, model_version=model.model_version
        )


class MetadataPolicyRepository:
    """Adapter for immutable policy releases stored by the service."""

    def __init__(self, metadata: object) -> None:
        self._metadata = metadata

    def list(self) -> tuple[PolicyRecordV1, ...]:
        return tuple(self._metadata.list_policies())

    def get(self, policy_id: str) -> PolicyRecordV1:
        candidates = tuple(item for item in self.list() if item.policy_id == policy_id)
        if len(candidates) != 1:
            code = "POLICY_NOT_FOUND" if not candidates else "POLICY_AMBIGUOUS"
            raise PolicyError(code, "policy release lookup is not unique")
        return candidates[0]

    def publish(self, policy: PolicyRecordV1) -> None:
        self._metadata.publish_policy(
            policy, policy_id=policy.policy_id, policy_version=policy.policy_version
        )


class FilesystemPolicyRepository:
    """Append-only JSON policy releases keyed by immutable policy ID."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, policy_id: str) -> Path:
        if (
            not policy_id
            or policy_id in {".", ".."}
            or any(character in policy_id for character in "/\\")
        ):
            raise PolicyError("POLICY_ID_INVALID", "policy ID contains an unsafe path")
        path = (self.root / f"{policy_id}.json").resolve()
        if self.root.resolve() not in path.parents:
            raise PolicyError("POLICY_ID_INVALID", "policy path escapes its repository")
        return path

    def publish(self, policy: PolicyRecordV1) -> None:
        path = self._path(policy.policy_id)
        payload = canonical_bytes(policy)
        fd, temporary = tempfile.mkstemp(prefix="policy-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temporary, path)
            except FileExistsError:
                if path.read_bytes() != payload:
                    raise PolicyError(
                        "POLICY_IMMUTABLE", "published policy IDs cannot be replaced"
                    )
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def get(self, policy_id: str) -> PolicyRecordV1:
        try:
            return PolicyRecordV1.model_validate_json(
                self._path(policy_id).read_bytes()
            )
        except FileNotFoundError as error:
            raise PolicyError(
                "POLICY_NOT_FOUND", "policy release was not found"
            ) from error
        except ValueError as error:
            raise PolicyError("POLICY_CORRUPT", "policy release is invalid") from error

    def list(self) -> tuple[PolicyRecordV1, ...]:
        policies: list[PolicyRecordV1] = []
        for path in sorted(self.root.glob("*.json")):
            policy = self.get(path.stem)
            if policy.policy_id != path.stem:
                raise PolicyError(
                    "POLICY_CORRUPT", "policy repository key does not match its record"
                )
            policies.append(policy)
        return tuple(policies)


def initial_policy_records() -> tuple[PolicyRecordV1, ...]:
    return tuple(
        PolicyRecordV1(
            **(
                payload := {
                    "contract_version": "fundamental.v1",
                    "policy_id": f"{model_id}-us-gaap-public-v1",
                    "policy_version": f"{model_version}-quality-v1",
                    "profile_id": "us-gaap-public-v1",
                    "model_id": model_id,
                    "model_version": model_version,
                    "assumptions": None,
                    "source_refs": (
                        "fundamental-service/docs/fundamental-enterprise-grade-target-state.md#24.4.3",
                    ),
                    # The first released policy is effective for every supported
                    # historical snapshot; later releases supersede it by version.
                    "effective_at": datetime(1970, 1, 1, tzinfo=UTC),
                    "status": "active",
                }
            ),
            policy_digest=sha256_digest(payload),
        )
        for model_id, model_version in (
            ("fcff_dcf", "fcff_dcf-v1"),
            ("transition_fcff_dcf", "transition_fcff_dcf-v1"),
        )
    )


@dataclass(frozen=True)
class EligibilityResult:
    report: EligibilityReportV1
    policy: PolicyRecordV1 | None = None


def resolve_policy(
    *,
    request: ValuationInputV1,
    policy: PolicyRecordV1,
) -> tuple[ValuationInputV1, PolicyResolutionV1]:
    if (
        policy.model_id != request.model_id
        or policy.model_version != request.model_version
    ):
        raise ValueError("policy model ID/version does not match request")
    if policy.assumptions is None:
        assumptions = request.assumptions
        resolved = _flatten_assumptions(assumptions.model_dump())
        precedence = {key: "caller" for key in resolved}
        resolved_input = request.model_copy(
            update={
                "policy_id": policy.policy_id,
                "provenance": request.provenance.model_copy(
                    update={"policy_version": policy.policy_version}
                ),
            }
        ).with_digest()
        return resolved_input, PolicyResolutionV1(
            contract_version="fundamental.v1",
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_digest=policy.policy_digest,
            resolved_fields=resolved,
            precedence=precedence,
            input_digest=resolved_input.input_digest,
        )
    caller = request.assumptions.model_dump()
    defaults = policy.assumptions.model_dump()
    resolved: dict[str, object] = {}
    precedence: dict[str, Literal["caller", "policy"]] = {}
    for group, values in defaults.items():
        if not isinstance(values, dict):
            key = f"assumptions.{group}"
            resolved[key] = (
                caller.get(group) if caller.get(group) is not None else values
            )
            precedence[key] = "caller" if caller.get(group) is not None else "policy"
            continue
        for field, value in values.items():
            key = f"assumptions.{group}.{field}"
            supplied = (
                caller.get(group, {}).get(field)
                if isinstance(caller.get(group), dict)
                else None
            )
            if supplied is None:
                resolved[key] = value
                precedence[key] = "policy"
            else:
                resolved[key] = supplied
                precedence[key] = "caller"
    resolved_assumptions = AssumptionsV1(
        forecast=ForecastAssumptionsV1(
            **{**defaults["forecast"], **caller["forecast"]}
        ),
        wacc=WaccAssumptionsV1(**{**defaults["wacc"], **caller["wacc"]}),
        terminal_growth=(
            caller["terminal_growth"]
            if caller.get("terminal_growth") is not None
            else defaults["terminal_growth"]
        ),
        capital_bridge=policy.assumptions.capital_bridge.model_copy(
            update=caller.get("capital_bridge", {})
        ),
        trace=request.assumptions.trace,
    )
    resolved_input = request.model_copy(
        update={
            "assumptions": resolved_assumptions,
            "policy_id": policy.policy_id,
            "provenance": request.provenance.model_copy(
                update={"policy_version": policy.policy_version}
            ),
        }
    )
    resolved_input = resolved_input.with_digest()
    resolution = PolicyResolutionV1(
        contract_version="fundamental.v1",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
        resolved_fields={key: value for key, value in resolved.items()},
        precedence=precedence,
        input_digest=resolved_input.input_digest,
    )
    return resolved_input, resolution


def _flatten_assumptions(
    value: dict[str, object], prefix: str = "assumptions"
) -> dict[str, object]:
    flattened: dict[str, object] = {}
    for key, item in value.items():
        path = f"{prefix}.{key}"
        if isinstance(item, dict):
            flattened.update(_flatten_assumptions(item, path))
        else:
            flattened[path] = item
    return flattened


def evaluate_eligibility(
    *,
    request: ValuationInputV1,
    model: ModelSpecV1,
    available_fields: set[str],
    quality: QualityInputV1,
    policy: PolicyRecordV1 | None = None,
) -> EligibilityResult:
    quality = QualityInputV1.model_validate(quality)
    missing = tuple(
        field for field in model.required_fields if field not in available_fields
    )
    forbidden = tuple(
        condition
        for condition in model.forbidden_conditions
        if condition in available_fields
    )
    issues: list[str] = []
    if request.valuation_context.coverage_profile != model.profile_id:
        issues.append("UNSUPPORTED_PROFILE")
    if missing:
        issues.append("MISSING_REQUIRED_FACT")
    if forbidden:
        issues.append("FORBIDDEN_CONDITION")
    if quality.status not in model.minimum_quality:
        issues.append("INSUFFICIENT_QUALITY")
    if model.lifecycle != "active":
        issues.append("MODEL_NOT_ACTIVE")
    if issues:
        status = (
            QualityStatus.UNSUPPORTED
            if "UNSUPPORTED_PROFILE" in issues
            else QualityStatus.ABSTAIN
        )
        return EligibilityResult(
            EligibilityReportV1(
                contract_version="fundamental.v1",
                status=status,
                selected_model=None,
                candidates=(model.model_id,),
                missing_fields=missing,
                forbidden_conditions=forbidden,
                issue_codes=tuple(issues),
                rationale="; ".join(issues),
            ),
            policy,
        )
    return EligibilityResult(
        EligibilityReportV1(
            contract_version="fundamental.v1",
            status=QualityStatus.VERIFIED,
            selected_model=model.model_id,
            candidates=(model.model_id,),
            rationale="all model applicability and quality gates passed",
        ),
        policy,
    )


def initial_model_specs() -> tuple[ModelSpecV1, ...]:
    common = {
        "contract_version": "fundamental.v1",
        "profile_id": "us-gaap-public-v1",
        "required_fields": (
            "revenue",
            "operating_income",
            "cash",
            "debt",
            "diluted_shares",
        ),
        "supported_archetypes": ("mature_non_financial",),
        "owner": "fundamental-service",
        "validator": "quality-policy-v1",
        "lifecycle": "active",
    }
    return (
        ModelSpecV1(model_id="fcff_dcf", model_version="fcff_dcf-v1", **common),
        ModelSpecV1(
            model_id="transition_fcff_dcf",
            model_version="transition_fcff_dcf-v1",
            required_fields=(*common["required_fields"], "filed_operating_evidence"),
            supported_archetypes=("high_growth_non_financial",),
            **{
                key: value
                for key, value in common.items()
                if key not in {"required_fields", "supported_archetypes"}
            },
        ),
    )
