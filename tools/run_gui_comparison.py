"""Run serial same-machine GUI measurements; never rank different CI runners."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def validate_report(
    report: Path, candidate: str, large: bool, duration: int, exercise: bool
) -> dict:
    if not report.is_file():
        raise RuntimeError(
            f"{report.stem}: process exited without a report; duration was not verified. "
            "A closed window can also exit successfully. Inspect the case log."
        )
    measured = json.loads(report.read_text(encoding="utf-8"))
    if (
        measured["error"]
        or measured["candidate"] != candidate
        or measured["large"] != large
        or measured["generated_frames"] <= 0
    ):
        raise RuntimeError(f"Invalid measurement: {report.stem}")
    if measured["measurement_seconds"] < duration - 1:
        raise RuntimeError(f"Measurement ended early: {report.stem}")
    if exercise and measured["exercise_steps"] < 160:
        raise RuntimeError(f"Insufficient lifecycle exercise: {report.stem}")
    return measured


def run(
    distribution: Path,
    output: Path,
    *,
    warmup: int,
    seconds: int,
    repeats: int,
    soak: int,
    resume: bool = False,
) -> None:
    distribution = distribution.resolve()
    output = output.resolve()
    if output.is_relative_to(distribution) or distribution.is_relative_to(output):
        raise ValueError("Distribution and measurements must be disjoint")
    binaries = {
        candidate: distribution / candidate / f"bin/comparison-{candidate}.exe"
        for candidate in ("qt", "wx", "imgui")
    }
    binary_hashes = {
        candidate: hashlib.sha256(binary.read_bytes()).hexdigest()
        for candidate, binary in binaries.items()
    }
    if output.exists() and not resume:
        raise ValueError("Use a new output directory to preserve earlier measurements")
    output.mkdir(parents=True, exist_ok=resume)
    power_output = subprocess.check_output(["powercfg", "/getactivescheme"])
    power_guid = re.search(
        rb"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", power_output
    )
    if power_guid is None:
        raise RuntimeError("Cannot identify the active Windows power scheme GUID")
    metadata = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True
        ).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        ),
        "binary_sha256": binary_hashes,
        "started_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "power_scheme_guid": power_guid.group().decode("ascii"),
        "warmup_seconds": warmup,
        "measurement_seconds": seconds,
        "repeats": repeats,
        "soak_seconds_per_candidate_and_dataset": soak,
        "method": "Serial visible GUI processes; foreground focus/occlusion not enforced. Shared worker included in process CPU. Intake is not scanout. Other desktop activity is uncontrolled.",
    }
    if resume:
        previous = json.loads((output / "environment.json").read_text(encoding="utf-8"))
        for key in (
            "binary_sha256",
            "platform",
            "processor",
            "logical_cpus",
            "power_scheme_guid",
            "warmup_seconds",
            "measurement_seconds",
            "repeats",
            "soak_seconds_per_candidate_and_dataset",
        ):
            if previous[key] != metadata[key]:
                raise ValueError(
                    f"Cannot resume with changed measurement condition: {key}"
                )
        if (output / "invalidated.json").exists() or (
            output / "completed.json"
        ).exists():
            raise ValueError("Cannot resume invalidated or completed measurements")
        previous.setdefault("resumes", []).append(
            {
                "utc": metadata["started_utc"],
                "runner_source_commit": metadata["source_commit"],
                "runner_working_tree_dirty": metadata["working_tree_dirty"],
                "reason": "Retry cases without a report; keep and revalidate completed cases. Binary hashes unchanged.",
            }
        )
        metadata = previous
    (output / "environment.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8"
    )
    cases = []
    # Alternate candidate order between repetitions to limit systematic order bias.
    for repeat in range(repeats):
        candidates = ("qt", "wx", "imgui") if repeat % 2 == 0 else ("imgui", "wx", "qt")
        for large in (False, True):
            for candidate in candidates:
                cases.append(
                    (
                        candidate,
                        large,
                        f"monitor-{repeat + 1}",
                        seconds,
                        False,
                        "monitor",
                    )
                )
    # Separate Diagnostics measurement and capture; never mix these with Monitor.
    for large in (False, True):
        for candidate in ("qt", "wx", "imgui"):
            cases.append(
                (candidate, large, "diagnostics", seconds, False, "diagnostics")
            )
            if soak:
                cases.append((candidate, large, "soak", soak, True, "monitor"))
    for candidate, large, label, duration, exercise, page in cases:
        name = f"{candidate}-{'large' if large else 'small'}-{label}"
        root = (distribution / candidate).resolve()
        windows = Path(os.environ["SystemRoot"])
        environment = {
            key: value
            for key, value in os.environ.items()
            if not key.startswith(("QT_", "QML", "OPENCV_", "NDI_"))
        }
        environment["PATH"] = os.pathsep.join(
            (str(root / "bin"), str(windows / "System32"), str(windows))
        )
        report = (output / f"{name}.json").resolve()
        if resume and report.exists():
            validate_report(report, candidate, large, duration, exercise)
            print(f"KEEP {name}: validated existing report", flush=True)
            continue
        command = [
            str(root / f"bin/comparison-{candidate}.exe"),
            "--seconds",
            str(duration),
            "--warmup",
            str(warmup),
            "--page",
            page,
            "--report",
            str(report),
        ]
        if large:
            command.append("--large")
        if exercise:
            command.append("--exercise")
        if label == "diagnostics":
            command.extend(("--capture", str((output / f"{name}.png").resolve())))
        print(f"START {name}: warmup {warmup}s + measure {duration}s", flush=True)
        log_path = output / f"{name}.log"
        if log_path.exists():
            log_path.rename(
                log_path.with_suffix(
                    f".interrupted-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.log"
                )
            )
        with log_path.open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command,
                cwd=root,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=warmup + duration + 60,
                check=False,
            )
        if result.returncode:
            raise RuntimeError(f"{name} failed: {result.returncode}")
        measured = validate_report(report, candidate, large, duration, exercise)
        print(
            f"PASS {name}: CPU {measured['cpu_seconds']:.3f}s / {measured['measurement_seconds']:.3f}s, frames {measured['generated_frames']}",
            flush=True,
        )
    (output / "completed.json").write_text(
        json.dumps(
            {"completed_utc": datetime.now(UTC).isoformat(), "cases": len(cases)}
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--distribution", type=Path, default=Path("dist/gui-comparison")
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmup", type=int, default=30)
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--soak", type=int, default=1800)
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Reuse validated cases only with identical binaries and conditions",
    )
    args = parser.parse_args()
    if args.warmup < 0 or args.seconds <= 0 or args.repeats <= 0 or args.soak < 0:
        parser.error(
            "Durations and repetitions must be positive (warmup/soak may be zero)"
        )
    run(
        args.distribution,
        args.output,
        warmup=args.warmup,
        seconds=args.seconds,
        repeats=args.repeats,
        soak=args.soak,
        resume=args.resume,
    )


if __name__ == "__main__":
    main()
