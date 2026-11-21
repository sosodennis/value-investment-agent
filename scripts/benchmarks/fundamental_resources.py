"""Read cgroup and process counters inside the measured Linux container."""

from __future__ import annotations

import json
import time
from pathlib import Path


def pairs(root: Path, name: str) -> dict[str, int]:
    return {
        key: int(value)
        for key, value in (
            line.split() for line in (root / name).read_text().splitlines()
        )
    }


def collect() -> dict[str, object]:
    root = Path("/sys/fs/cgroup")
    cpu = pairs(root, "cpu.stat")
    processes = []
    for process in Path("/proc").iterdir():
        if not process.name.isdigit():
            continue
        try:
            fields = {
                key: value.strip()
                for key, value in (
                    line.split(":", 1)
                    for line in (process / "status").read_text().splitlines()
                )
            }
            processes.append(
                {
                    "pid": int(process.name),
                    "ppid": int(fields["PPid"]),
                    "name": fields["Name"],
                    "rss_kib": int(fields.get("VmRSS", "0 kB").split()[0]),
                    "swap_kib": int(fields.get("VmSwap", "0 kB").split()[0]),
                }
            )
        except (FileNotFoundError, ProcessLookupError):
            continue
    return {
        "monotonic": time.monotonic(),
        "cpu_us": cpu["usage_usec"],
        "cpu": cpu,
        "memory_current": int((root / "memory.current").read_text()),
        "memory_peak": int((root / "memory.peak").read_text()),
        "memory_stat": pairs(root, "memory.stat"),
        "memory_events": pairs(root, "memory.events"),
        "swap_current": int((root / "memory.swap.current").read_text()),
        "io_stat": (root / "io.stat").read_text(),
        "processes": processes,
    }


if __name__ == "__main__":
    print(json.dumps(collect()))
