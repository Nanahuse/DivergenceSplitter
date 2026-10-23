"""Summarize completed same-machine measurements, retaining per-run evidence."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from itertools import pairwise
from pathlib import Path
from statistics import median
from typing import Any


def summarize(source: Path, output: Path) -> None:
    environment = json.loads((source / "environment.json").read_text(encoding="utf-8"))
    completed = json.loads((source / "completed.json").read_text(encoding="utf-8"))
    if (source / "invalidated.json").exists():
        raise ValueError("Invalidated measurements cannot be summarized as completed")
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    records = []
    for path in sorted(source.glob("*.json")):
        if path.name in ("environment.json", "completed.json"):
            continue
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("error") or record.get("self_test"):
            raise ValueError(f"Failed or non-steady measurement: {path.name}")
        duration = record["measurement_seconds"]
        if duration <= 0:
            raise ValueError("Measurement duration must be positive")
        record["name"] = path.stem
        record["producer_hz"] = record["generated_frames"] / duration
        record["gui_intake_hz"] = record["gui_frame_intakes"] / duration
        record["cpu_one_core_percent"] = record["cpu_seconds"] / duration * 100
        samples = record.pop("memory_samples")
        buckets: dict[int, list[int]] = defaultdict(list)
        for seconds, private, _working_set in samples:
            buckets[int(seconds // 60)].append(private)
        record["private_bytes_per_minute"] = {
            str(minute): {
                "min": min(values),
                "median": median(values),
                "max": max(values),
            }
            for minute, values in buckets.items()
        }
        if samples:
            first = [sample[1] for sample in samples if sample[0] < 60]
            last = [sample[1] for sample in samples if sample[0] >= duration - 60]
            record["private_first_to_last_minute_median_delta"] = (
                median(last) - median(first) if first and last else None
            )
            record["maximum_memory_sample_gap_seconds"] = max(
                (second[0] - first[0] for first, second in pairwise(samples)),
                default=0,
            )
        mode = (
            "soak"
            if path.stem.endswith("soak")
            else "diagnostics"
            if path.stem.endswith("diagnostics")
            else "monitor"
        )
        dataset = "large" if record["large"] else "small"
        record["mode"] = mode
        groups[f"{record['candidate']}/{dataset}/{mode}"].append(record)
        records.append(record)
    if len(records) != completed["cases"]:
        raise ValueError("Completed case count disagrees with available reports")
    for candidate in ("qt", "wx", "imgui"):
        for dataset in ("small", "large"):
            if len(groups[f"{candidate}/{dataset}/monitor"]) != environment["repeats"]:
                raise ValueError("Missing Monitor repetition")
            if len(groups[f"{candidate}/{dataset}/diagnostics"]) != 1:
                raise ValueError("Missing Diagnostics measurement")
            if (
                environment["soak_seconds_per_candidate_and_dataset"]
                and len(groups[f"{candidate}/{dataset}/soak"]) != 1
            ):
                raise ValueError("Missing soak measurement")
    aggregates = {}
    for key, values in groups.items():
        aggregates[key] = {
            "runs": len(values),
            "median_cpu_one_core_percent": median(
                item["cpu_one_core_percent"] for item in values
            ),
            "maximum_peak_private_bytes": max(
                item["peak_private_bytes"] for item in values
            ),
            "maximum_peak_working_set_bytes": max(
                item["peak_working_set_bytes"] for item in values
            ),
            "median_producer_hz": median(item["producer_hz"] for item in values),
            "median_gui_intake_hz": median(item["gui_intake_hz"] for item in values),
            "median_of_run_frame_age_p95_ms": (
                median(
                    item["frame_age_p95_ms"]
                    for item in values
                    if item["gui_frame_intakes"]
                )
                if any(item["gui_frame_intakes"] for item in values)
                else None
            ),
            "median_process_creation_to_first_intake_ms": (
                median(
                    item["process_creation_to_first_intake_ms"]
                    for item in values
                    if item["process_creation_to_first_intake_ms"] >= 0
                )
                if any(
                    item["process_creation_to_first_intake_ms"] >= 0 for item in values
                )
                else None
            ),
        }
    result = {
        "environment": environment,
        "completed": completed,
        "limitations": [
            "Shared worker CPU included; not GUI-only CPU",
            "CPU percentage is one logical core equivalent, not total-machine utilization",
            "Frame intake is not display scanout or physical input response",
            "Private commit is not GPU memory",
            "Desktop activity and power behavior uncontrolled; no universal performance ranking",
            "No NDI or Scenario Runtime",
        ],
        "aggregates": aggregates,
        "runs": records,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summarize(args.source, args.output)


if __name__ == "__main__":
    main()
