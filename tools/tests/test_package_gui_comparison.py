from __future__ import annotations

from pathlib import Path

import pytest
from package_gui_comparison import (
    EXPECTED_CHECKS,
    QT_RUNTIME_CHECKS,
    classify,
    package,
    prepare,
    qml_file_owners,
    verify_qt_configuration,
    verify_qt_runtime_report,
    verify_smoke_report,
)


def test_qtquick_distribution_needs_qml_controls_not_only_dlls(tmp_path: Path) -> None:
    (tmp_path / "qwindows.dll").write_bytes(b"platform")
    with pytest.raises(ValueError, match="Fusion Controls QML"):
        prepare(tmp_path, tmp_path / "installed", "qtquick", tmp_path / "manifest")


def test_qml_metadata_ownership_uses_installed_paths(tmp_path: Path) -> None:
    info = tmp_path / "vcpkg/info"
    info.mkdir(parents=True)
    (info / "qtdeclarative_6.11.1_x64-windows.list").write_text(
        "x64-windows/Qt6/qml/QtQuick/Controls/Fusion/qmldir\n"
        "x64-windows/Qt6/qml/QtQuick/Controls/Fusion/\n"
        "x64-windows/debug/Qt6/qml/QtQuick/Controls/Fusion/qmldir\n",
        encoding="utf-8",
    )
    assert qml_file_owners(tmp_path) == {
        "qtquick/controls/fusion/qmldir": {"qtdeclarative"}
    }


@pytest.mark.parametrize("candidate", ["qt", "qtquick", "wx", "imgui", "webview2"])
def test_exit_success_without_gui_checks_is_not_accepted(candidate: str) -> None:
    with pytest.raises(ValueError, match="Incomplete/failed"):
        verify_smoke_report({"candidate": candidate, "self_test": True}, candidate)
    report = {
        "candidate": candidate,
        "self_test": True,
        "error": "",
        "checks": sorted(EXPECTED_CHECKS),
    }
    if candidate == "qtquick":
        with pytest.raises(ValueError, match="Incomplete/failed"):
            verify_smoke_report(report, candidate)
        report["checks"].extend(
            (
                "Q01_packaged_qml_imports_and_runtime",
                "Q02_qml_preview_and_reference_delegates",
            )
        )
    if candidate == "webview2":
        with pytest.raises(ValueError, match="Incomplete/failed"):
            verify_smoke_report(report, candidate)
        report["checks"].extend(
            (
                "W01_virtualized_rows_bounded",
                "W02_reload_keeps_core",
                "W03_renderer_failure_reload",
                "W04_browser_failure_recreation",
            )
        )
    if candidate in {"qt", "webview2"}:
        with pytest.raises(ValueError, match="Incomplete/failed"):
            verify_smoke_report(report, candidate)
        report["checks"].append("MC02_note_draft_apply_and_backend")
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


def test_qt_runtime_exit_success_without_focused_checks_is_rejected() -> None:
    with pytest.raises(ValueError, match="Qt runtime report"):
        verify_qt_runtime_report({"error": ""})
    verify_qt_runtime_report({"error": "", "checks": sorted(QT_RUNTIME_CHECKS)})
    with pytest.raises(ValueError, match="Qt runtime report"):
        verify_qt_runtime_report(
            {"error": "missing font", "checks": sorted(QT_RUNTIME_CHECKS)}
        )


@pytest.mark.parametrize(
    "dll", ["icudt78.dll", "libcrypto-3-x64.dll", "Qt6Sql.dll", "dxcompiler.dll"]
)
def test_removed_qt_runtime_cannot_be_silently_recollected(
    tmp_path: Path, dll: str
) -> None:
    installed = tmp_path / "installed"
    (installed / "vcpkg").mkdir(parents=True)
    features = (
        "widgets",
        "gui",
        "network",
        "dnslookup",
        "freetype",
        "harfbuzz",
        "jpeg",
        "png",
        "windeployqt",
    )
    status = "\n\n".join(
        f"Package: qtbase\nArchitecture: x64-windows\nFeature: {feature}"
        for feature in features
    )
    (installed / "vcpkg/status").write_text(status)
    root = tmp_path / "dist"
    (root / "bin").mkdir(parents=True)
    verify_qt_configuration(root, installed, "optimized")
    (root / "bin" / dll).write_bytes(b"recollected")
    with pytest.raises(ValueError, match="collected"):
        verify_qt_configuration(root, installed, "optimized")


def test_default_qt_feature_cannot_leak_into_lean_profile(tmp_path: Path) -> None:
    (tmp_path / "vcpkg").mkdir()
    (tmp_path / "vcpkg/status").write_text(
        "Package: qtbase\nArchitecture: x64-windows\nFeature: icu\n"
    )
    with pytest.raises(ValueError, match="feature selection"):
        verify_qt_configuration(tmp_path, tmp_path, "features")


@pytest.mark.parametrize("kind", ["generic", "styles"])
def test_removed_qt_plugin_type_cannot_be_recollected(
    tmp_path: Path, kind: str
) -> None:
    installed = tmp_path / "installed"
    (installed / "vcpkg").mkdir(parents=True)
    features = (
        "widgets",
        "gui",
        "network",
        "dnslookup",
        "freetype",
        "harfbuzz",
        "jpeg",
        "png",
        "windeployqt",
    )
    (installed / "vcpkg/status").write_text(
        "\n\n".join(
            f"Package: qtbase\nArchitecture: x64-windows\nFeature: {feature}"
            for feature in features
        )
    )
    root = tmp_path / "distribution"
    (root / "Qt6/plugins" / kind).mkdir(parents=True)
    with pytest.raises(ValueError, match="plugin type was re-collected"):
        verify_qt_configuration(root, installed, "optimized")
