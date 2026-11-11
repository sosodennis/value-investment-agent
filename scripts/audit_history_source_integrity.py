"""Compare retained SEC representations without approving source publication."""

from __future__ import annotations

import argparse
import collections
import io
import json
import platform
import re
import subprocess
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from lxml import etree

from audit_history_dqc_applicability import canonical_bytes, digest, write_report

C14N_URL = "https://www.w3.org/TR/2001/REC-xml-c14n-20010315"
C14N_SHA256 = "09c02ef3bc0f8364b00b16fb06092637c08e8f38cf223d47a5862eacc2956bc0"
MAX_MEMBER_BYTES = 128 * 1024 * 1024


def canonical_xml(content: bytes) -> bytes:
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        remove_blank_text=False,
        recover=False,
    )
    tree = etree.parse(io.BytesIO(content), parser)
    if tree.docinfo.doctype:
        raise ValueError("DTD is not permitted")
    if tree.docinfo.xml_version != "1.0":
        raise ValueError("only XML 1.0 is covered")
    if tree.getroot().tag != "{http://www.xbrl.org/2003/instance}xbrl":
        raise ValueError("source is not an XBRL instance")
    return etree.tostring(tree, method="c14n", exclusive=False, with_comments=False)


def read_source(root: Path, source: dict) -> bytes:
    expected = source["content_hash"]
    if re.fullmatch("[0-9a-f]{64}", expected) is None:
        raise ValueError("invalid source content hash")
    suffix = ".json" if source["media_type"] == "application/json" else ".bin"
    path = root / expected[:2] / (expected + suffix)
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("retained source escapes its content root")
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError("retained source content hash mismatch")
    return raw


def compare_sources(
    index: bytes, direct: bytes, archive: bytes, target: dict, filename: str
) -> dict:
    entries = json.loads(index)["directory"]["item"]
    primary = [row for row in entries if row["name"] == filename]
    archives = [
        row for row in entries if row["name"] == f"{target['accession']}-xbrl.zip"
    ]
    if len(primary) != 1 or len(archives) != 1:
        raise ValueError("index does not uniquely identify the primary and archive")
    if primary[0]["size"] != str(len(direct)) or archives[0]["size"] != str(
        len(archive)
    ):
        raise ValueError("index size does not match retained direct/archive bytes")
    with ZipFile(io.BytesIO(archive)) as package:
        matches = [
            i for i in package.infolist() if i.filename.rsplit("/", 1)[-1] == filename
        ]
        if len(matches) != 1 or matches[0].file_size > MAX_MEMBER_BYTES:
            raise ValueError("primary archive member is ambiguous or exceeds the limit")
        member = package.read(matches[0])
    direct_c14n, member_c14n = canonical_xml(direct), canonical_xml(member)
    return {
        "relation": "canonical_xml_equal"
        if direct_c14n == member_c14n
        else "canonical_xml_different",
        "direct_byte_length": len(direct),
        "archive_member_byte_length": len(member),
        "archive_member_sha256": digest(member),
        "direct_c14n_sha256": digest(direct_c14n),
        "archive_member_c14n_sha256": digest(member_c14n),
    }


def audit(report: dict, root: Path) -> dict:
    rows = []
    for row in report["output"]["rows"]:
        if row["original_failure_code"] != "SOURCE_ARCHIVE_SIZE_MISMATCH":
            continue
        sources = row["original_sources"]
        result = {
            "target": row["target"],
            "original_result_digest": row["original_result_digest"],
            "sources": sources,
            "publication_approved": False,
        }
        try:
            index, direct, archive = (read_source(root, source) for source in sources)
            filename = sources[1]["uri"].rsplit("/", 1)[-1]
            if any(
                source["accession"] != row["target"]["accession"] for source in sources
            ):
                raise ValueError("source accession differs from the frozen target")
            result.update(
                compare_sources(index, direct, archive, row["target"], filename)
            )
        except OSError:
            result.update(
                {"relation": "unresolved", "failure_code": "SOURCE_CONTENT_UNAVAILABLE"}
            )
        except BadZipFile:
            result.update(
                {"relation": "unresolved", "failure_code": "SOURCE_ARCHIVE_INVALID"}
            )
        except etree.LxmlError:
            result.update(
                {
                    "relation": "unresolved",
                    "failure_code": "XML_CANONICALIZATION_FAILED",
                }
            )
        except ValueError as error:
            result.update(
                {
                    "relation": "unresolved",
                    "failure_code": "SOURCE_COMPARISON_FAILED",
                    "reason": str(error),
                }
            )
        rows.append(result)
    return {
        "filing_count": len(rows),
        "rows": rows,
        "relation_counts": dict(
            sorted(collections.Counter(r["relation"] for r in rows).items())
        ),
        "supported_history_threshold": None,
        "canonical_publication_approved": False,
        "limitation": "Canonical XML equality excludes comments and proves a representation relation only. It does not establish taxonomy, EFM/DQC compliance, mapping correctness, financial materiality, or release readiness.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--failure-report", type=Path, required=True)
    parser.add_argument("--failure-report-sha256", required=True)
    parser.add_argument("--content-root", type=Path, required=True)
    parser.add_argument("--c14n-reference", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    raw = args.failure_report.read_bytes()
    if digest(raw) != args.failure_report_sha256:
        raise ValueError("failure report differs from its pin")
    if digest(args.c14n_reference.read_bytes()) != C14N_SHA256:
        raise ValueError("W3C reference differs from its pin")
    repository_root = Path(
        subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"], text=True
        ).strip()
    ).resolve()
    if args.output_directory.resolve().is_relative_to(repository_root):
        raise ValueError("generated research evidence must be outside the Git worktree")
    inputs = {
        "protocol": "fixed100-source-representation-audit-v1",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "script_sha256": digest(Path(__file__).read_bytes()),
        "report_writer_sha256": digest(
            Path(__file__).with_name("audit_history_dqc_applicability.py").read_bytes()
        ),
        "failure_report_sha256": args.failure_report_sha256,
        "canonicalization": "W3C inclusive Canonical XML 1.0 without comments; preserve text and whitespace; no DTD, network, external entities, or recovery",
        "reference": {"url": C14N_URL, "sha256": C14N_SHA256},
        "runtime": {
            "python": platform.python_version(),
            "lxml": etree.LXML_VERSION,
            "libxml2": etree.LIBXML_VERSION,
        },
    }
    output = audit(json.loads(raw), args.content_root)
    report = {
        "inputs": inputs,
        "input_digest": digest(canonical_bytes(inputs)),
        "output": output,
        "output_digest": digest(canonical_bytes(output)),
    }
    print(
        json.dumps(
            {
                **write_report(args.output_directory, report),
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
