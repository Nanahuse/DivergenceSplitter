"""Record host + all descendant process CPU/private/RSS for one representative run.

Requires psutil. This is functional telemetry unless desktop conditions are controlled.
RSS sum double-counts shared pages; private bytes is recorded separately. GPU unmeasured.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import time
from pathlib import Path

import psutil


def run(executable: Path, output: Path, seconds: int, large: bool, page: str) -> None:
    if output.exists():
        raise ValueError("Use a new output directory")
    output.mkdir(parents=True)
    executable = executable.resolve()
    args = [str(executable), "--seconds", str(seconds), "--page", page,
            "--report", str((output / "app.json").resolve())]
    if large:
        args.append("--large")
    started = time.monotonic()
    samples, processes = [], {}
    with (output / "app.log").open("w", encoding="utf-8") as log:
        child = subprocess.Popen(args, cwd=executable.parent, stdout=log, stderr=log)
        root = psutil.Process(child.pid)
        while child.poll() is None:
            try:
                descendants = [root, *root.children(recursive=True)]
            except psutil.NoSuchProcess:
                break
            private = rss = 0
            for process in descendants:
                try:
                    with process.oneshot():
                        key = f"{process.pid}:{process.create_time()}"
                        cpu, memory = process.cpu_times(), process.memory_info()
                        processes[key] = {"pid": process.pid, "name": process.name(),
                                          "cpu_seconds": cpu.user + cpu.system}
                        private += memory.private
                        rss += memory.rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            samples.append({"seconds": time.monotonic() - started,
                            "private_bytes_sum": private, "rss_sum": rss,
                            "cpu_seconds_cumulative": sum(p["cpu_seconds"] for p in processes.values()),
                            "live_process_count": len(descendants)})
            if time.monotonic() - started > seconds + 30:
                child.terminate()
                raise TimeoutError("GUI failed to finish representative run")
            time.sleep(0.25)
        code = child.wait(timeout=10)
    app = json.loads((output / "app.json").read_text(encoding="utf-8"))
    if code or app["error"] or app["measurement_seconds"] < seconds - 1:
        raise RuntimeError("Representative run failed or ended early")
    report = {"executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
              "command": args, "processes": list(processes.values()), "samples": samples,
              "scope": "host and sampled descendants; exited process last observed CPU retained",
              "limitations": ["RSS sum double-counts shared pages", "short-lived processes between samples may be missed",
                              "desktop workload/occlusion uncontrolled; no performance ranking", "GPU unmeasured", "intake/decode acknowledgement is not display scanout"]}
    (output / "process-tree.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("executable", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--seconds", type=int, default=20)
    parser.add_argument("--large", action="store_true")
    parser.add_argument("--page", choices=["monitor", "diagnostics"], default="monitor")
    args = parser.parse_args()
    run(args.executable, args.output, args.seconds, args.large, args.page)
