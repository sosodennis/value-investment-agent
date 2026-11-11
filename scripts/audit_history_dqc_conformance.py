"""Replay retained historical DQC assertions with the official Arelle matcher."""

from __future__ import annotations

import argparse
import collections
import gzip
import json
import logging
import platform
import socket
import subprocess
import tempfile
from contextlib import contextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any, Iterator
from unittest.mock import patch
from zipfile import ZipFile

import arelle
from arelle.CntlrCmdLine import CntlrCmdLine
from arelle.ModelFormulaObject import FormulaOptions
from arelle.Validate import Validate
from lxml import etree

from audit_history_dqc_applicability import canonical_bytes, digest, write_report

SUITE_SHA256 = "4a0190225dc1d8d2631b39c66644e28783136e32fd6cc576fe87c418a657adde"
INPUT_SHA256 = "6bbfd6162e2bb6fd86ae3a1efbc40cadbfc0599a741900158c9ebf9734c31d27"
SHARD_SHA256 = frozenset(
    (
        "ef14b87bd7d6ba7decbbc7297f0a2a98e867d58b5be6d23e1f90f253afd939bf",
        "0486affb44c45c52b82268205683220c37c6b5fe79c322bf9f1805d4a1dfacbe",
        "91a55e1681ac93d67e282580c7d7b46daacfa6855e0ba92af201481c9510bb91",
        "a12481847a69adc15a81355b31c8e150c4762d7685827af19ef540efbfd5cafb",
    )
)
SOURCE_COMMIT = "cafb54391c1d21e4c219bc3d491b855a9b877cb6"
MATCHER_SHA256 = "6247dcde32eff3333f961871fb960e69427522138bddd19568deb24fd7a98861"
MODULES = (
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
)
LEVELS = {
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "critical": logging.CRITICAL,
    "fatal": logging.FATAL,
}


def read_evidence(root: Path, kind: str, sha256: str) -> dict[str, Any]:
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise ValueError("evidence reference is not a SHA-256 digest")
    raw = gzip.decompress((root / kind / f"{sha256}.json.gz").read_bytes())
    document = json.loads(raw)
    if digest(raw) != sha256 or canonical_bytes(document) != raw:
        raise ValueError("retained conformance evidence failed digest/canonical checks")
    if not isinstance(document, dict):
        raise ValueError("retained conformance document must be an object")
    return document


@contextmanager
def offline_attempts() -> Iterator[list[int]]:
    attempts = [0]

    def blocked(*args: object, **kwargs: object) -> None:
        attempts[0] += 1
        raise OSError("conformance assertion replay is offline")

    with (
        patch.object(socket.socket, "connect", blocked),
        patch.object(socket.socket, "connect_ex", blocked),
    ):
        yield attempts


class OfficialMatcher:
    """Load suite metadata, never its filing instances or taxonomy imports."""

    def __init__(self, paths: list[Path]) -> None:
        if version("arelle-release") != "2.47.4":
            raise ValueError("the official matcher must be Arelle 2.47.4")
        if (
            digest((Path(arelle.__file__).parent / "Validate.py").read_bytes())
            != MATCHER_SHA256
        ):
            raise ValueError(
                "official Arelle matcher source differs from its release pin"
            )
        self.controllers: list[CntlrCmdLine] = []
        self.variations: dict[str, Any] = {}
        self.cases: list[dict[str, Any]] = []
        try:
            for path in paths:
                controller = CntlrCmdLine(disable_persistent_config=True)
                self.controllers.append(controller)
                controller.webCache.workOffline = True
                controller.modelManager.formulaOptions = FormulaOptions()
                plugin = str(
                    Path(arelle.__file__).parent / "plugin/logging/dqcParameters.py"
                )
                if controller._pluginManager.addPluginModule(plugin) is None:
                    raise ValueError("official DQC assertion plugin is unavailable")
                controller.startLogging(logFileName="logToBuffer")
                model = controller.modelManager.load(str(path))
                if model is None or model.modelDocument is None:
                    raise ValueError("official testcase metadata did not load")
                for variation in model.modelDocument.testcaseVariations:
                    if variation.id in self.variations:
                        raise ValueError("official suite repeats a testcase identity")
                    self.variations[variation.id] = variation
                    instance = variation.findtext("{*}data/{*}instance")
                    if not isinstance(instance, str):
                        raise ValueError("official testcase has no instance entrypoint")
                    if not instance.startswith(("http:", "https:")):
                        instance = f"{path.parent.name}/{instance}"
                    self.cases.append(
                        {
                            "family": path.parent.name,
                            "id": variation.id,
                            "instance": instance,
                            "blocked": variation.blockedMessageCodes,
                            "expected": [
                                {
                                    "code": e.text,
                                    "count": e.get("count"),
                                    "severity": e.get("severity"),
                                }
                                for e in variation.findall("{*}results/{*}error")
                            ],
                        }
                    )
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        for controller in self.controllers:
            controller.modelManager.close()
            controller.close()
        self.controllers.clear()

    def compare(self, case_id: str, findings: list[dict[str, Any]]) -> dict[str, Any]:
        variation = self.variations[case_id]
        dqc = [f for f in findings if f["code"].startswith("DQC.")]
        unknown_severity = [f for f in dqc if f.get("rule_severity") not in LEVELS]
        captured = [
            f["code"]
            for f in dqc
            if LEVELS.get(str(f.get("rule_severity")), 0) >= variation.severityLevel
        ]
        Validate(variation.modelXbrl).determineTestStatus(variation, captured)
        return {
            "official_status": variation.status,
            "match_all": variation.matchAll,
            "expected_count": variation.expectedCount,
            "capture_severity": variation.severityLevel,
            "actual_counts": getattr(variation, "actualCounts", {}),
            "unknown_original_severity_count": len(unknown_severity),
        }


@contextmanager
def suite_matcher(archive: Path) -> Iterator[OfficialMatcher]:
    if digest(archive.read_bytes()) != SUITE_SHA256:
        raise ValueError("official suite archive differs from its pin")
    with tempfile.TemporaryDirectory(prefix="issue376-dqc-expectations-") as temp:
        with ZipFile(archive) as package:
            if len(package.namelist()) != len(set(package.namelist())):
                raise ValueError("official suite contains duplicate member paths")
            parser = etree.XMLParser(
                resolve_entities=False, no_network=True, load_dtd=False
            )
            index = etree.fromstring(package.read("index.xml"), parser)
            paths = []
            for element in index.findall("testcases/testcase"):
                relative = Path(element.attrib["uri"])
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or relative.name != "variation.xml"
                ):
                    raise ValueError("official testcase metadata path is unsafe")
                target = Path(temp) / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(package.read(relative.as_posix()))
                paths.append(target)
        matcher = OfficialMatcher(paths)
        try:
            yield matcher
        finally:
            matcher.close()


def assess(record: dict[str, Any], comparison: dict[str, Any]) -> dict[str, Any]:
    complete = (
        record.get("success") is True
        and record.get("all_modules_completed") is True
        and tuple(record.get("returned_modules", ())) == MODULES
        and not record.get("unsupported_namespaces")
        and record.get("network_attempt_count") == 0
        and not record.get("runtime_errors")
        and not record.get("error_type")
    )
    passed = (
        complete
        and comparison["official_status"] == "pass"
        and comparison["unknown_original_severity_count"] == 0
    )
    return {
        "case_id": record["case"]["id"],
        "index": record["index"],
        "original_passed": record["passed"],
        "official_assertion": comparison,
        "execution_complete": complete,
        "unsupported_namespaces": record.get("unsupported_namespaces", []),
        "runtime_errors": record.get("runtime_errors", []),
        "network_attempt_count": record.get("network_attempt_count"),
        "passed": passed,
    }


def audit(root: Path, matcher: OfficialMatcher) -> dict[str, Any]:
    original_input = read_evidence(root, "input", INPUT_SHA256)
    if (
        original_input["official_source_commit"] != SOURCE_COMMIT
        or original_input["official_archive_sha256"] != SUITE_SHA256
        or digest(canonical_bytes(matcher.cases)) != original_input["cases_digest"]
        or len(matcher.cases) != original_input["declared_count"]
    ):
        raise ValueError("official suite and retained execution inventory disagree")
    shards = []
    actual_shards = {
        path.name.removesuffix(".json.gz")
        for path in (root / "shards").glob("*.json.gz")
    }
    if actual_shards != SHARD_SHA256:
        raise ValueError(
            "complete suite requires four unique shards with their original digests"
        )
    for path in sorted((root / "shards").glob("*.json.gz")):
        shard = read_evidence(root, "shards", path.name.removesuffix(".json.gz"))
        if shard["input_digest"] != INPUT_SHA256 or shard["sample_only"]:
            raise ValueError("conformance shard is not from the pinned complete suite")
        if (
            shard["shard_count"] != 4
            or shard["network_attempt_count"]
            or not shard["cache_unchanged"]
        ):
            raise ValueError(
                "conformance shard execution was incomplete or not offline"
            )
        if shard["executed_count"] != len(shard["results"]) or shard[
            "passed_count"
        ] != sum(r["passed"] for r in shard["results"]):
            raise ValueError("conformance shard summary disagrees with its cases")
        shards.append((shard, path.name.removesuffix(".json.gz")))
    if sorted(s["shard_index"] for s, _ in shards) != list(range(4)):
        raise ValueError("complete suite requires four unique shards")
    rows = []
    for shard, shard_digest in shards:
        for ref in shard["results"]:
            record = read_evidence(root, "cases", ref["digest"])
            index = ref["index"]
            if (
                not 0 <= index < len(matcher.cases)
                or index % 4 != shard["shard_index"]
                or record["index"] != index
                or record["input_digest"] != INPUT_SHA256
                or record["passed"] != ref["passed"]
                or record["case"] != matcher.cases[index]
                or ref["case_id"] != record["case"]["id"]
            ):
                raise ValueError("case reference disagrees with the official suite")
            row = assess(
                record, matcher.compare(ref["case_id"], record.get("findings", []))
            )
            rows.append(
                {
                    **row,
                    "original_record_digest": ref["digest"],
                    "original_shard_digest": shard_digest,
                    "original_findings_digest": digest(
                        canonical_bytes(record.get("findings", []))
                    ),
                }
            )
    rows.sort(key=lambda r: r["index"])
    if [r["index"] for r in rows] != list(range(len(matcher.cases))):
        raise ValueError("suite cases are missing or duplicated")
    return {
        "declared_count": len(rows),
        "original_passed_count": sum(r["original_passed"] for r in rows),
        "official_assertion_passed_count": sum(
            r["official_assertion"]["official_status"] == "pass" for r in rows
        ),
        "execution_and_assertion_passed_count": sum(r["passed"] for r in rows),
        "newly_matching_cases": [
            r["case_id"] for r in rows if r["passed"] and not r["original_passed"]
        ],
        "remaining_failure_cases": [r["case_id"] for r in rows if not r["passed"]],
        "unsupported_namespace_counts": dict(
            sorted(
                collections.Counter(
                    n for r in rows for n in r["unsupported_namespaces"]
                ).items()
            )
        ),
        "rows": rows,
        "fresh_rule_execution": False,
        "canonical_publication_approved": False,
        "limitation": "Re-evaluates retained execution records; does not certify current parser integration, rule effective dates, financial materiality, release mappings or a history threshold.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--official-suite", required=True, type=Path)
    parser.add_argument("--output-directory", required=True, type=Path)
    args = parser.parse_args()
    git_root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    )
    if args.output_directory.resolve().is_relative_to(git_root.resolve()):
        raise ValueError("generated research evidence must remain outside Git")
    installed = Path(arelle.__file__).parent
    inputs = {
        "protocol": "retained-dqc-official-assertion-replay-v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "script_sha256": digest(Path(__file__).read_bytes()),
        "writer_sha256": digest(
            Path(__file__).with_name("audit_history_dqc_applicability.py").read_bytes()
        ),
        "original_input_digest": INPUT_SHA256,
        "original_shard_digests": sorted(SHARD_SHA256),
        "official_source_commit": SOURCE_COMMIT,
        "official_suite_sha256": SUITE_SHA256,
        "runtime": {
            "python": platform.python_version(),
            "arelle": version("arelle-release"),
            "lxml": etree.LXML_VERSION,
            "libxml2": etree.LIBXML_VERSION,
        },
        "matcher_source_hashes": {
            name: digest((installed / name).read_bytes())
            for name in (
                "Validate.py",
                "ModelTestcaseObject.py",
                "ModelFormulaObject.py",
                "plugin/logging/dqcParameters.py",
                "conformance/error_code_matcher.py",
            )
        },
    }
    with offline_attempts() as attempts, suite_matcher(args.official_suite) as matcher:
        output = audit(args.evidence_root, matcher)
    if attempts[0]:
        raise ValueError("official assertion replay attempted network access")
    output["assertion_replay_network_attempt_count"] = attempts[0]
    report = {
        "inputs": inputs,
        "input_digest": digest(canonical_bytes(inputs)),
        "output": output,
        "output_digest": digest(canonical_bytes(output)),
    }
    receipt = write_report(args.output_directory, report)
    print(
        json.dumps(
            {
                **receipt,
                "input_digest": report["input_digest"],
                "output_digest": report["output_digest"],
                "summary": {k: v for k, v in output.items() if k != "rows"},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
