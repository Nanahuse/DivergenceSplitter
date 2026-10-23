"""Run serial same-machine GUI measurements; never rank different CI runners."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def run(
    distribution: Path,
    output: Path,
    *,
    warmup: int,
    seconds: int,
    repeats: int,
    soak: int,
) -> None:
    if output.exists():
        raise ValueError("Use a new output directory to preserve earlier measurements")
    output.mkdir(parents=True)
    metadata = {
        "started_utc": datetime.now(UTC).isoformat(),
        "platform": platform.platform(),
        "processor": platform.processor(),
        "logical_cpus": os.cpu_count(),
        "power_plan": subprocess.check_output(
            ["powercfg", "/getactivescheme"], text=True
        ).strip(),
        "warmup_seconds": warmup,
        "measurement_seconds": seconds,
        "repeats": repeats,
        "soak_seconds_per_candidate_and_dataset": soak,
        "method": "Serial foreground GUI processes; shared worker included in process CPU. Intake is not scanout. Other desktop activity is uncontrolled.",
    }
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
        with (output / f"{name}.log").open("w", encoding="utf-8") as log:
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
        measured = json.loads(report.read_text(encoding="utf-8"))
        if (
            measured["error"]
            or measured["candidate"] != candidate
            or measured["large"] != large
            or measured["generated_frames"] <= 0
        ):
            raise RuntimeError(f"Invalid measurement: {name}")
        if measured["measurement_seconds"] < duration - 1:
            raise RuntimeError(f"Measurement ended early: {name}")
        if exercise and measured["exercise_steps"] < 160:
            raise RuntimeError(f"Insufficient lifecycle exercise: {name}")
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
    )


if __name__ == "__main__":
    main()
