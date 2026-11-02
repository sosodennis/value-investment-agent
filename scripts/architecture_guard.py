#!/usr/bin/env python3
"""Check agent package boundaries and capability dependency cycles."""

from __future__ import annotations

import argparse
import ast
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "finance-agent-core" / "src"
API_ROOT = REPO_ROOT / "finance-agent-core" / "api"
EXCEPTIONS_DIR = REPO_ROOT / "scripts" / "architecture_guard_exceptions"
REPORT_PATH = (
    REPO_ROOT
    / "finance-agent-core"
    / "src"
    / "agents"
    / "ARCHITECTURE_MODULE_ACTIONS.md"
)
DEPENDENCY_REPORT_PATH = (
    REPO_ROOT / "docs" / "refactor-map" / "architecture-dependency-report.md"
)

LEGACY_WORKFLOW_AGENTS = {
    "debate": "debate",
    "fundamental_analysis": "fundamental",
    "financial_news_research": "news",
    "intent_extraction": "intent",
    "technical_analysis": "technical",
}
CAPABILITY_ROOTS = ("capabilities", "subdomains")
LAYERS = {
    "application",
    "composition",
    "domain",
    "entrypoint",
    "infrastructure",
    "interface",
    "workflow",
}
PUBLIC_CAPABILITY_MODULES = {"api", "contracts", "public"}
INDEPENDENT_CAPABILITIES = {"llm_provider"}


@dataclass(frozen=True)
class ModuleOwner:
    agent: str | None = None
    capability: str | None = None
    layer: str | None = None


@dataclass(frozen=True)
class ImportRef:
    source: str
    target: str
    file: str
    line: int


@dataclass(frozen=True)
class Violation:
    rule: str
    source: str
    target: str
    file: str
    line: int
    message: str

    def key(self) -> str:
        return f"{self.rule}|{self.source}|{self.target}"


def module_name_from_path(
    path: Path,
    src_root: Path = SRC_ROOT,
    *,
    module_prefix: str = "src",
) -> str:
    parts = list(path.relative_to(src_root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return module_prefix + ("." + ".".join(parts) if parts else "")


def resolve_import(
    module_name: str, node: ast.ImportFrom, *, is_package_init: bool
) -> str | None:
    if node.level == 0:
        return node.module

    current_package = module_name if is_package_init else module_name.rsplit(".", 1)[0]
    package_parts = current_package.split(".")
    pop_count = node.level - 1
    if pop_count > len(package_parts):
        return None
    base = package_parts[: len(package_parts) - pop_count]
    if node.module:
        return ".".join(base + node.module.split("."))
    return ".".join(base)


def _module_exists(module_name: str, src_root: Path) -> bool:
    parts = module_name.split(".")[1:]
    module_path = src_root.joinpath(*parts)
    return (
        module_path.with_suffix(".py").is_file()
        or (module_path / "__init__.py").is_file()
        or module_path.is_dir()
    )


def extract_imports(
    path: Path,
    src_root: Path = SRC_ROOT,
    *,
    source_root: Path | None = None,
    module_prefix: str = "src",
) -> list[ImportRef]:
    source = module_name_from_path(
        path,
        source_root or src_root,
        module_prefix=module_prefix,
    )
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imports: list[ImportRef] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(
                ImportRef(source, alias.name, str(path), node.lineno)
                for alias in node.names
            )
        elif isinstance(node, ast.ImportFrom):
            base_target = resolve_import(
                source,
                node,
                is_package_init=path.name == "__init__.py",
            )
            if base_target:
                for alias in node.names:
                    child_target = f"{base_target}.{alias.name}"
                    target = (
                        child_target
                        if alias.name != "*" and _module_exists(child_target, src_root)
                        else base_target
                    )
                    imports.append(ImportRef(source, target, str(path), node.lineno))
    return imports


def collect_imports(
    src_root: Path = SRC_ROOT,
    api_root: Path | None = None,
) -> list[ImportRef]:
    imports = [
        ref
        for path in sorted(src_root.rglob("*.py"))
        for ref in extract_imports(path, src_root)
    ]
    if api_root is None and src_root == SRC_ROOT:
        api_root = API_ROOT
    if api_root is not None and api_root.exists():
        imports.extend(
            ref
            for path in sorted(api_root.rglob("*.py"))
            for ref in extract_imports(
                path,
                src_root,
                source_root=api_root,
                module_prefix="api",
            )
        )
    return imports


def _is_migration_module_path(module_name: str) -> bool:
    parts = module_name.split(".")
    if parts[:2] == ["src", "agents"] and "subdomains" in parts[3:]:
        return True
    if parts[:3] == ["src", "workflow", "nodes"] and len(parts) >= 4 and parts[3]:
        return True
    return (
        parts[:2] == ["src", "agents"]
        and len(parts) >= 5
        and parts[3:5] == ["application", "subgraph"]
    )


def _migration_path_violations(src_root: Path) -> list[Violation]:
    violations: dict[str, Violation] = {}
    for path in sorted(src_root.rglob("*.py")):
        module_name = module_name_from_path(path, src_root)
        if not _is_migration_module_path(module_name):
            continue
        violation = Violation(
            rule="MIGRATION_PATH",
            source=module_name,
            target=module_name,
            file=str(path),
            line=1,
            message="migration-only package paths must be removed after callers move",
        )
        violations.setdefault(violation.key(), violation)
    return list(violations.values())


def classify_module(module_name: str) -> ModuleOwner:
    parts = module_name.split(".")
    if parts[0] == "api":
        return ModuleOwner(layer="api_composition")
    if len(parts) >= 3 and parts[:2] == ["src", "llm_provider"]:
        remainder = parts[2:]
        layer = remainder[0] if remainder and remainder[0] in LAYERS else None
        if layer == "application" and len(remainder) > 1:
            if remainder[1] in {"composition", "wiring"}:
                layer = "composition"
        return ModuleOwner(
            agent="llm_provider",
            capability="llm_provider",
            layer=layer,
        )
    if parts[:3] == ["src", "workflow", "nodes"] and len(parts) >= 4:
        agent = LEGACY_WORKFLOW_AGENTS.get(parts[3])
        if agent:
            return ModuleOwner(agent=agent, layer="workflow")
    if parts[:2] == ["src", "workflow"]:
        return ModuleOwner(layer="root_workflow")

    if parts[:2] != ["src", "agents"] or len(parts) < 3:
        return ModuleOwner()

    agent = parts[2]
    if len(parts) == 3:
        return ModuleOwner(agent=agent)

    remainder = parts[3:]
    capability: str | None = None
    if len(remainder) >= 2 and remainder[0] in CAPABILITY_ROOTS:
        capability = remainder[1]
        remainder = remainder[2:]

    layer = remainder[0] if remainder and remainder[0] in LAYERS else None
    if layer == "application" and len(remainder) > 1:
        if remainder[1] in {"composition", "wiring"}:
            layer = "composition"
    if layer == "entrypoint":
        layer = "entrypoint"
    return ModuleOwner(agent=agent, capability=capability, layer=layer)


def _is_agent_entrypoint(module_name: str, agent: str) -> bool:
    return module_name in {
        f"src.agents.{agent}.entrypoint",
        f"src.{agent}.entrypoint",
    }


def _is_own_entrypoint_wiring_import(
    ref: ImportRef, source: ModuleOwner, target: ModuleOwner
) -> bool:
    return (
        source.layer == "entrypoint"
        and target.layer == "composition"
        and source.agent is not None
        and source.agent == target.agent
        and _is_agent_entrypoint(ref.source, source.agent)
        and ref.target
        in {
            f"src.agents.{source.agent}.application.wiring",
            f"src.{source.agent}.application.wiring",
        }
    )


def _is_capability_facade(module_name: str, agent: str, capability: str) -> bool:
    for root in CAPABILITY_ROOTS:
        package = f"src.agents.{agent}.{root}.{capability}"
        if module_name == package:
            return True
        if module_name.startswith(package + "."):
            suffix = module_name[len(package) + 1 :].split(".")
            return len(suffix) == 1 and suffix[0] in PUBLIC_CAPABILITY_MODULES
    return False


def _is_shared_or_interface_module(module_name: str) -> bool:
    return any(
        module_name == prefix or module_name.startswith(prefix + ".")
        for prefix in ("src.shared", "src.interface")
    )


def _is_api_private_import(ref: ImportRef, target: ModuleOwner) -> bool:
    if target.layer == "root_workflow":
        return True
    if target.agent and not _is_agent_entrypoint(ref.target, target.agent):
        return True
    if ref.target == "src.services" or ref.target.startswith("src.services."):
        return True
    if ref.target == "src.interface" or ref.target.startswith("src.interface."):
        return ref.target != "src.interface.origins"
    return False


def _layer_violation(source: ModuleOwner, target: ModuleOwner) -> str | None:
    forbidden_targets = {
        "domain": {
            "application",
            "infrastructure",
            "interface",
            "workflow",
            "root_workflow",
            "entrypoint",
            "composition",
        },
        "application": {
            "infrastructure",
            "workflow",
            "root_workflow",
            "entrypoint",
            "composition",
        },
        "interface": {
            "application",
            "infrastructure",
            "workflow",
            "root_workflow",
            "entrypoint",
            "composition",
        },
        "workflow": {
            "infrastructure",
            "root_workflow",
            "entrypoint",
            "composition",
        },
        "infrastructure": {
            "workflow",
            "root_workflow",
            "entrypoint",
            "composition",
        },
        "entrypoint": {
            "infrastructure",
            "root_workflow",
            "composition",
        },
        "composition": {"root_workflow"},
    }
    if source.layer and target.layer in forbidden_targets.get(source.layer, set()):
        return f"{source.layer} must not import {target.layer}"
    return None


def _make_violation(
    ref: ImportRef,
    rule: str,
    message: str,
    *,
    source: str | None = None,
    target: str | None = None,
) -> Violation:
    return Violation(
        rule=rule,
        source=source or ref.source,
        target=target or ref.target,
        file=ref.file,
        line=ref.line,
        message=message,
    )


def _strongly_connected_components(
    graph: dict[tuple[str, str], set[tuple[str, str]]],
) -> list[set[tuple[str, str]]]:
    index = 0
    indexes: dict[tuple[str, str], int] = {}
    lowlinks: dict[tuple[str, str], int] = {}
    stack: list[tuple[str, str]] = []
    on_stack: set[tuple[str, str]] = set()
    components: list[set[tuple[str, str]]] = []

    def visit(node: tuple[str, str]) -> None:
        nonlocal index
        indexes[node] = index
        lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)

        for neighbor in graph.get(node, set()):
            if neighbor not in indexes:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[neighbor])

        if lowlinks[node] == indexes[node]:
            component: set[tuple[str, str]] = set()
            while True:
                member = stack.pop()
                on_stack.remove(member)
                component.add(member)
                if member == node:
                    break
            components.append(component)

    nodes = set(graph)
    for neighbors in graph.values():
        nodes.update(neighbors)
    for node in sorted(nodes):
        if node not in indexes:
            visit(node)
    return components


def collect_violations(
    src_root: Path = SRC_ROOT,
    api_root: Path | None = None,
) -> list[Violation]:
    refs = collect_imports(src_root, api_root)
    violations: dict[str, Violation] = {}
    capability_graph: dict[tuple[str, str], set[tuple[str, str]]] = defaultdict(set)
    capability_edges: dict[tuple[tuple[str, str], tuple[str, str]], list[ImportRef]] = (
        defaultdict(list)
    )

    def add(violation: Violation) -> None:
        violations.setdefault(violation.key(), violation)

    for violation in _migration_path_violations(src_root):
        add(violation)

    for ref in refs:
        source = classify_module(ref.source)
        target = classify_module(ref.target)

        if source.layer == "api_composition" and _is_api_private_import(ref, target):
            add(
                _make_violation(
                    ref,
                    "API_COMPOSITION_PRIVATE_IMPORT",
                    "FastAPI composition must import public entrypoints and owned boundary contracts only",
                )
            )

        if source.layer == "root_workflow" and target.agent:
            if not _is_agent_entrypoint(ref.target, target.agent):
                add(
                    _make_violation(
                        ref,
                        "ROOT_WORKFLOW_PRIVATE_IMPORT",
                        "root workflow must import an agent entrypoint only",
                    )
                )

        if source.agent and target.agent and source.agent != target.agent:
            if not _is_agent_entrypoint(ref.target, target.agent):
                add(
                    _make_violation(
                        ref,
                        "CROSS_AGENT_PRIVATE_IMPORT",
                        "agent-to-agent imports must use the target entrypoint or shared contracts",
                    )
                )

        if _is_shared_or_interface_module(ref.source) and target.agent:
            add(
                _make_violation(
                    ref,
                    "SHARED_IMPORTS_AGENT",
                    "shared and external interface modules must not depend on agent packages",
                )
            )

        if source.agent and (
            source.agent == target.agent or target.layer == "root_workflow"
        ):
            layer_message = _layer_violation(source, target)
            if layer_message and not _is_own_entrypoint_wiring_import(
                ref, source, target
            ):
                if (
                    source.agent == "llm_provider"
                    and source.layer == "entrypoint"
                    and ref.target == "src.llm_provider.composition.routes"
                ):
                    continue
                add(_make_violation(ref, "LAYER_DIRECTION", layer_message))

        if source.agent and source.agent == target.agent:
            if target.capability and source.capability != target.capability:
                if not _is_capability_facade(
                    ref.target, target.agent, target.capability
                ):
                    add(
                        _make_violation(
                            ref,
                            "CAPABILITY_PRIVATE_IMPORT",
                            "capability consumers must use the capability facade or public contracts",
                        )
                    )

            if (
                source.capability
                and target.capability
                and source.capability != target.capability
            ):
                source_capability = (source.agent, source.capability)
                target_capability = (target.agent, target.capability)
                capability_graph[source_capability].add(target_capability)
                capability_edges[(source_capability, target_capability)].append(ref)

        if source.agent and (
            ref.target == "src.services"
            or ref.target.startswith("src.services.")
            or ref.target == "src.interface"
            or ref.target.startswith("src.interface.")
        ):
            add(
                _make_violation(
                    ref,
                    "CROSS_SLICE_PRIVATE_IMPORT",
                    "agent code must use shared contracts instead of private root implementations",
                )
            )

    for component in _strongly_connected_components(capability_graph):
        if len(component) < 2:
            continue
        for (source_cap, target_cap), edge_refs in capability_edges.items():
            if source_cap not in component or target_cap not in component:
                continue
            for ref in edge_refs:
                add(
                    _make_violation(
                        ref,
                        "CAPABILITY_CYCLE",
                        "capability dependency participates in a cycle",
                        source=_capability_package_path(source_cap, src_root),
                        target=_capability_package_path(target_cap, src_root),
                    )
                )

    return sorted(
        violations.values(),
        key=lambda item: (item.rule, item.source, item.target, item.file, item.line),
    )


def _capability_package_path(owner: tuple[str, str], src_root: Path) -> str:
    agent, capability = owner
    for root in CAPABILITY_ROOTS:
        candidate = f"src.agents.{agent}.{root}.{capability}"
        if src_root.joinpath(*candidate.split(".")[1:]).is_dir():
            return candidate
    return f"src.agents.{agent}.capabilities.{capability}"


def load_exceptions(path: Path = EXCEPTIONS_DIR) -> dict[str, str]:
    if not path.exists():
        return {}
    if not path.is_dir():
        raise ValueError(
            f"Architecture exceptions must be stored in a directory: {path}"
        )
    unexpected = sorted(
        item.name for item in path.iterdir() if item.is_file() and item.suffix != ".tsv"
    )
    if unexpected:
        raise ValueError(
            f"Unexpected files in architecture exception directory: {unexpected}"
        )

    exceptions: dict[str, str] = {}
    for shard in sorted(path.glob("*.tsv")):
        for line_number, line in enumerate(
            shard.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            parts = stripped.split("|")
            if len(parts) != 4 or not all(parts):
                raise ValueError(f"Malformed exception at {shard}:{line_number}")
            rule, source, target, action = parts
            key = f"{rule}|{source}|{target}"
            expected_shard = f"{source}.tsv"
            if shard.name != expected_shard:
                raise ValueError(
                    f"Exception at {shard}:{line_number} belongs in {expected_shard}"
                )
            if key in exceptions:
                raise ValueError(f"Duplicate exception at {shard}:{line_number}: {key}")
            exceptions[key] = action
    return exceptions


def action_id_for_module(module_name: str) -> str:
    if module_name.startswith("src.workflow"):
        return "ROOT-WORKFLOW"
    if module_name.startswith(("src.shared", "src.interface")):
        return "SHARED-BOUNDARY"

    owner = classify_module(module_name)
    if owner.agent and owner.capability:
        capability = re.sub(r"[^A-Z0-9]+", "-", owner.capability.upper()).strip("-")
        return f"{owner.agent.upper()}-CAP-{capability}"
    if owner.agent:
        return f"{owner.agent.upper()}-CORE"
    return "UNSCOPED"


def load_action_ids(path: Path = REPORT_PATH) -> set[str]:
    if not path.exists():
        return set()
    action_pattern = re.compile(r"^### \[([A-Z0-9-]+)\] ", re.MULTILINE)
    return set(action_pattern.findall(path.read_text(encoding="utf-8")))


def validate_exception_actions(
    exceptions: dict[str, str], action_ids: set[str]
) -> list[str]:
    errors: list[str] = []
    for key, action_id in sorted(exceptions.items()):
        _, source, _ = key.split("|", maxsplit=2)
        expected_action = action_id_for_module(source)
        if action_id != expected_action:
            errors.append(
                f"{key} maps to {action_id}, expected {expected_action} for its source module"
            )
        elif action_id not in action_ids:
            errors.append(f"{key} references missing report action {action_id}")
    return errors


def _remediation_for(rule: str) -> str:
    return {
        "API_COMPOSITION_PRIVATE_IMPORT": (
            "Move behavior behind the agent's public entrypoint or an owned route."
        ),
        "CROSS_SLICE_PRIVATE_IMPORT": (
            "Move the shared contract to `src/shared/` or use the owning public entrypoint."
        ),
        "MIGRATION_PATH": (
            "Move callers to the current workflow or capability owner, then delete this path."
        ),
        "ROOT_WORKFLOW_PRIVATE_IMPORT": (
            "Route root graph composition through the agent's public entrypoint."
        ),
        "CROSS_AGENT_PRIVATE_IMPORT": (
            "Depend on the target agent entrypoint or move the stable contract to shared."
        ),
        "SHARED_IMPORTS_AGENT": (
            "Move the shared contract out of the agent package or invert the dependency."
        ),
        "LAYER_DIRECTION": (
            "Move the dependency behind an inward-facing contract or relocate the behavior."
        ),
        "CAPABILITY_PRIVATE_IMPORT": (
            "Expose the required contract through the capability facade."
        ),
        "CAPABILITY_CYCLE": (
            "Break the capability cycle through a stable contract or workflow orchestration."
        ),
    }.get(rule, "Review the dependency against the canonical architecture standard.")


def write_module_report(violations: list[Violation], path: Path = REPORT_PATH) -> None:
    grouped: dict[str, dict[str, list[Violation]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for violation in violations:
        grouped[action_id_for_module(violation.source)][violation.source].append(
            violation
        )

    lines = [
        "# Architecture Module Actions",
        "",
        "Generated from `scripts/architecture_guard.py --write-module-report`.",
        "Each item identifies a source module, exact import target, and first remediation action.",
        "Resolve items within their module, then remove the matching edge from its",
        "`scripts/architecture_guard_exceptions/<source-module>.tsv` shard. CI rejects new",
        "edges, stale edges, and exceptions without a matching action ID in this report.",
        "",
        f"Current documented findings: {len(violations)}.",
    ]

    for action_id, modules in sorted(grouped.items()):
        lines.extend(["", f"### [{action_id}] Module remediation", ""])
        for source, module_violations in sorted(modules.items()):
            lines.extend([f"#### `{source}`", ""])
            for violation in sorted(
                module_violations,
                key=lambda item: (item.rule, item.target, item.file, item.line),
            ):
                location = Path(violation.file)
                try:
                    display_path = location.relative_to(REPO_ROOT).as_posix()
                except ValueError:
                    display_path = location.as_posix()
                lines.append(
                    f"- `{violation.rule}` -> `{violation.target}` at "
                    f"`{display_path}:{violation.line}`. "
                    f"{_remediation_for(violation.rule)}"
                )
            lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _ownership_node(module_name: str) -> str | None:
    owner = classify_module(module_name)
    if owner.layer == "root_workflow":
        return "root workflow"
    if owner.layer == "api_composition":
        return "FastAPI composition"
    if owner.agent:
        if owner.capability:
            return f"{owner.agent}.{owner.capability} capability"
        if owner.layer:
            return f"{owner.agent} {owner.layer}"
        return f"{owner.agent} agent"
    if module_name == "src.shared" or module_name.startswith("src.shared."):
        return "shared contracts"
    if module_name == "src.services" or module_name.startswith("src.services."):
        return "root services"
    if module_name == "src.interface" or module_name.startswith("src.interface."):
        return "root interface"
    if module_name.startswith("src."):
        parts = module_name.split(".")
        return f"{parts[1]} feature" if len(parts) > 1 else None
    return None


def _dependency_report(src_root: Path = SRC_ROOT, api_root: Path | None = None) -> str:
    refs = collect_imports(src_root, api_root)
    modules = {ref.source for ref in refs}
    internal_refs = [
        ref
        for ref in refs
        if ref.target.startswith("src.") and _module_exists(ref.target, src_root)
    ]
    ownership_edges: Counter[tuple[str, str]] = Counter()
    capability_edges: Counter[tuple[str, str]] = Counter()
    capability_nodes: set[str] = set()
    agents_root = src_root / "agents"
    if agents_root.is_dir():
        for agent_root in sorted(
            path for path in agents_root.iterdir() if path.is_dir()
        ):
            for capability_root_name in CAPABILITY_ROOTS:
                capability_root = agent_root / capability_root_name
                if not capability_root.is_dir():
                    continue
                for capability_path in sorted(
                    path for path in capability_root.iterdir() if path.is_dir()
                ):
                    if any(capability_path.rglob("*.py")):
                        capability_nodes.add(
                            f"{agent_root.name}.{capability_path.name}"
                        )
    for ref in internal_refs:
        source_node = _ownership_node(ref.source)
        target_node = _ownership_node(ref.target)
        if source_node and target_node and source_node != target_node:
            ownership_edges[(source_node, target_node)] += 1

        source = classify_module(ref.source)
        target = classify_module(ref.target)
        if source.agent and source.capability:
            capability_nodes.add(f"{source.agent}.{source.capability}")
        if target.agent and target.capability:
            capability_nodes.add(f"{target.agent}.{target.capability}")
        if (
            source.agent
            and source.agent == target.agent
            and source.capability
            and target.capability
            and source.capability != target.capability
        ):
            capability_edges[
                (
                    f"{source.agent}.{source.capability}",
                    f"{target.agent}.{target.capability}",
                )
            ] += 1

    violations = collect_violations(src_root, api_root)
    by_rule = Counter(item.rule for item in violations)
    lines = [
        "# Architecture dependency report",
        "",
        "Generated by `python3 scripts/architecture_guard.py --write-dependency-report`.",
        "The report scans Python imports in `finance-agent-core/src` and `finance-agent-core/api`.",
        "It groups internal imports by their owning workflow, agent layer, capability, or shared contract.",
        "",
        "## Scan result",
        "",
        f"- Python modules with imports scanned: {len(modules)}.",
        f"- Resolved internal `src.*` imports: {len(internal_refs)}.",
        f"- Architecture findings: {len(violations)}.",
        f"- Capability packages observed: {len(capability_nodes)}.",
        f"- Cross-capability dependency edges: {len(capability_edges)}.",
        "",
    ]
    if by_rule:
        lines.extend(["Findings by rule:", ""])
        lines.extend(f"- `{rule}`: {count}." for rule, count in sorted(by_rule.items()))
        lines.append("")
    else:
        lines.extend(
            [
                "The architecture guard found no forbidden imports, migration-only paths, or capability cycles.",
                "All observed ownership edges satisfy the guard rules.",
                "",
            ]
        )

    lines.extend(["## Observed ownership edges", ""])
    if ownership_edges:
        lines.extend(
            [
                "| Source owner | Target owner | Internal import count |",
                "| --- | --- | ---: |",
            ]
        )
        lines.extend(
            f"| `{source}` | `{target}` | {count} |"
            for (source, target), count in sorted(ownership_edges.items())
        )
        lines.append("")
    else:
        lines.extend(["No cross-owner internal imports were found.", ""])

    lines.extend(["## Capability dependency graph", ""])
    if capability_nodes:
        lines.append(
            "Each node names a capability package. Edges show observed imports between capabilities."
        )
        lines.append("")
        lines.append("```mermaid")
        lines.append("flowchart LR")
        for node in sorted(capability_nodes):
            node_id = re.sub(r"[^a-zA-Z0-9]+", "_", node).strip("_").lower()
            lines.append(f'    {node_id}["{node}"]')
        for (source, target), _count in sorted(capability_edges.items()):
            source_id = re.sub(r"[^a-zA-Z0-9]+", "_", source).strip("_").lower()
            target_id = re.sub(r"[^a-zA-Z0-9]+", "_", target).strip("_").lower()
            lines.append(f"    {source_id} --> {target_id}")
        lines.append("```")
        lines.append("")
        if capability_edges:
            lines.extend(
                [
                    "| Source capability | Target capability | Import count |",
                    "| --- | --- | ---: |",
                ]
            )
            lines.extend(
                f"| `{source}` | `{target}` | {count} |"
                for (source, target), count in sorted(capability_edges.items())
            )
            lines.append("")
        else:
            lines.extend(["No cross-capability imports were found.", ""])
    else:
        lines.extend(["No agent capability packages were found.", ""])
    return "\n".join(lines).rstrip() + "\n"


def write_dependency_report(
    src_root: Path = SRC_ROOT,
    path: Path = DEPENDENCY_REPORT_PATH,
    api_root: Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dependency_report(src_root, api_root), encoding="utf-8")


def print_findings(violations: list[Violation]) -> None:
    for item in violations:
        print(f"{item.key()}\t{Path(item.file).as_posix()}:{item.line}\t{item.message}")


def print_summary(violations: list[Violation]) -> None:
    grouped: dict[tuple[str, str], int] = defaultdict(int)
    for item in violations:
        owner = classify_module(item.source).agent or "shared/root"
        grouped[(owner, item.rule)] += 1
    for (owner, rule), count in sorted(grouped.items()):
        print(f"{owner}\t{rule}\t{count}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-current", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--write-module-report", action="store_true")
    parser.add_argument("--write-dependency-report", action="store_true")
    parser.add_argument("--exceptions-dir", type=Path, default=EXCEPTIONS_DIR)
    parser.add_argument("--report", type=Path, default=REPORT_PATH)
    parser.add_argument(
        "--dependency-report", type=Path, default=DEPENDENCY_REPORT_PATH
    )
    args = parser.parse_args(argv)

    violations = collect_violations()
    if args.print_current:
        print_findings(violations)
        return 0
    if args.summary:
        print_summary(violations)
        return 0
    if args.write_module_report:
        write_module_report(violations, args.report)
        print(f"Wrote {len(violations)} findings to {args.report}")
        return 0

    exceptions = load_exceptions(args.exceptions_dir)
    action_ids = load_action_ids(args.report)
    action_errors = validate_exception_actions(exceptions, action_ids)
    current_keys = {item.key() for item in violations}
    unapproved = [item for item in violations if item.key() not in exceptions]
    stale = sorted(set(exceptions) - current_keys)

    if unapproved:
        print("Architecture guard found unapproved dependency violations:")
        print_findings(unapproved)
    if stale:
        print("Remove stale exceptions from the architecture exception shards:")
        for key in stale:
            print(f"  {key} -> {exceptions[key]}")
    if action_errors:
        print("Invalid architecture exception action references:")
        for error in action_errors:
            print(f"  {error}")
    if unapproved or stale or action_errors:
        return 1

    if args.write_dependency_report:
        write_dependency_report(path=args.dependency_report)
        print(f"Wrote dependency report to {args.dependency_report}")
        return 0

    by_rule: dict[str, int] = defaultdict(int)
    for item in violations:
        by_rule[item.rule] += 1
    if violations:
        summary = ", ".join(
            f"{rule}={count}" for rule, count in sorted(by_rule.items())
        )
        print(
            f"Architecture guard passed; {len(violations)} documented legacy edges remain ({summary})."
        )
    else:
        print("Architecture guard passed with no boundary violations.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
