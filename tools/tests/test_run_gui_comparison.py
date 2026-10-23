from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from run_gui_comparison import run, validate_report


def test_successful_process_exit_without_report_is_not_a_pass(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="exited without a report"):
        validate_report(tmp_path / "qt-small-soak.json", "qt", False, 1800, True)


@pytest.mark.parametrize(
    "override",
    [
        {"candidate": "wx"},
        {"error": "failure"},
        {"measurement_seconds": 100},
        {"exercise_steps": 10},
    ],
)
def test_resume_rejects_invalid_or_shortened_reports(
    tmp_path: Path, override: dict
) -> None:
    report = tmp_path / "qt-small-soak.json"
    data = {
        "candidate": "qt",
        "large": False,
        "error": "",
        "generated_frames": 100,
        "measurement_seconds": 1800,
        "exercise_steps": 1000,
    }
    report.write_text(json.dumps(data | override), encoding="utf-8")
    with pytest.raises(RuntimeError):
        validate_report(report, "qt", False, 1800, True)


def test_resume_refuses_changed_binaries_before_launching_a_gui(tmp_path: Path) -> None:
    distribution = tmp_path / "distribution"
    for candidate in ("qt", "wx", "imgui"):
        binary = distribution / candidate / f"bin/comparison-{candidate}.exe"
        binary.parent.mkdir(parents=True)
        binary.write_bytes(b"changed executable")
    output = tmp_path / "measurements"
    output.mkdir()
    (output / "environment.json").write_text(
        json.dumps({"binary_sha256": {"qt": "original"}}), encoding="utf-8"
    )
    with patch("run_gui_comparison.subprocess.check_output") as query:
        query.side_effect = [
            b"381b4222-f694-41f0-9685-ff5bb260df2e",
            "source",
            "",
        ]
        with patch("run_gui_comparison.subprocess.run") as launch:
            with pytest.raises(ValueError, match="binary_sha256"):
                run(
                    distribution,
                    output,
                    warmup=30,
                    seconds=120,
                    repeats=5,
                    soak=1800,
                    resume=True,
                )
            launch.assert_not_called()
