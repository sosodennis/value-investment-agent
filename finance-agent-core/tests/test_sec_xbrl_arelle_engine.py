from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from src.agents.fundamental.infrastructure.sec_xbrl import extractor as extractor_module
from src.agents.fundamental.infrastructure.sec_xbrl.providers import (
    arelle_engine as arelle_engine_module,
)
from src.agents.fundamental.infrastructure.sec_xbrl.providers.arelle_engine import (
    ArelleEngineUnavailableError,
    ArelleParseResult,
    ArelleXbrlEngine,
)
from src.agents.fundamental.infrastructure.sec_xbrl.providers.engine_contracts import (
    ArelleRuntimeMetadata,
    ArelleValidationIssue,
    ArelleValidationProfile,
    XbrlAttachment,
    XbrlAttachmentBundle,
)


def _bundle() -> XbrlAttachmentBundle:
    return XbrlAttachmentBundle(
        ticker="AMZN",
        fiscal_year=2025,
        instance_document="amzn-20251231_htm.xml",
        attachments=(
            XbrlAttachment(
                document="amzn-20251231_htm.xml",
                document_type="EX-101.INS",
                description="XBRL INSTANCE DOCUMENT",
                content="<xbrli:xbrl/>",
            ),
        ),
    )


def test_arelle_engine_raises_unavailable_when_runtime_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        arelle_engine_module.importlib.util, "find_spec", lambda _n: None
    )
    engine = ArelleXbrlEngine()
    with pytest.raises(ArelleEngineUnavailableError):
        engine.parse_attachment_bundle(bundle=_bundle())


def test_arelle_engine_supports_injected_parser() -> None:
    expected_df = pd.DataFrame(
        [
            {
                "concept": "us-gaap:Assets",
                "value": "1",
                "period_key": "instant_2025-12-31",
            }
        ]
    )

    def _fake_parse(bundle: XbrlAttachmentBundle) -> ArelleParseResult:
        return ArelleParseResult(
            facts_dataframe=expected_df,
            instance_document=bundle.instance_document,
            loaded_attachment_count=len(bundle.attachments),
            schema_loaded=False,
            label_loaded=False,
            presentation_loaded=False,
            calculation_loaded=False,
            definition_loaded=False,
            validation_issues=(
                ArelleValidationIssue(
                    code="EFM.6.5.20",
                    source="EFM",
                    severity="warning",
                    message="sample issue",
                    concept="us-gaap:Assets",
                ),
            ),
            runtime_metadata=ArelleRuntimeMetadata(
                mode="facts_only",
                disclosure_system=None,
                plugins=(),
                packages=(),
                arelle_version="2.37.77",
                validation_enabled=False,
            ),
            parse_latency_ms=12.5,
        )

    engine = ArelleXbrlEngine(parse_bundle_fn=_fake_parse)
    result = engine.parse_attachment_bundle(bundle=_bundle())
    assert result.facts_dataframe.equals(expected_df)
    assert result.instance_document == "amzn-20251231_htm.xml"
    assert result.loaded_attachment_count == 1
    assert len(result.validation_issues) == 1
    assert result.validation_issues[0].code == "EFM.6.5.20"
    assert result.runtime_metadata is not None
    assert result.runtime_metadata.mode == "facts_only"
    assert result.parse_latency_ms == pytest.approx(12.5)


def test_arelle_validation_profile_defaults_to_facts_only(monkeypatch) -> None:
    monkeypatch.delenv("FUNDAMENTAL_XBRL_ARELLE_VALIDATION_MODE", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_XBRL_ARELLE_DISCLOSURE_SYSTEM", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_XBRL_ARELLE_PLUGINS", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_XBRL_ARELLE_PACKAGES", raising=False)

    profile = arelle_engine_module._resolve_validation_profile_from_env()
    assert profile == ArelleValidationProfile(
        mode="facts_only",
        disclosure_system=None,
        plugins=(),
        packages=(),
    )
    assert profile.validation_enabled is False


def test_arelle_validation_profile_reads_env_inputs(monkeypatch) -> None:
    monkeypatch.setenv("FUNDAMENTAL_XBRL_ARELLE_VALIDATION_MODE", "efm_dqc_validate")
    monkeypatch.setenv("FUNDAMENTAL_XBRL_ARELLE_DISCLOSURE_SYSTEM", "efm")
    monkeypatch.setenv(
        "FUNDAMENTAL_XBRL_ARELLE_PLUGINS",
        "validate/EFM, validate/XFsyntax",
    )
    monkeypatch.setenv(
        "FUNDAMENTAL_XBRL_ARELLE_PACKAGES",
        "sec-taxonomy-2025.zip, dqc-rules-2026.zip",
    )

    profile = arelle_engine_module._resolve_validation_profile_from_env()
    assert profile.mode == "efm_dqc_validate"
    assert profile.disclosure_system == "efm"
    assert profile.plugins == ("validate/EFM", "validate/XFsyntax")
    assert profile.packages == ("sec-taxonomy-2025.zip", "dqc-rules-2026.zip")
    assert profile.validation_enabled is True


def test_arelle_validation_profile_applies_mode_default_plugins(monkeypatch) -> None:
    monkeypatch.setenv("FUNDAMENTAL_XBRL_ARELLE_VALIDATION_MODE", "efm_validate")
    monkeypatch.delenv("FUNDAMENTAL_XBRL_ARELLE_PLUGINS", raising=False)
    monkeypatch.delenv("FUNDAMENTAL_XBRL_ARELLE_PACKAGES", raising=False)

    profile_efm = arelle_engine_module._resolve_validation_profile_from_env()
    assert profile_efm.plugins == ("validate/EFM",)

    monkeypatch.setenv("FUNDAMENTAL_XBRL_ARELLE_VALIDATION_MODE", "efm_dqc_validate")
    profile_dqc = arelle_engine_module._resolve_validation_profile_from_env()
    assert profile_dqc.plugins == ("validate/EFM", "validate/DQC")


def test_runtime_isolation_mode_defaults_to_serial(monkeypatch) -> None:
    monkeypatch.delenv("FUNDAMENTAL_XBRL_ARELLE_RUNTIME_ISOLATION", raising=False)
    mode = arelle_engine_module._resolve_runtime_isolation_mode_from_env()
    assert mode == "serial"


def test_runtime_isolation_mode_supports_none(monkeypatch) -> None:
    monkeypatch.setenv("FUNDAMENTAL_XBRL_ARELLE_RUNTIME_ISOLATION", "none")
    mode = arelle_engine_module._resolve_runtime_isolation_mode_from_env()
    assert mode == "none"


def test_configure_validation_runtime_loads_plugins_and_packages() -> None:
    class _FakeDisclosureSystem:
        def __init__(self) -> None:
            self.selected: str | None = None

        def select(self, value: str | None) -> None:
            self.selected = value

    class _FakeManager:
        def __init__(self) -> None:
            self.disclosureSystem = _FakeDisclosureSystem()
            self.validateDisclosureSystem = False

    class _FakePluginManager:
        def __init__(self) -> None:
            self.init_calls = 0
            self.loaded_plugins: list[str] = []

        def init(self, _controller: object, loadPluginConfig: bool = True) -> None:
            self.init_calls += 1
            assert loadPluginConfig is False

        def addPluginModule(self, name: str) -> dict[str, object]:
            self.loaded_plugins.append(name)
            return {"name": name}

    class _FakePackageManager:
        def __init__(self) -> None:
            self.init_calls = 0
            self.loaded_packages: list[str] = []

        def init(self, _controller: object, loadPackagesConfig: bool = True) -> None:
            self.init_calls += 1
            assert loadPackagesConfig is False

        def addPackage(
            self,
            _controller: object,
            url: str,
            packageManifestName: str | None = None,
        ) -> dict[str, object]:
            assert packageManifestName is None
            self.loaded_packages.append(url)
            return {"identifier": url}

    manager = _FakeManager()
    plugin_manager = _FakePluginManager()
    package_manager = _FakePackageManager()

    def _fake_import(module_name: str) -> object | None:
        if module_name == "arelle.PluginManager":
            return plugin_manager
        if module_name == "arelle.PackageManager":
            return package_manager
        return None

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        arelle_engine_module, "_import_arelle_runtime_module", _fake_import
    )
    try:
        arelle_engine_module._configure_validation_runtime(
            controller=object(),
            manager=manager,
            validation_profile=ArelleValidationProfile(
                mode="efm_dqc_validate",
                disclosure_system="efm",
                plugins=("validate/EFM", "validate/DQC"),
                packages=("sec-taxonomy-2025.zip",),
            ),
        )
    finally:
        monkeypatch.undo()

    assert manager.disclosureSystem.selected == "efm"
    assert manager.validateDisclosureSystem is True
    assert plugin_manager.init_calls == 1
    assert plugin_manager.loaded_plugins == ["validate/EFM", "validate/DQC"]
    assert package_manager.init_calls == 1
    assert package_manager.loaded_packages == ["sec-taxonomy-2025.zip"]


def test_configure_validation_runtime_fails_when_plugin_load_fails() -> None:
    class _FakeDisclosureSystem:
        def select(self, _value: str | None) -> None:
            return

    class _FakeManager:
        def __init__(self) -> None:
            self.disclosureSystem = _FakeDisclosureSystem()
            self.validateDisclosureSystem = False

    class _FailingPluginManager:
        def init(self, _controller: object, loadPluginConfig: bool = True) -> None:
            assert loadPluginConfig is False

        def addPluginModule(self, _name: str) -> None:
            return None

    manager = _FakeManager()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        arelle_engine_module,
        "_import_arelle_runtime_module",
        lambda module_name: _FailingPluginManager()
        if module_name == "arelle.PluginManager"
        else None,
    )
    try:
        with pytest.raises(RuntimeError, match="validation plugin load failed"):
            arelle_engine_module._configure_validation_runtime(
                controller=object(),
                manager=manager,
                validation_profile=ArelleValidationProfile(
                    mode="efm_validate",
                    disclosure_system="efm",
                    plugins=("validate/EFM",),
                    packages=(),
                ),
            )
    finally:
        monkeypatch.undo()


def test_collect_validation_issues_normalizes_model_error_codes() -> None:
    class _ModelXbrl:
        errors = ["EFM.6.05.20", "DQC.US.0001", "xbrl.5.2.4.2", "EFM.6.05.20"]

    issues = arelle_engine_module._collect_validation_issues(_ModelXbrl())
    assert [issue.code for issue in issues] == [
        "EFM.6.05.20",
        "DQC.US.0001",
        "xbrl.5.2.4.2",
    ]
    assert [issue.source for issue in issues] == ["EFM", "DQC", "ARELLE"]
    assert all(issue.severity == "error" for issue in issues)


def test_collect_validation_issues_handles_mapping_and_sequence_entries() -> None:
    class _ModelXbrl:
        errors = [
            {
                "code": "DQC.US.0015",
                "message": "IncomeBeforeTax context mismatch",
                "severity": "critical",
                "concept": "us-gaap:IncomeBeforeTax",
                "contextId": "ctx_2025",
            },
            ("EFM.6.05.20", "warning: invalid context"),
            {
                "code": "DQC.US.0015",
                "message": "IncomeBeforeTax context mismatch",
                "severity": "critical",
                "concept": "us-gaap:IncomeBeforeTax",
                "contextId": "ctx_2025",
            },
        ]

    issues = arelle_engine_module._collect_validation_issues(_ModelXbrl())
    assert len(issues) == 2

    first = issues[0]
    assert first.code == "DQC.US.0015"
    assert first.source == "DQC"
    assert first.severity == "critical"
    assert first.field_key == "income_before_tax"
    assert first.context_id == "ctx_2025"

    second = issues[1]
    assert second.code == "EFM.6.05.20"
    assert second.source == "EFM"
    assert second.severity == "warning"


@dataclass
class _FakeAttachment:
    document: str
    document_type: str
    description: str
    extension: str
    content: str


@dataclass
class _FakeAttachments:
    data_files: list[object]


@dataclass
class _FakeFiling:
    attachments: _FakeAttachments


def test_extractor_prefers_arelle_candidate_when_available(monkeypatch) -> None:
    candidate_df = pd.DataFrame(
        [
            {
                "concept": "us-gaap:Assets",
                "value": "123",
                "period_key": "instant_2025-12-31",
            }
        ]
    )

    class _FakeArelleEngine:
        def parse_attachment_bundle(
            self, *, bundle: XbrlAttachmentBundle
        ) -> ArelleParseResult:
            return ArelleParseResult(
                facts_dataframe=candidate_df,
                instance_document=bundle.instance_document,
                loaded_attachment_count=len(bundle.attachments),
                schema_loaded=True,
                label_loaded=True,
                presentation_loaded=True,
                calculation_loaded=True,
                definition_loaded=True,
            )

    monkeypatch.setattr(extractor_module, "ArelleXbrlEngine", _FakeArelleEngine)

    filing = _FakeFiling(
        attachments=_FakeAttachments(
            data_files=[
                _FakeAttachment(
                    document="amzn-20251231.xsd",
                    document_type="EX-101.SCH",
                    description="schema",
                    extension=".xsd",
                    content="<xsd:schema/>",
                ),
                _FakeAttachment(
                    document="amzn-20251231_htm.xml",
                    document_type="EX-101.INS",
                    description="XBRL INSTANCE DOCUMENT",
                    extension=".xml",
                    content="<xbrli:xbrl/>",
                ),
            ]
        )
    )

    result = extractor_module._build_dataframe_from_filing_attachments(
        filing=filing,
        ticker="AMZN",
        fiscal_year=2025,
    )
    assert result is not None
    dataframe, instance_document, metadata = result
    assert instance_document == "amzn-20251231_htm.xml"
    assert int(len(dataframe)) == 1
    assert metadata["arelle_validation_issue_count"] == 0
    assert metadata["arelle_validation_issues"] == []


def test_extractor_hard_fails_when_arelle_unavailable(
    monkeypatch,
) -> None:
    class _UnavailableArelleEngine:
        def parse_attachment_bundle(self, *, bundle: XbrlAttachmentBundle) -> object:
            raise ArelleEngineUnavailableError(
                f"Arelle unavailable for {bundle.instance_document}"
            )

    monkeypatch.setattr(extractor_module, "ArelleXbrlEngine", _UnavailableArelleEngine)

    filing = _FakeFiling(
        attachments=_FakeAttachments(
            data_files=[
                _FakeAttachment(
                    document="amzn-20251231.xsd",
                    document_type="EX-101.SCH",
                    description="schema",
                    extension=".xsd",
                    content="<xsd:schema/>",
                ),
                _FakeAttachment(
                    document="amzn-20251231_htm.xml",
                    document_type="EX-101.INS",
                    description="XBRL INSTANCE DOCUMENT",
                    extension=".xml",
                    content="<xbrli:xbrl/>",
                ),
            ]
        )
    )

    with pytest.raises(ArelleEngineUnavailableError):
        extractor_module._build_dataframe_from_filing_attachments(
            filing=filing,
            ticker="AMZN",
            fiscal_year=2025,
        )
