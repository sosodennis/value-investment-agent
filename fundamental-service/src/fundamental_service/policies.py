"""Versioned model eligibility and explicit assumption policy resolution."""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .contracts import (
    AssumptionsV1,
    CapitalBridgeAssumptionsV1,
    EligibilityReportV1,
    ForecastAssumptionsV1,
    MarketPolicyEvidenceV1,
    MarketPolicyInputsV1,
    ModelId,
    PolicyResolutionV1,
    PolicyValuationInputV1,
    QualityInputV1,
    QualityStatus,
    ValuationInputV1,
    WaccAssumptionsV1,
)
from .numerical_policy import VALUATION_NUMERICAL_POLICY
from .serialization import canonical_bytes, sha256_digest
from .snapshots import SnapshotError

AssumptionGroup = TypeVar("AssumptionGroup", bound=BaseModel)


class ModelSpecV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    model_id: ModelId
    schema_version: Literal["ModelSpecV1"] = "ModelSpecV1"
    model_version: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    required_fields: tuple[str, ...] = Field(min_length=1)
    forbidden_conditions: tuple[str, ...] = ()
    acceptable_ranges: dict[str, tuple[Decimal | None, Decimal | None]] = {}
    minimum_quality: tuple[QualityStatus, ...] = (QualityStatus.VERIFIED,)
    supported_archetypes: tuple[str, ...] = Field(min_length=1)
    abstention_reasons: tuple[str, ...] = ()
    owner: str = Field(min_length=1)
    validator: str = Field(min_length=1)
    lifecycle: Literal["active", "exploratory", "retired"]
    economic_purpose: str = Field(min_length=1)
    valuation_basis: Literal["enterprise", "equity", "asset"]
    jurisdictions: tuple[str, ...] = Field(min_length=1)
    accounting_bases: tuple[str, ...] = Field(min_length=1)
    required_evidence: tuple[str, ...] = Field(min_length=1)
    assumption_policy: str = Field(min_length=1)
    formula_graph: str = Field(min_length=1)
    numerical_policy: str = Field(min_length=1)
    eligibility_policy: str = Field(min_length=1)
    abstention_policy: str = Field(min_length=1)
    uncertainty_policy: str = Field(min_length=1)
    calibration_policy: str = Field(min_length=1)
    calibration_targets: tuple[str, ...] = Field(min_length=1)
    calibration_required_for_promotion: bool = True
    required_release_gates: tuple[str, ...] = Field(min_length=1)
    source_register: tuple[str, ...] = Field(min_length=1)
    capital_bridge_policy: str = Field(min_length=1)
    golden_cohort: str = Field(min_length=1)
    challenger: str = Field(min_length=1)
    independent_validator: str = Field(min_length=1)
    approval_date: datetime | None = None
    review_date: datetime | None = None
    retirement_trigger: str = Field(min_length=1)
    rollback_policy: str = Field(min_length=1)
    monitoring_policy: str = Field(min_length=1)
    release_manifest: str | None = None

    @model_validator(mode="after")
    def governed_release(self) -> ModelSpecV1:
        if self.lifecycle == "active":
            required = {
                "approval_date": self.approval_date,
                "review_date": self.review_date,
                "release_manifest": self.release_manifest,
            }
            missing = tuple(name for name, value in required.items() if value is None)
            if missing:
                raise ValueError(
                    "active model requires approval, review, and release manifest: "
                    + ", ".join(missing)
                )
        if self.lifecycle != "active" and self.release_manifest is not None:
            raise ValueError("unreleased model cannot carry a release manifest")
        if self.owner == self.independent_validator:
            raise ValueError("model owner cannot independently validate its release")
        for name, value in (
            ("approval_date", self.approval_date),
            ("review_date", self.review_date),
        ):
            if value is not None and (
                value.tzinfo is None or value.utcoffset() is None
            ):
                raise ValueError(f"{name} must include a timezone")
        if (
            self.approval_date is not None
            and self.review_date is not None
            and self.review_date <= self.approval_date
        ):
            raise ValueError("review_date must follow approval_date")
        return self


class PolicyRecordV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_version: Literal["fundamental.v1"]
    policy_id: str = Field(min_length=1)
    policy_version: str = Field(min_length=1)
    profile_id: str = Field(min_length=1)
    model_id: ModelId
    model_version: str = Field(min_length=1)
    assumptions: AssumptionsV1 | None
    market_inputs: MarketPolicyInputsV1 | None = None
    source_refs: tuple[str, ...] = Field(min_length=1)
    effective_at: datetime
    status: Literal["active", "retired"]
    policy_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def digest_matches(self) -> PolicyRecordV1:
        if self.effective_at.tzinfo is None or self.effective_at.utcoffset() is None:
            raise ValueError("effective_at must include a timezone")
        payload = self.model_dump(exclude={"policy_digest"})
        if self.policy_digest == sha256_digest(payload):
            return self
        legacy_payload = self.model_dump(exclude={"policy_digest", "market_inputs"})
        if self.market_inputs is not None or self.policy_digest != sha256_digest(
            legacy_payload
        ):
            raise ValueError("policy_digest does not match policy content")
        return self


class PolicyRegistry:
    def __init__(
        self,
        models: Iterable[ModelSpecV1] = (),
        policies: Iterable[PolicyRecordV1] = (),
        model_repository: ModelRepository | None = None,
        repository: PolicyRepository | None = None,
    ) -> None:
        self._models: dict[tuple[str, str], ModelSpecV1] = {
            (item.model_id, item.model_version): item for item in models
        }
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
        except PolicyError as error:
            if error.code == "POLICY_NOT_FOUND":
                return None
            raise
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
        if model is None:
            raise PolicyError(
                "MODEL_UNSUPPORTED", "requested model version is not active"
            )
        candidates: tuple[PolicyRecordV1, ...]
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
                and (
                    item.market_inputs is None
                    or all(
                        evidence.available_at <= valuation_timestamp
                        for evidence in item.market_inputs.evidence
                    )
                )
            )
            if candidates:
                latest = max(item.effective_at for item in candidates)
                candidates = tuple(
                    item for item in candidates if item.effective_at == latest
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
        if policy.market_inputs is not None and any(
            item.available_at > valuation_timestamp
            for item in policy.market_inputs.evidence
        ):
            raise PolicyError(
                "POLICY_NOT_EFFECTIVE",
                "policy market evidence is unavailable at the valuation timestamp",
            )
        if model.lifecycle != "active" and policy.assumptions is not None:
            raise PolicyError(
                "MODEL_UNSUPPORTED",
                "exploratory models may only resolve an explicit no-default policy",
            )
        return policy

    def add_policy(self, policy: PolicyRecordV1) -> None:
        existing = self.policy(policy.policy_id)
        if existing is not None and existing != policy:
            raise ValueError("policy versions are immutable")
        if self._repository is not None:
            self._repository.publish(policy)
        self._policies[policy.policy_id] = policy

    def add_model(self, model: ModelSpecV1) -> None:
        key = (model.model_id, model.model_version)
        existing = self.model(*key)
        if existing is not None and existing != model:
            raise ValueError("model versions are immutable")
        if self._model_repository is not None:
            self._model_repository.publish_model(model)
        self._models[key] = model


class PolicyError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ModelRepository(Protocol):
    def list_models(self) -> tuple[ModelSpecV1, ...]: ...

    def get_model(self, model_id: str, model_version: str) -> ModelSpecV1: ...

    def publish_model(self, model: ModelSpecV1) -> None: ...


class PolicyRepository(Protocol):
    def list(self) -> tuple[PolicyRecordV1, ...]: ...

    def get(self, policy_id: str) -> PolicyRecordV1: ...

    def publish(self, policy: PolicyRecordV1) -> None: ...


class ModelMetadataPort(Protocol):
    def list_models(self) -> tuple[ModelSpecV1, ...]: ...

    def get_model(self, model_id: str, model_version: str) -> ModelSpecV1: ...

    def publish_model(
        self, model: object, *, model_id: str, model_version: str
    ) -> None: ...


class PolicyMetadataPort(Protocol):
    def list_policies(self) -> tuple[PolicyRecordV1, ...]: ...

    def publish_policy(
        self, policy: object, *, policy_id: str, policy_version: str
    ) -> None: ...


class MetadataModelRepository:
    """Adapter for the service-owned metadata persistence port."""

    def __init__(self, metadata: ModelMetadataPort) -> None:
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

    def __init__(self, metadata: PolicyMetadataPort) -> None:
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
                    ) from None
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


_FCFF_MARKET_POLICY_VERSION = "fcff-market-policy-2025-v1"
_FCFF_MARKET_POLICY_AS_OF = datetime(2025, 1, 3, tzinfo=UTC)
_FCFF_MARKET_POLICY_CAPTURED_AT = datetime(2026, 11, 3, tzinfo=UTC)
_FRED_DGS10_FIXTURE_HASH = (
    "1cf8c2d38f773142b58b772bde5028d12f00dfd72bf37b40c2327e15d418ea28"
)


def _market_policy_evidence(
    role: str,
    value: Decimal,
    *,
    method: Literal["observed_source", "approved_policy"],
    source_id: str,
    source_uri: str,
    source_version: str,
    terms_reference: str,
    content_hash: str | None = None,
    rationale: str,
) -> MarketPolicyEvidenceV1:
    if content_hash is None:
        content_hash = sha256_digest(
            {
                "policy_version": _FCFF_MARKET_POLICY_VERSION,
                "role": role,
                "value": value,
                "source_version": source_version,
            }
        )
    return MarketPolicyEvidenceV1(
        role=role,
        method=method,
        value=value,
        source_id=source_id,
        source_uri=source_uri,
        content_hash=content_hash,
        source_version=source_version,
        terms_reference=terms_reference,
        as_of=_FCFF_MARKET_POLICY_AS_OF,
        available_at=_FCFF_MARKET_POLICY_AS_OF,
        captured_at=_FCFF_MARKET_POLICY_CAPTURED_AT,
        rationale=rationale,
    )


def _initial_market_inputs() -> MarketPolicyInputsV1:
    policy_uri = (
        f"in-repository://fundamental-service/policy/{_FCFF_MARKET_POLICY_VERSION}"
    )
    policy_terms = (
        "fundamental-service/docs/fundamental-enterprise-grade-target-state.md#24.4.4"
    )
    evidence = (
        _market_policy_evidence(
            "risk_free_rate",
            Decimal("0.046"),
            method="observed_source",
            source_id="fred-observations",
            source_uri=(
                "https://fred.stlouisfed.org/graph/fredgraph.csv"
                "?id=DGS10&cosd=2025-01-03&coed=2025-01-03"
            ),
            source_version="DGS10@2025-01-03",
            terms_reference="https://fred.stlouisfed.org/terms-of-use/",
            content_hash=_FRED_DGS10_FIXTURE_HASH,
            rationale="10-year U.S. Treasury par yield observed in the pinned FRED vintage",
        ),
        _market_policy_evidence(
            "beta",
            Decimal("1.1"),
            method="approved_policy",
            source_id="fundamental-market-policy",
            source_uri=policy_uri,
            source_version=_FCFF_MARKET_POLICY_VERSION,
            terms_reference=policy_terms,
            rationale="reviewed explicit beta assumption; not an issuer fact",
        ),
        _market_policy_evidence(
            "equity_risk_premium",
            Decimal("0.05"),
            method="approved_policy",
            source_id="fundamental-market-policy",
            source_uri=policy_uri,
            source_version=_FCFF_MARKET_POLICY_VERSION,
            terms_reference=policy_terms,
            rationale="reviewed explicit equity risk premium assumption",
        ),
        _market_policy_evidence(
            "pre_tax_cost_of_debt",
            Decimal("0.05"),
            method="approved_policy",
            source_id="fundamental-market-policy",
            source_uri=policy_uri,
            source_version=_FCFF_MARKET_POLICY_VERSION,
            terms_reference=policy_terms,
            rationale="reviewed marginal debt-cost assumption; trailing interest is diagnostic only",
        ),
        _market_policy_evidence(
            "debt_weight",
            Decimal("0.2"),
            method="approved_policy",
            source_id="fundamental-market-policy",
            source_uri=policy_uri,
            source_version=_FCFF_MARKET_POLICY_VERSION,
            terms_reference=policy_terms,
            rationale="reviewed capital-weight policy used when issuer market value is unavailable",
        ),
        _market_policy_evidence(
            "equity_weight",
            Decimal("0.8"),
            method="approved_policy",
            source_id="fundamental-market-policy",
            source_uri=policy_uri,
            source_version=_FCFF_MARKET_POLICY_VERSION,
            terms_reference=policy_terms,
            rationale="reviewed capital-weight policy used when issuer market value is unavailable",
        ),
        _market_policy_evidence(
            "terminal_growth",
            Decimal("0.02"),
            method="approved_policy",
            source_id="fundamental-market-policy",
            source_uri=policy_uri,
            source_version=_FCFF_MARKET_POLICY_VERSION,
            terms_reference=policy_terms,
            rationale="reviewed terminal-growth ceiling policy; must remain below discount rates",
        ),
    )
    return MarketPolicyInputsV1(
        policy_version=_FCFF_MARKET_POLICY_VERSION,
        risk_free_rate=Decimal("0.046"),
        beta=Decimal("1.1"),
        equity_risk_premium=Decimal("0.05"),
        pre_tax_cost_of_debt=Decimal("0.05"),
        debt_weight=Decimal("0.2"),
        equity_weight=Decimal("0.8"),
        terminal_growth=Decimal("0.02"),
        evidence=evidence,
    )


def initial_policy_records() -> tuple[PolicyRecordV1, ...]:
    return tuple(
        PolicyRecordV1.model_validate(
            {
                **(
                    payload := {
                        "contract_version": "fundamental.v1",
                        "policy_id": f"{model_id}-us-gaap-public-v1",
                        "policy_version": f"{model_version}-quality-v1",
                        "profile_id": "us-gaap-public-v1",
                        "model_id": model_id,
                        "model_version": model_version,
                        "assumptions": None,
                        "market_inputs": _initial_market_inputs(),
                        "source_refs": (
                            "fundamental-service/docs/fundamental-enterprise-grade-target-state.md#24.4.3",
                        ),
                        # The first released policy is effective for every supported
                        # historical snapshot; later releases supersede it by version.
                        "effective_at": datetime(1970, 1, 1, tzinfo=UTC),
                        "status": "active",
                    }
                ),
                "policy_digest": sha256_digest(payload),
            }
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
    selection_mode: Literal["pinned", "exploratory_active"] = (
        "pinned" if request.policy_id is not None else "exploratory_active"
    )
    if (
        policy.model_id != request.model_id
        or policy.model_version != request.model_version
    ):
        raise ValueError("policy model ID/version does not match request")
    resolved: dict[str, object]
    precedence: dict[str, Literal["caller", "policy"]]
    if policy.assumptions is None:
        assumptions = request.assumptions
        resolved = _flatten_assumptions(assumptions.model_dump())
        precedence = dict.fromkeys(resolved, "caller")
        resolved_input = request.model_copy(
            update={
                "policy_id": policy.policy_id,
                "provenance": request.provenance.model_copy(
                    update={"policy_version": policy.policy_version}
                ),
            }
        ).with_digest()
        if (
            request.caller_approval is not None
            and request.caller_approval.input_digest != resolved_input.input_digest
        ):
            raise PolicyError(
                "CALLER_APPROVAL_CONFLICT",
                "caller approval is bound to a different resolved input_digest",
            )
        assert resolved_input.input_digest is not None
        return resolved_input, PolicyResolutionV1(
            contract_version="fundamental.v1",
            policy_id=policy.policy_id,
            policy_version=policy.policy_version,
            policy_digest=policy.policy_digest,
            selection_mode=selection_mode,
            resolved_fields=resolved,
            precedence=precedence,
            input_digest=resolved_input.input_digest,
        )
    caller = request.assumptions.model_dump()
    defaults = policy.assumptions.model_dump()
    if request.model_id not in {"fcff_dcf", "transition_fcff_dcf"}:
        raise ValueError("policy resolution is not released for this model family")
    capital_bridge = policy.assumptions.capital_bridge
    if capital_bridge is None or any(
        defaults.get(group) is None
        for group in ("forecast", "wacc", "capital_bridge", "trace")
    ):
        raise ValueError("policy does not contain a complete FCFF assumption set")
    resolved = {}
    precedence = {}
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
        capital_bridge=capital_bridge.model_copy(
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
    if (
        request.caller_approval is not None
        and request.caller_approval.input_digest != resolved_input.input_digest
    ):
        raise PolicyError(
            "CALLER_APPROVAL_CONFLICT",
            "caller approval is bound to a different resolved input_digest",
        )
    assert resolved_input.input_digest is not None
    resolution = PolicyResolutionV1(
        contract_version="fundamental.v1",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
        selection_mode=selection_mode,
        resolved_fields=dict(resolved),
        precedence=precedence,
        input_digest=resolved_input.input_digest,
    )
    return resolved_input, resolution


def resolve_policy_overrides(
    *,
    request: PolicyValuationInputV1,
    policy: PolicyRecordV1,
) -> tuple[ValuationInputV1, PolicyResolutionV1]:
    """Resolve a typed policy request into the calculator's complete input."""

    if (
        policy.model_id != request.model_id
        or policy.model_version != request.model_version
    ):
        raise PolicyError(
            "POLICY_MODEL_MISMATCH",
            "policy release does not cover the requested model version",
        )
    if request.model_id not in {"fcff_dcf", "transition_fcff_dcf"}:
        raise PolicyError(
            "POLICY_MODEL_UNSUPPORTED",
            "policy calculation is not released for this model family",
        )
    if request.assumptions.bank is not None or (
        policy.assumptions is not None and policy.assumptions.bank is not None
    ):
        raise PolicyError(
            "POLICY_ASSUMPTIONS_INVALID",
            "bank assumptions are not valid for an FCFF policy calculation",
        )

    defaults = policy.assumptions or AssumptionsV1()
    overrides = request.assumptions
    resolved_fields: dict[str, object] = {}
    precedence: dict[str, Literal["caller", "policy"]] = {}

    def resolve_group(name: str, model_type: type[AssumptionGroup]) -> AssumptionGroup:
        default_group = getattr(defaults, name)
        caller_group = getattr(overrides, name)
        default_values = (
            default_group.model_dump(exclude_none=True) if default_group else {}
        )
        caller_values = (
            caller_group.model_dump(exclude_none=True) if caller_group else {}
        )
        values: dict[str, object] = {}
        for field in model_type.model_fields:
            path = f"assumptions.{name}.{field}"
            if field in caller_values:
                values[field] = caller_values[field]
                precedence[path] = "caller"
            elif field in default_values:
                values[field] = default_values[field]
                precedence[path] = "policy"
            else:
                continue
            resolved_fields[path] = values[field]
        try:
            return model_type.model_validate(values)
        except ValidationError as error:
            raise PolicyError(
                "POLICY_ASSUMPTIONS_INCOMPLETE",
                f"caller values and policy do not resolve complete {name} assumptions",
            ) from error

    forecast = resolve_group("forecast", ForecastAssumptionsV1)
    wacc = resolve_group("wacc", WaccAssumptionsV1)
    capital_bridge = resolve_group("capital_bridge", CapitalBridgeAssumptionsV1)

    terminal_growth = overrides.terminal_growth
    if terminal_growth is not None:
        precedence["assumptions.terminal_growth"] = "caller"
    else:
        terminal_growth = defaults.terminal_growth
        if terminal_growth is not None:
            precedence["assumptions.terminal_growth"] = "policy"
    if terminal_growth is None:
        raise PolicyError(
            "POLICY_ASSUMPTIONS_INCOMPLETE",
            "caller values and policy do not resolve terminal_growth",
        )
    resolved_fields["assumptions.terminal_growth"] = terminal_growth

    trace = overrides.trace or defaults.trace
    if trace is None:
        raise PolicyError(
            "POLICY_ASSUMPTIONS_INCOMPLETE",
            "caller values and policy do not resolve assumption trace",
        )
    precedence["assumptions.trace"] = "caller" if overrides.trace else "policy"
    resolved_fields["assumptions.trace"] = trace.model_dump(mode="json")

    assumptions = AssumptionsV1(
        forecast=forecast,
        wacc=wacc,
        terminal_growth=terminal_growth,
        capital_bridge=capital_bridge,
        trace=trace,
    )
    payload = {
        "contract_version": request.contract_version,
        "identity": request.identity,
        "valuation_context": request.valuation_context,
        "historical_facts": request.historical_facts,
        "assumptions": assumptions,
        "uncertainty": request.uncertainty,
        "quality": request.quality,
        "provenance": request.provenance.model_copy(
            update={"policy_version": policy.policy_version}
        ),
        "model_id": request.model_id,
        "model_version": request.model_version,
        "policy_id": policy.policy_id,
    }
    try:
        resolved = ValuationInputV1.model_validate({**payload}).with_digest()
    except ValidationError as error:
        raise PolicyError(
            "POLICY_ASSUMPTIONS_INVALID",
            "resolved policy calculation input is invalid",
        ) from error
    if (
        request.input_digest is not None
        and request.input_digest != resolved.input_digest
    ):
        raise PolicyError(
            "INPUT_DIGEST_MISMATCH",
            "input_digest does not match the resolved policy calculation input",
        )
    if (
        request.caller_approval is not None
        and request.caller_approval.input_digest != resolved.input_digest
    ):
        raise PolicyError(
            "CALLER_APPROVAL_CONFLICT",
            "caller approval is bound to a different resolved input_digest",
        )
    if request.caller_approval is not None:
        resolved = resolved.model_copy(
            update={"caller_approval": request.caller_approval}
        )

    assert resolved.input_digest is not None
    return resolved, PolicyResolutionV1(
        contract_version="fundamental.v1",
        policy_id=policy.policy_id,
        policy_version=policy.policy_version,
        policy_digest=policy.policy_digest,
        selection_mode="pinned",
        resolved_fields=resolved_fields,
        precedence=precedence,
        input_digest=resolved.input_digest,
    )


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
        if condition in quality.issue_codes
    )
    issues: list[str] = []
    if request.valuation_context.coverage_profile != model.profile_id:
        issues.append("UNSUPPORTED_PROFILE")
    if request.model_id != model.model_id:
        issues.append("MODEL_MISMATCH")
    if missing:
        issues.append("MISSING_REQUIRED_FACT")
    if forbidden:
        issues.append("FORBIDDEN_CONDITION")
    if quality.status not in model.minimum_quality:
        issues.append("INSUFFICIENT_QUALITY")
    if model.lifecycle != "active":
        issues.append("MODEL_NOT_ACTIVE")
    if model.release_manifest is None:
        issues.append("MODEL_RELEASE_EVIDENCE_MISSING")
    if issues:
        unsupported_issues = {
            "UNSUPPORTED_PROFILE",
            "MODEL_NOT_ACTIVE",
            "MODEL_RELEASE_EVIDENCE_MISSING",
        }
        status = (
            QualityStatus.UNSUPPORTED
            if set(issues) & unsupported_issues
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
    required_fields = ("revenue", "operating_income", "cash", "debt", "diluted_shares")
    common = {
        "contract_version": "fundamental.v1",
        "profile_id": "us-gaap-public-v1",
        "required_fields": required_fields,
        "supported_archetypes": ("mature_non_financial",),
        "owner": "fundamental-service",
        "validator": "quality-policy-v1",
        "lifecycle": "active",
        "economic_purpose": "value mature non-financial operating cash flows",
        "valuation_basis": "enterprise",
        "jurisdictions": ("US",),
        "accounting_bases": ("us-gaap",),
        "required_evidence": ("issuer-filings", "capital-bridge", "golden-cohort"),
        "assumption_policy": "policy-v1-explicit-caller-assumptions",
        "formula_graph": "calculator-v1-fcff",
        "numerical_policy": VALUATION_NUMERICAL_POLICY,
        "eligibility_policy": "quality-policy-v1",
        "abstention_policy": "abstain-on-missing-or-unverified-evidence-v1",
        "uncertainty_policy": "caller-owned-explicit-controls-v1",
        "calibration_policy": "calibration-inactive-unless-oos-promoted-v1",
        "calibration_targets": ("first-subsequent-reported-revenue-v1",),
        "calibration_required_for_promotion": True,
        "required_release_gates": (
            "public-source-coverage",
            "point-in-time-accounting",
            "positive-negative-golden-cohorts",
            "independent-node-challenger",
            "calibration-oos",
            "replay-reproducibility",
        ),
        "source_register": ("sec-companyfacts", "sec-filing", "treasury-yields"),
        "capital_bridge_policy": (
            "enterprise-value-plus-cash-minus-debt-and-dilution-v1"
        ),
        "golden_cohort": "fundamental-engineering-cohort-v1",
        "challenger": "independent-verification-v1",
        "independent_validator": "fundamental-service-validator",
        "approval_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "review_date": datetime(2026, 12, 31, tzinfo=timezone.utc),
        "release_manifest": "release-fundamental-v1",
        "retirement_trigger": "blocking-reconciliation-or-expired-review",
        "rollback_policy": "restore-last-promoted-release-manifest",
        "monitoring_policy": (
            "monthly-source-health-drift-missingness-and-abstention-v1"
        ),
    }
    return (
        ModelSpecV1.model_validate(
            {"model_id": "fcff_dcf", "model_version": "fcff_dcf-v1", **common}
        ),
        ModelSpecV1.model_validate(
            {
                "model_id": "transition_fcff_dcf",
                "model_version": "transition_fcff_dcf-v1",
                "required_fields": (*required_fields, "filed_operating_evidence"),
                "supported_archetypes": ("high_growth_non_financial",),
                **{
                    key: value
                    for key, value in common.items()
                    if key not in {"required_fields", "supported_archetypes"}
                },
            }
        ),
    )


def expansion_model_specs() -> tuple[ModelSpecV1, ...]:
    """Governed inventory for post-cutover families.

    These records make coverage and ownership auditable while keeping every
    family explicitly unsupported until its evidence and release gates pass.
    """

    families = (
        {
            "model_id": "bank_excess_return",
            "archetype": "U.S. bank holding company or depository institution",
            "basis": "equity",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "bank_current_book_value",
                "bank_tangible_book_value",
                "bank_reported_rwa",
                "bank_cet1_capital",
                "bank_diluted_shares",
                "bank_regulatory_entity_relationship",
            ),
            "forbidden_conditions": (
                "BANK_REGULATORY_ENTITY_UNMAPPED",
                "BANK_REGULATORY_SCOPE_MISMATCH",
                "BANK_CET1_RECONCILIATION_FAILED",
                "BANK_REGULATORY_SOURCE_STALE",
            ),
            "sources": (
                "sec-companyfacts",
                "sec-filing",
                "fdic-bankfind",
                "ffiec-cdr",
            ),
            "evidence": (
                "issuer SEC filings and point-in-time company facts",
                "reported CET1 capital and risk-weighted assets at matched entity "
                "scope",
                "FDIC certificate or FFIEC RSSD crosswalk with dated ownership "
                "evidence",
                "positive and negative bank golden cohorts",
                "independent residual-income node report",
            ),
            "assumption_policy": (
                "caller supplies each forecast net income, RWA growth, cost of equity, "
                "payout, terminal growth, CET1 floor, and share count; no defaults"
            ),
            "formula_graph": "bank-excess-return-v1",
            "uncertainty_policy": (
                "caller specifies bounded forecast-income and RWA-growth "
                "distributions; "
                "reject invalid draws according to the request"
            ),
            "calibration_targets": (
                "next-reported-bank-net-income-v1",
                "next-reported-bank-risk-weighted-assets-v1",
            ),
            "capital_bridge_policy": (
                "reported-tangible-book-plus-discounted-residual-income-with-"
                "cet1-rwa-guard-v1"
            ),
            "valuation_basis": "equity",
            "economic_purpose": (
                "value a regulated banking issuer from tangible book and residual "
                "income"
            ),
        },
        {
            "model_id": "insurance_statutory_excess_return",
            "archetype": "U.S. insurance issuer",
            "basis": "equity",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "insurance_statutory_surplus",
                "insurance_rbc_ratio",
                "insurance_premiums_earned",
                "insurance_reserve_development",
                "insurance_diluted_shares",
            ),
            "forbidden_conditions": (
                "INSURANCE_STATUTORY_SCOPE_UNAVAILABLE",
                "INSURANCE_RBC_BASIS_UNVERIFIED",
                "INSURANCE_RESERVE_DEVELOPMENT_ADVERSE",
            ),
            "sources": ("sec-filing", "naic-statutory-filings"),
            "evidence": (
                "issuer filings and applicable jurisdiction statutory statements",
                "RBC formula and authorized-control-level basis by legal entity",
                "positive and negative insurer cohorts",
                "independent reserve and surplus reconciliation",
            ),
            "assumption_policy": (
                "caller supplies premium growth, loss and expense ratios, capital "
                "retention, cost of equity, and terminal growth"
            ),
            "formula_graph": "insurance-statutory-excess-return-v1",
            "uncertainty_policy": (
                "caller supplies bounded premium, loss-ratio, and reserve-"
                "development distributions"
            ),
            "calibration_targets": (
                "first-subsequent-statutory-premium-and-loss-ratio-v1",
            ),
            "capital_bridge_policy": "statutory-surplus-to-common-equity-v1",
            "valuation_basis": "equity",
            "economic_purpose": (
                "value insurer equity subject to statutory solvency constraints"
            ),
        },
        {
            "model_id": "reit_nav",
            "archetype": "U.S. equity REIT",
            "basis": "asset",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "reit_property_value_by_asset",
                "reit_debt_by_entity",
                "reit_lease_obligations",
                "reit_occupancy",
                "reit_maintenance_capex",
                "reit_diluted_shares",
            ),
            "forbidden_conditions": (
                "REIT_AFFO_UNRECONCILED",
                "REIT_PROPERTY_COVERAGE_INCOMPLETE",
                "REIT_LEASE_SCOPE_MISMATCH",
            ),
            "sources": ("sec-filing", "nareit-definitions"),
            "evidence": (
                "issuer property schedule, lease obligations, and debt maturities",
                "property-level valuation method and dated cap-rate evidence",
                "positive and negative REIT NAV cohorts",
                "independent property, debt, and share-count bridge",
            ),
            "assumption_policy": (
                "caller supplies asset-level NOI, discount or cap rates, "
                "disposition costs, "
                "and diluted shares"
            ),
            "formula_graph": "reit-asset-nav-v1",
            "uncertainty_policy": (
                "caller supplies bounded NOI, cap-rate, and occupancy distributions"
            ),
            "calibration_targets": ("first-subsequent-property-noi-and-occupancy-v1",),
            "capital_bridge_policy": (
                "property-nav-minus-debt-leases-and-other-claims-v1"
            ),
            "valuation_basis": "asset",
            "economic_purpose": (
                "value REIT common equity from property and liability NAV"
            ),
        },
        {
            "model_id": "regulated_utility",
            "archetype": "U.S. regulated electric or gas utility",
            "basis": "enterprise",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "utility_jurisdictional_rate_base",
                "utility_allowed_return",
                "utility_recovery_schedule",
                "utility_parent_debt",
                "utility_diluted_shares",
            ),
            "forbidden_conditions": (
                "UTILITY_RATE_ORDER_MISSING",
                "UTILITY_RECOVERY_DISALLOWED",
                "UTILITY_JURISDICTION_MIXED",
            ),
            "sources": ("sec-filing", "ferc-public-data"),
            "evidence": (
                "issuer filings and applicable FERC forms",
                "effective state commission rate orders and recovery timing",
                "positive and negative utility cohorts by jurisdiction",
                "independent rate-base and capital-structure bridge",
            ),
            "assumption_policy": (
                "caller specifies jurisdiction-specific rate base additions, "
                "allowed returns, "
                "recovery timing, and financing assumptions"
            ),
            "formula_graph": "jurisdictional-rate-base-discounted-cash-flow-v1",
            "uncertainty_policy": (
                "caller supplies bounded rate-base, recovery, and allowed-return "
                "distributions"
            ),
            "calibration_targets": (
                "first-subsequent-rate-base-and-allowed-return-v1",
            ),
            "capital_bridge_policy": (
                "jurisdictional-enterprise-cash-flow-to-parent-equity-v1"
            ),
            "valuation_basis": "enterprise",
            "economic_purpose": (
                "value utility cash flows under jurisdiction-specific rate regulation"
            ),
        },
        {
            "model_id": "normalized_cyclical",
            "archetype": "U.S. commodity-exposed cyclical issuer",
            "basis": "enterprise",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "cyclical_realized_price",
                "cyclical_production_volume",
                "cyclical_unit_cost",
                "cyclical_capacity_utilization",
                "cyclical_net_debt",
                "cyclical_diluted_shares",
            ),
            "forbidden_conditions": (
                "CYCLICAL_THROUGH_CYCLE_SERIES_INCOMPLETE",
                "CYCLICAL_COMMODITY_BASIS_MISMATCH",
                "CYCLICAL_CAPACITY_NOT_RECONCILED",
            ),
            "sources": (
                "sec-filing",
                "eia-open-data",
                "usgs-commodity-statistics",
                "usda-nass-quickstats",
            ),
            "evidence": (
                "issuer realized prices, volume, cost, and utilization from filings",
                "public commodity series mapped to the issuer's product and geography",
                "positive and negative through-cycle cohorts",
                "independent normalized margin and net-debt bridge",
            ),
            "assumption_policy": (
                "caller specifies cycle length, normalized price, volume, and "
                "unit-cost path"
            ),
            "formula_graph": "through-cycle-normalized-fcff-v1",
            "uncertainty_policy": (
                "caller supplies bounded commodity-price, volume, and unit-cost "
                "distributions"
            ),
            "calibration_targets": (
                "first-subsequent-realized-price-volume-and-cost-v1",
            ),
            "capital_bridge_policy": (
                "normalized-enterprise-value-minus-net-debt-and-dilution-v1"
            ),
            "valuation_basis": "enterprise",
            "economic_purpose": (
                "value a cyclical issuer on normalized through-cycle operations"
            ),
        },
        {
            "model_id": "biotech_rnpv",
            "archetype": "U.S. clinical-stage or commercial biotech issuer",
            "basis": "equity",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "biotech_asset_trial_phase",
                "biotech_primary_endpoint",
                "biotech_trial_status_date",
                "biotech_cash_runway",
                "biotech_diluted_shares",
            ),
            "forbidden_conditions": (
                "BIOTECH_TRIAL_STATUS_STALE",
                "BIOTECH_ENDPOINT_UNVERIFIED",
                "BIOTECH_PATENT_EXCLUSIVITY_UNKNOWN",
            ),
            "sources": ("sec-filing", "fda-drugs", "clinicaltrials-api"),
            "evidence": (
                "dated FDA and ClinicalTrials.gov records matched to the issuer's "
                "assets",
                "issuer cash runway, dilution, and patent disclosures",
                "positive and negative clinical-stage golden cohorts",
                "independent probability-of-success and launch-cost scenarios",
            ),
            "assumption_policy": (
                "caller supplies indication market, launch path, costs, and "
                "success probabilities"
            ),
            "formula_graph": "asset-level-risk-adjusted-npv-v1",
            "uncertainty_policy": (
                "caller supplies bounded trial-success and commercial-outcome "
                "distributions"
            ),
            "calibration_targets": ("first-subsequent-trial-outcome-by-phase-v1",),
            "capital_bridge_policy": (
                "asset-risk-adjusted-value-plus-cash-minus-debt-and-dilution-v1"
            ),
            "valuation_basis": "equity",
            "economic_purpose": (
                "value biotech assets with explicit clinical and commercial risk "
                "adjustment"
            ),
        },
        {
            "model_id": "sum_of_parts",
            "archetype": "U.S. multi-segment conglomerate",
            "basis": "asset",
            "profile_id": "us-gaap-public-v1",
            "required_fields": (
                "sotp_segment_financials",
                "sotp_segment_valuation_basis",
                "sotp_corporate_cost_allocation",
                "sotp_parent_debt_and_cash",
                "sotp_diluted_shares",
            ),
            "forbidden_conditions": (
                "SOTP_SEGMENT_ELIMINATIONS_UNRESOLVED",
                "SOTP_INTERCOMPANY_BALANCES_UNRESOLVED",
                "SOTP_PARENT_CLAIMS_UNALLOCATED",
            ),
            "sources": ("sec-filing", "sec-companyfacts"),
            "evidence": (
                "issuer segment disclosures and intersegment eliminations",
                "segment-specific peer or asset valuation method with dated evidence",
                "positive and negative conglomerate cohorts",
                "independent parent-debt, cash, and dilution bridge",
            ),
            "assumption_policy": (
                "caller supplies segment valuation assumptions and shared-cost "
                "allocation"
            ),
            "formula_graph": "segment-values-plus-parent-bridge-v1",
            "uncertainty_policy": (
                "caller supplies explicit segment-specific distributions and "
                "dependence assumptions"
            ),
            "calibration_targets": ("first-subsequent-segment-operating-results-v1",),
            "capital_bridge_policy": (
                "segment-sum-minus-intercompany-and-parent-claims-v1"
            ),
            "valuation_basis": "asset",
            "economic_purpose": (
                "value conglomerate common equity from independently valued "
                "operating segments"
            ),
        },
        {
            "model_id": "ifrs_fcff_dcf",
            "archetype": "IFRS-reporting non-financial operating issuer",
            "basis": "enterprise",
            "profile_id": "ifrs-public-v1",
            "required_fields": (
                "ifrs_revenue",
                "ifrs_operating_profit",
                "ifrs_cash",
                "ifrs_borrowings",
                "ifrs_diluted_shares",
            ),
            "forbidden_conditions": (
                "IFRS_TAXONOMY_MAPPING_UNVERIFIED",
                "IFRS_PRESENTATION_CURRENCY_MISMATCH",
                "IFRS_CASH_FLOW_CLASSIFICATION_UNRESOLVED",
            ),
            "sources": ("ifrs-taxonomy", "sec-filing"),
            "evidence": (
                "issuer filing with pinned IFRS taxonomy and mapping decisions",
                "IAS 7 cash-flow classification reconciliation",
                "positive and negative IFRS reporting cohorts",
                "independent enterprise-to-equity capital bridge",
            ),
            "assumption_policy": (
                "caller supplies explicit IFRS-mapped forecasts and discount "
                "assumptions"
            ),
            "formula_graph": "ifrs-fcff-dcf-v1",
            "uncertainty_policy": (
                "caller supplies bounded forecast and discount-rate distributions"
            ),
            "calibration_targets": (
                "first-subsequent-reported-ifrs-revenue-and-margin-v1",
            ),
            "capital_bridge_policy": (
                "ifrs-enterprise-value-plus-cash-minus-borrowings-and-dilution-v1"
            ),
            "valuation_basis": "enterprise",
            "economic_purpose": (
                "value IFRS-reporting non-financial operations without mixing "
                "GAAP mappings"
            ),
        },
    )
    return tuple(
        ModelSpecV1.model_validate(
            {
                "contract_version": "fundamental.v1",
                "model_id": family["model_id"],
                "model_version": f"{family['model_id']}-v1",
                "profile_id": family["profile_id"],
                "required_fields": family["required_fields"],
                "forbidden_conditions": family["forbidden_conditions"],
                "supported_archetypes": (family["archetype"],),
                "owner": "fundamental-service",
                "validator": "independent-model-validation",
                "lifecycle": "exploratory",
                "economic_purpose": family["economic_purpose"],
                "valuation_basis": family["valuation_basis"],
                "jurisdictions": ("US",),
                "accounting_bases": ("ifrs",)
                if family["model_id"] == "ifrs_fcff_dcf"
                else ("us-gaap",),
                "required_evidence": family["evidence"],
                "assumption_policy": family["assumption_policy"],
                "formula_graph": family["formula_graph"],
                "numerical_policy": VALUATION_NUMERICAL_POLICY,
                "eligibility_policy": "model-required-facts-forbidden-conditions-and-quality-v1",
                "abstention_policy": "abstain-on-any-required-evidence-or-entity-scope-failure-v1",
                "uncertainty_policy": family["uncertainty_policy"],
                "calibration_policy": "chronological-point-in-time-oos-before-promotion-v1",
                "calibration_targets": family["calibration_targets"],
                "calibration_required_for_promotion": True,
                "required_release_gates": (
                    "public-source-coverage",
                    "point-in-time-accounting",
                    "positive-negative-golden-cohorts",
                    "independent-node-challenger",
                    "calibration-oos",
                    "replay-reproducibility",
                ),
                "source_register": family["sources"],
                "capital_bridge_policy": family["capital_bridge_policy"],
                "golden_cohort": f"{family['model_id']}-positive-negative-golden-cohort-v1",
                "challenger": f"{family['model_id']}-independent-node-challenger-v1",
                "independent_validator": "independent-model-validation",
                "retirement_trigger": "source-loss-drift-validation-failure-or-expired-review-v1",
                "rollback_policy": "restore-last-promoted-release-manifest-and-replay-v1",
                "monitoring_policy": "monthly-source-health-drift-missingness-and-abstention-v1",
            }
        )
        for family in families
    )


def expansion_policy_records() -> tuple[PolicyRecordV1, ...]:
    """Versioned no-default policies identify families that remain unsupported."""

    policies: list[PolicyRecordV1] = []
    for model in expansion_model_specs():
        payload = {
            "contract_version": "fundamental.v1",
            "policy_id": f"{model.model_id}-{model.profile_id}",
            "policy_version": f"{model.model_version}-unsupported-v1",
            "profile_id": model.profile_id,
            "model_id": model.model_id,
            "model_version": model.model_version,
            "assumptions": None,
            "source_refs": (
                "fundamental-service/docs/fundamental-enterprise-grade-target-state.md#21.1",
            ),
            "effective_at": datetime(1970, 1, 1, tzinfo=UTC),
            "status": "active",
        }
        policies.append(
            PolicyRecordV1.model_validate(
                {**payload, "policy_digest": sha256_digest(payload)}
            )
        )
    return tuple(policies)
