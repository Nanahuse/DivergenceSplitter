from __future__ import annotations

from pathlib import Path

import pytest
from package_gui_comparison import (
    EXPECTED_CHECKS,
    classify,
    package,
    verify_smoke_report,
)


@pytest.mark.parametrize("candidate", ["qt", "wx", "imgui"])
def test_exit_success_without_gui_checks_is_not_accepted(candidate: str) -> None:
    with pytest.raises(ValueError, match="Incomplete/failed"):
        verify_smoke_report({"candidate": candidate, "self_test": True}, candidate)
    report = {
        "candidate": candidate,
        "self_test": True,
        "error": "",
        "checks": sorted(EXPECTED_CHECKS),
    }
    verify_smoke_report(report, candidate)
    report["error"] = "Failed after earlier checks"
    with pytest.raises(ValueError, match="Incomplete/failed"):
        verify_smoke_report(report, candidate)


def test_shared_dll_is_not_attributed_to_both_libraries() -> None:
    owners = {"jpeg62.dll": {"libjpeg-turbo"}}
    category, owner = classify(
        "bin/jpeg62.dll",
        owners,
        {"libjpeg-turbo", "wxwidgets"},
        {"libjpeg-turbo", "opencv4"},
    )
    assert category == "Shared GUI/OpenCV dependencies"
    assert owner == "libjpeg-turbo"


def test_imgui_static_code_is_not_reported_as_a_missing_dll() -> None:
    category, _ = classify("bin/comparison-imgui.exe", {}, {"imgui"}, {"opencv4"})
    assert "statically linked GUI code" in category


def test_reports_inside_distribution_are_rejected_before_modifying_files(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "distribution"
    stage.mkdir()
    with pytest.raises(ValueError, match="must be disjoint"):
        package(
            stage,
            tmp_path / "installed",
            "qt",
            stage / "reports",
            tmp_path / "manifest",
        )
    assert list(stage.iterdir()) == []
