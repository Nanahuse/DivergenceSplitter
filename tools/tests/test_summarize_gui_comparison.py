from __future__ import annotations

import json
from pathlib import Path

import pytest
from summarize_gui_comparison import summarize


def measurements(root: Path) -> None:
    root.mkdir()
    environment = {
        "repeats": 1,
        "logical_cpus": 12,
        "soak_seconds_per_candidate_and_dataset": 0,
    }
    (root / "environment.json").write_text(json.dumps(environment), encoding="utf-8")
    (root / "completed.json").write_text('{"cases": 12}', encoding="utf-8")
    for candidate in ("qt", "wx", "imgui"):
        for large in (False, True):
            for mode in ("monitor-1", "diagnostics"):
                data = {
                    "candidate": candidate,
                    "large": large,
                    "self_test": False,
                    "error": "",
                    "measurement_seconds": 120,
                    "cpu_seconds": 12,
                    "generated_frames": 7200,
                    "gui_frame_intakes": 1800,
                    "peak_private_bytes": 150,
                    "peak_working_set_bytes": 300,
                    "frame_age_p95_ms": 20,
                    "process_creation_to_first_intake_ms": 100,
                    "memory_samples": [[0, 100, 200], [60, 130, 260], [119, 150, 300]],
                }
                name = f"{candidate}-{'large' if large else 'small'}-{mode}.json"
                (root / name).write_text(json.dumps(data), encoding="utf-8")


def test_cpu_units_rates_and_memory_buckets_are_preserved(tmp_path: Path) -> None:
    source = tmp_path / "measurements"
    measurements(source)
    output = tmp_path / "summary.json"
    summarize(source, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    aggregate = result["aggregates"]["qt/small/monitor"]
    assert aggregate["median_cpu_one_core_percent"] == 10  # Do not divide by 12 cores.
    assert aggregate["median_producer_hz"] == 60
    assert aggregate["median_gui_intake_hz"] == 15
    run = next(item for item in result["runs"] if item["name"] == "qt-small-monitor-1")
    assert run["private_bytes_per_minute"]["1"]["median"] == 140
    assert run["private_first_to_last_minute_median_delta"] == 40


def test_no_frame_intake_is_unavailable_instead_of_zero_latency(tmp_path: Path) -> None:
    source = tmp_path / "measurements"
    measurements(source)
    path = source / "qt-small-diagnostics.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record.update(
        gui_frame_intakes=0, frame_age_p95_ms=0, process_creation_to_first_intake_ms=100
    )
    path.write_text(json.dumps(record), encoding="utf-8")
    output = tmp_path / "summary.json"
    summarize(source, output)
    group = json.loads(output.read_text(encoding="utf-8"))["aggregates"][
        "qt/small/diagnostics"
    ]
    assert group["median_of_run_frame_age_p95_ms"] is None
    assert group["median_process_creation_to_first_intake_ms"] is None


def test_numbered_diagnostics_and_soak_runs_are_grouped_and_required(
    tmp_path: Path,
) -> None:
    source = tmp_path / "measurements"
    measurements(source)
    env = {
        "repeats": 1,
        "diagnostics_repeats": 3,
        "soak_repeats": 3,
        "soak_seconds_per_candidate_and_dataset": 180,
    }
    (source / "environment.json").write_text(json.dumps(env), encoding="utf-8")
    for c in ("qt", "wx", "imgui"):
        for dataset in ("small", "large"):
            original = source / f"{c}-{dataset}-diagnostics.json"
            contents = original.read_text(encoding="utf-8")
            original.unlink()
            for mode in ("diagnostics", "soak"):
                for repeat in (1, 2, 3):
                    (source / f"{c}-{dataset}-{mode}-{repeat}.json").write_text(
                        contents, encoding="utf-8"
                    )
    (source / "completed.json").write_text('{"cases": 42}', encoding="utf-8")
    output = tmp_path / "summary.json"
    summarize(source, output)
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["aggregates"]["qt/small/diagnostics"]["runs"] == 3
    assert result["aggregates"]["wx/large/soak"]["runs"] == 3
    (source / "imgui-large-diagnostics-3.json").unlink()
    (source / "completed.json").write_text('{"cases": 41}', encoding="utf-8")
    with pytest.raises(ValueError, match="Missing Diagnostics"):
        summarize(source, output)


@pytest.mark.parametrize("invalidated", [False, True])
def test_incomplete_or_invalidated_measurements_cannot_be_reported_as_success(
    tmp_path: Path, invalidated: bool
) -> None:
    source = tmp_path / "measurements"
    measurements(source)
    if invalidated:
        (source / "invalidated.json").write_text("{}", encoding="utf-8")
    else:
        (source / "qt-small-monitor-1.json").unlink()
    output = tmp_path / "summary.json"
    with pytest.raises(ValueError):
        summarize(source, output)
    assert not output.exists()
