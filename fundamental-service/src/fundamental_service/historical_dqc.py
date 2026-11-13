"""Execute pinned official historical DQC hooks without changing their rules."""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from arelle.Cntlr import Cntlr
    from arelle.CntlrCmdLine import CntlrCmdLine, ParserForDynamicPlugins
    from arelle.RuntimeOptions import RuntimeOptions
    from arelle.ValidateXbrl import ValidateXbrl

HISTORICAL_PROFILE_ID = "sec-efm-us-dqc-v1.0.0-historical"
OFFICIAL_SOURCE_COMMIT = "266946cdecddf37c3d7d43b258eecb945a2daed3"
OFFICIAL_SOURCE_SHA256 = (
    "771ac2f5630e01e646a68b6730f6b4ae78e38e2e80db4a3b36608faf7dfd2301"
)
OFFICIAL_MODULES = (
    "dqc_us_0004",
    "dqc_us_0005",
    "dqc_us_0006",
    "dqc_us_0009",
    "dqc_us_0015",
    "dqc_us_0033_0036",
)
GAAP_NAMESPACES = frozenset(
    f"http://fasb.org/us-gaap/{year}-01-31" for year in range(2012, 2016)
)
DEI_NAMESPACES = frozenset(
    (
        "http://xbrl.us/dei/2009-01-31",
        *(f"http://xbrl.sec.gov/dei/{year}-01-31" for year in range(2011, 2015)),
    )
)
HISTORICAL_V3_PROFILE_ID = "sec-efm-us-dqc-v3.6.2-historical"


@dataclass(frozen=True)
class HistoricalDqcProfile:
    profile_id: str
    dqc_version: str
    source_commit: str
    source_sha256: str
    modules: tuple[str, ...]
    gaap_namespaces: frozenset[str]
    dei_namespaces: frozenset[str]
    completion_marker: str
    axis_config_sha256: str | None = None


V1_PROFILE = HistoricalDqcProfile(
    HISTORICAL_PROFILE_ID,
    "v1.0.0",
    OFFICIAL_SOURCE_COMMIT,
    OFFICIAL_SOURCE_SHA256,
    OFFICIAL_MODULES,
    GAAP_NAMESPACES,
    DEI_NAMESPACES,
    "dqc-historical-v1-all-six-modules-returned",
)
V3_PROFILE = HistoricalDqcProfile(
    HISTORICAL_V3_PROFILE_ID,
    "v3.6.2",
    "cafb54391c1d21e4c219bc3d491b855a9b877cb6",
    "84a53e0c4e6e6f9300644978e4ce4884f8d34243a735434f3b36a841c3a28aaa",
    (
        "dqc_us_0001",
        "dqc_us_0004",
        "dqc_us_0005",
        "dqc_us_0006",
        "dqc_us_0009",
        "dqc_us_0013",
        "dqc_us_0014",
        "dqc_us_0015",
        "dqc_us_0018",
        "dqc_us_0033_0036",
        "dqc_us_0041",
    ),
    frozenset(f"http://fasb.org/us-gaap/{year}-01-31" for year in range(2012, 2018)),
    DEI_NAMESPACES,
    "dqc-historical-v3.6.2-all-eleven-modules-returned",
)

# A configuration adaptation, not an upstream DQC release or compliance opinion.
V3_2013_PROFILE = replace(
    V3_PROFILE,
    profile_id="sec-efm-us-dqc-v3.6.2-gaap2013-config-v1",
    dqc_version="v3.6.2-gaap2013-config-v1",
    gaap_namespaces=frozenset({"http://fasb.org/us-gaap/2013-01-31"}),
    completion_marker="dqc-v3.6.2-gaap2013-config-v1-all-eleven-modules-returned",
    axis_config_sha256="baf022187417e3d5f8d579942323d9d77e848d4f14909cccdecc43c4f81007a2",
)


def historical_profile(profile_id: str) -> HistoricalDqcProfile | None:
    return {
        V1_PROFILE.profile_id: V1_PROFILE,
        V3_PROFILE.profile_id: V3_PROFILE,
        V3_2013_PROFILE.profile_id: V3_2013_PROFILE,
    }.get(profile_id)


_STATE_ATTRIBUTE = "fundamental_historical_dqc_execution"


@dataclass
class HistoricalDqcExecution:
    root: Path
    profile: HistoricalDqcProfile = V1_PROFILE
    returned_modules: list[str] = field(default_factory=list)
    unsupported_namespaces: tuple[str, ...] = ()
    failed: bool = False
    axis_config_path: Path | None = None

    @property
    def completed(self) -> bool:
        return (
            not self.failed
            and not self.unsupported_namespaces
            and tuple(self.returned_modules) == self.profile.modules
        )


def execution_for(controller: Cntlr) -> HistoricalDqcExecution | None:
    state = getattr(controller, _STATE_ATTRIBUTE, None)
    return state if isinstance(state, HistoricalDqcExecution) else None


def options(parser: ParserForDynamicPlugins) -> None:
    parser.add_option(
        "--fundamental-historical-dqc-root",
        action="store",
        dest="fundamental_historical_dqc_root",
    )
    parser.add_option(
        "--fundamental-historical-dqc-profile",
        action="store",
        dest="fundamental_historical_dqc_profile",
    )
    parser.add_option(
        "--fundamental-historical-dqc-axis-config",
        action="store",
        dest="fundamental_historical_dqc_axis_config",
    )


def initialize(
    controller: CntlrCmdLine, runtime: RuntimeOptions, **kwargs: object
) -> None:
    root = getattr(runtime, "fundamental_historical_dqc_root", None)
    if not isinstance(root, str) or not root:
        raise ValueError("historical DQC source directory is required")
    selected = historical_profile(
        getattr(runtime, "fundamental_historical_dqc_profile", None)
        or HISTORICAL_PROFILE_ID
    )
    if selected is None:
        raise ValueError("unknown historical DQC profile")
    config = getattr(runtime, "fundamental_historical_dqc_axis_config", None)
    config_path = Path(config) if isinstance(config, str) and config else None
    verify_axis_config(selected, config_path)
    setattr(
        controller,
        _STATE_ATTRIBUTE,
        HistoricalDqcExecution(
            root=Path(root), profile=selected, axis_config_path=config_path
        ),
    )


def verify_axis_config(profile: HistoricalDqcProfile, path: Path | None) -> None:
    if profile.axis_config_sha256 is None:
        if path is not None:
            raise ValueError("selected DQC profile does not accept an axis config")
        return
    if path is None or not path.is_file():
        raise ValueError("selected DQC profile requires its pinned axis config")
    if hashlib.sha256(path.read_bytes()).hexdigest() != profile.axis_config_sha256:
        raise ValueError("historical DQC axis config hash does not match")


def _run_official_hook(
    package: ModuleType,
    name: str,
    validation: ValidateXbrl,
    state: HistoricalDqcExecution,
) -> None:
    hook = _official_hook(package, name)
    if name != "dqc_us_0001" or state.profile.axis_config_sha256 is None:
        hook(validation)
        return
    verify_axis_config(state.profile, state.axis_config_path)
    module = importlib.import_module(f"{package.__name__}.{name}")
    original_selector = getattr(module, "_determine_namespace")
    # The parser runs each filing in its own worker. Route only configuration;
    # the pinned official rule, messages and severity are left intact.
    setattr(module, "_determine_namespace", lambda value: str(state.axis_config_path))
    try:
        hook(validation)
    finally:
        setattr(module, "_determine_namespace", original_selector)


def _load_package(root: Path) -> ModuleType:
    name = (
        "_fundamental_official_dqc_"
        + hashlib.sha256(str(root.resolve()).encode()).hexdigest()
    )
    cached = sys.modules.get(name)
    if cached is not None:
        if Path(cached.__file__ or "").resolve() != (root / "__init__.py").resolve():
            raise ValueError("a different historical DQC package is already loaded")
        return cached
    spec = importlib.util.spec_from_file_location(
        name, root / "__init__.py", submodule_search_locations=[str(root)]
    )
    if spec is None or spec.loader is None:
        raise ValueError("historical DQC package cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        sys.modules.pop(name, None)
        raise
    return module


def _official_hook(package: ModuleType, name: str) -> Callable[[ValidateXbrl], None]:
    module = importlib.import_module(f"{package.__name__}.{name}")
    info = getattr(module, "__pluginInfo__", None)
    if not isinstance(info, dict):
        raise ValueError(f"historical DQC module has no plugin metadata: {name}")
    hook = info.get("Validate.XBRL.Finally")
    if not callable(hook):
        raise ValueError(f"historical DQC module has no validation hook: {name}")
    return hook


def validate(validation: ValidateXbrl) -> None:
    model = validation.modelXbrl
    state = execution_for(model.modelManager.cntlr)
    if state is None:
        raise ValueError("historical DQC execution was not initialized")
    namespaces = set(model.namespaceDocs)
    gaap = {name for name in namespaces if name.startswith("http://fasb.org/us-gaap/")}
    dei = {
        name
        for name in namespaces
        if name.startswith(("http://xbrl.sec.gov/dei/", "http://xbrl.us/dei/"))
    }
    state.unsupported_namespaces = tuple(
        sorted(
            (gaap - state.profile.gaap_namespaces)
            | (dei - state.profile.dei_namespaces)
        )
    )
    if not gaap or state.unsupported_namespaces:
        state.failed = True
        return
    original_log = model.log

    def observed_log(level: str, codes: object, msg: str, **args: object) -> None:
        if isinstance(codes, str) and codes.startswith("DQC."):
            args["fundamental_rule_severity"] = level.lower()
        original_log(level, codes, msg, **args)

    model.log = observed_log
    try:
        package = _load_package(state.root)
        for name in state.profile.modules:
            _run_official_hook(package, name, validation, state)
            state.returned_modules.append(name)
    except BaseException:
        state.failed = True
        raise
    finally:
        model.log = original_log
