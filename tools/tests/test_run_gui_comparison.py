from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from run_gui_comparison import plan_cases, run, validate_report


def test_qtquick_only_schedule_never_launches_existing_candidates() -> None:
    cases = plan_cases(180, 3, 0, 3, 1, ("qtquick",))
    assert len(cases) == 12
    assert {case[0] for case in cases} == {"qtquick"}
    for large in (False, True):
        for page in ("monitor", "diagnostics"):
            selected = [case for case in cases if case[1] == large and case[5] == page]
            assert len(selected) == 3
            assert all(case[3] == 180 and not case[4] for case in selected)


def test_three_minutes_three_repeats_include_each_mode_and_dataset() -> None:
    cases = plan_cases(180, 3, 180, 3, 3)
    assert len(cases) == 54
    for candidate in ("qt", "wx", "imgui"):
        for large in (False, True):
            selected = [c for c in cases if c[0] == candidate and c[1] == large]
            assert {c[2] for c in selected} == {
                f"{mode}-{i}"
                for mode in ("monitor", "diagnostics", "soak")
                for i in (1, 2, 3)
            }
            assert all(c[3] == 180 for c in selected)
            assert all(c[4] == c[2].startswith("soak") for c in selected)
    assert [c[0] for c in cases[:3]] == ["qt", "wx", "imgui"]
    assert [c[0] for c in cases[6:9]] == ["imgui", "wx", "qt"]


def test_original_schedule_and_optional_soak_are_preserved() -> None:
    original = plan_cases(120, 5, 1800, 1, 1)
    assert len(original) == 42
    assert original[30] == ("qt", False, "diagnostics", 120, False, "diagnostics")
    assert original[31] == ("qt", False, "soak", 1800, True, "monitor")
    short = plan_cases(180, 3, 0, 3, 1)
    assert len(short) == 36
    assert not any(c[4] for c in short)


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
    with (
        patch("run_gui_comparison.subprocess.check_output") as query,
        patch("run_gui_comparison.platform.platform", return_value="Windows-test"),
        patch("run_gui_comparison.platform.processor", return_value="test-processor"),
    ):
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
