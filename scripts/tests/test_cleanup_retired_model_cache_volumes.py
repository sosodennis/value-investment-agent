from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "docker"
    / "cleanup_retired_model_cache_volumes.py"
)
LOGICAL_VOLUMES = (
    "hf_cache",
    "inference_news_hf_cache",
    "inference_fls_hf_cache",
)

FAKE_DOCKER = r"""#!/usr/bin/env python3
import json
import os
import sys

args = sys.argv[1:]
project = os.environ["FAKE_PROJECT"]
log_path = os.environ["FAKE_DOCKER_LOG"]
with open(log_path, "a", encoding="utf-8") as log:
    log.write(json.dumps(args) + "\n")

if args[:2] == ["image", "inspect"]:
    print("[{\"Id\":\"sha256:test\"}]")
elif args[:2] == ["volume", "ls"]:
    logical_names = os.environ.get("FAKE_VOLUMES", ",".join((
        "hf_cache", "inference_news_hf_cache", "inference_fls_hf_cache"
    ))).split(",")
    for logical_name in logical_names:
        if logical_name:
            print(f"{project}_{logical_name}")
elif args[:2] == ["volume", "inspect"]:
    name = args[-1]
    logical_name = name.removeprefix(project + "_")
    if name not in {
        f"{project}_{item}" for item in os.environ.get(
            "FAKE_VOLUMES",
            "hf_cache,inference_news_hf_cache,inference_fls_hf_cache",
        ).split(",") if item
    }:
        raise SystemExit(1)
    if name == os.environ.get("FAKE_BAD_LABEL_VOLUME"):
        logical_name = "pg_data"
    print(json.dumps([{
        "Name": name,
        "Driver": "local",
        "Labels": {
            "com.docker.compose.project": project,
            "com.docker.compose.volume": logical_name,
        },
    }]))
elif args[0] == "ps":
    filter_value = args[args.index("--filter") + 1]
    if filter_value.startswith("label="):
        print(os.environ.get("FAKE_PROJECT_CONTAINERS", ""))
    elif filter_value.startswith("volume="):
        volume_name = filter_value.removeprefix("volume=")
        if volume_name == os.environ.get("FAKE_ATTACHED_VOLUME"):
            print("other-project-container")
elif args[0] == "run":
    print("8.0M /cache\n/cache/hub\n/cache/hub/models--example")
elif args[:2] == ["volume", "rm"]:
    print(args[2])
else:
    raise SystemExit(f"unexpected docker args: {args}")
"""


class RetiredModelCacheCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        docker_bin = root / "docker"
        docker_bin.write_text(FAKE_DOCKER, encoding="utf-8")
        docker_bin.chmod(0o755)
        self.log_path = root / "docker.log"
        self.project = "value-investment-agent-test-retired"
        self.env = {
            **os.environ,
            "PATH": f"{root}:{os.environ['PATH']}",
            "FAKE_PROJECT": self.project,
            "FAKE_DOCKER_LOG": str(self.log_path),
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_cleanup(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["python3", str(SCRIPT), "--project", self.project, *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=self.env,
        )

    def docker_calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log_path.read_text().splitlines()]

    def removed_volumes(self) -> list[str]:
        return [call[2] for call in self.docker_calls() if call[:2] == ["volume", "rm"]]

    def test_default_run_inspects_but_does_not_delete(self) -> None:
        result = self.run_cleanup()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Dry run only", result.stdout)
        self.assertIn("/cache/hub/models--example", result.stdout)
        self.assertEqual(self.removed_volumes(), [])

    def test_confirmation_removes_only_three_allowlisted_cache_volumes(self) -> None:
        result = self.run_cleanup("--confirm-retired")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            self.removed_volumes(),
            [f"{self.project}_{name}" for name in LOGICAL_VOLUMES],
        )
        self.assertNotIn("pg_data", " ".join(self.removed_volumes()))

    def test_live_project_blocks_deletion(self) -> None:
        self.env["FAKE_PROJECT_CONTAINERS"] = "test-backend-1"

        result = self.run_cleanup("--confirm-retired")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("project still has 1 container", result.stderr)
        self.assertEqual(self.removed_volumes(), [])

    def test_volume_mounted_by_another_project_blocks_deletion(self) -> None:
        self.env["FAKE_ATTACHED_VOLUME"] = f"{self.project}_hf_cache"

        result = self.run_cleanup("--confirm-retired")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still mounted", result.stderr)
        self.assertEqual(self.removed_volumes(), [])

    def test_unexpected_compose_volume_label_blocks_all_deletion(self) -> None:
        self.env["FAKE_BAD_LABEL_VOLUME"] = f"{self.project}_inference_news_hf_cache"

        result = self.run_cleanup("--confirm-retired")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected Compose volume label", result.stderr)
        self.assertEqual(self.removed_volumes(), [])


if __name__ == "__main__":
    unittest.main()
