"""Validate, measure and test a GUI comparison distribution and its extracted ZIP."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from measure_distribution import closure, extract_archive, installed_inventory, measure
from prepare_cpp_distribution import SDK_GRAPHICS_DLLS, collect_sdk_notices

GUI_PORTS = {
    "qt": "qtbase",
    "qtquick": "qtdeclarative",
    "wx": "wxwidgets",
    "imgui": "imgui",
    "webview2": "webview2",
}
QT_CONFIGURATIONS = ("standard", "features", "optimized")
QT_RUNTIME_CHECKS = {
    "windows_platform_plugin",
    "module_loaded_from_distribution",
    "japanese_font_fallback_has_glyphs",
    "input_method_enabled",
    "synthetic_ime_preedit_not_committed",
    "synthetic_ime_commit_roundtrip",
    "unicode_json_roundtrip",
    "image_encode",
    "image_decode",
    "tcp_unicode_roundtrip",
    "localhost_lookup",
    "schannel_tls_backend_available",
    "fusion_dark_palette",
    "fusion_palette_restored",
    "japanese_widget_capture",
}
EXPECTED_CHECKS = {
    "M01_monitor_and_latest_preview",
    "D02_value_updates_preserve_tree_expansion_scroll",
    "D05_collapse_releases_reference",
    "D04_hidden_diagnostics_stops_materialization",
    "D03_dynamic_topology_retains_surviving_expansion",
    "D05_deleted_expanded_detector_releases_reference",
    "C02_invalid_apply_keeps_applied_profile",
    "C01_valid_apply_reaches_worker",
    "MC01_enabled_draft_apply_and_backend",
    "C03_actual_file_dialog_cancel",
    "C03_actual_unsaved_confirmation_cancel",
    "R01_hold_cancel_and_single_trigger",
    "U01_theme_resize_handlers",
}


def verify_smoke_report(report: dict[str, Any], candidate: str) -> None:
    if (
        report.get("candidate") != candidate
        or report.get("error")
        or not report.get("self_test")
        or not EXPECTED_CHECKS.issubset(report.get("checks", []))
        or candidate == "qtquick"
        and not {
            "Q01_packaged_qml_imports_and_runtime",
            "Q02_qml_preview_and_reference_delegates",
        }.issubset(report.get("checks", []))
        or candidate == "webview2"
        and not {
            "W01_virtualized_rows_bounded",
            "W02_reload_keeps_core",
            "W03_renderer_failure_reload",
            "W04_browser_failure_recreation",
        }.issubset(report.get("checks", []))
        or candidate in {"qt", "webview2"}
        and "MC02_note_draft_apply_and_backend" not in report.get("checks", [])
    ):
        raise ValueError(f"Incomplete/failed GUI contract report: {candidate}")


def distribution_environment(root: Path) -> dict[str, str]:
    windows = Path(os.environ["SystemRoot"])
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("QT_", "QML", "OPENCV_", "NDI_"))
    }
    environment["PATH"] = os.pathsep.join(
        (str(root.resolve() / "bin"), str(windows / "System32"), str(windows))
    )
    return environment


def smoke(root: Path, candidate: str, report: Path, *, large: bool = False) -> None:
    environment = distribution_environment(root)
    if candidate == "qtquick":
        environment["GUI_DISTRIBUTION_ROOT"] = str(root.resolve())
    command = [
        str(root.resolve() / f"bin/comparison-{candidate}.exe"),
        "--self-test",
        "--report",
        str(report.resolve()),
    ]
    if large:
        command.append("--large")
    completed = subprocess.run(
        command,
        cwd=root,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=60,
    )
    report.with_suffix(".log").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    verify_smoke_report(json.loads(report.read_text(encoding="utf-8")), candidate)


def verify_qt_configuration(root: Path, installed: Path, configuration: str) -> None:
    if configuration not in QT_CONFIGURATIONS:
        raise ValueError("Unknown Qt configuration")
    if configuration == "standard":
        return
    status = (installed / "vcpkg/status").read_text(encoding="utf-8")
    features = set()
    for block in status.split("\n\n"):
        fields = dict(
            line.split(": ", 1) for line in block.splitlines() if ": " in line
        )
        if (
            fields.get("Package") == "qtbase"
            and fields.get("Architecture") == "x64-windows"
        ):
            features.add(fields.get("Feature", "core"))
    required = {
        "widgets",
        "gui",
        "network",
        "dnslookup",
        "freetype",
        "harfbuzz",
        "jpeg",
        "png",
        "windeployqt",
    }
    if not required.issubset(features) or features & {
        "icu",
        "openssl",
        "sql",
        "sql-psql",
        "sql-sqlite",
    }:
        raise ValueError(f"Unexpected lean Qt feature selection: {sorted(features)}")
    dlls = {path.name.casefold() for path in root.rglob("*.dll")}
    if any(name.startswith(("icu", "libcrypto", "libssl", "qt6sql")) for name in dlls):
        raise ValueError("Removed Qt feature DLL was collected into lean distribution")
    if configuration == "optimized":
        if dlls & SDK_GRAPHICS_DLLS:
            raise ValueError("Excluded SDK graphics DLL was re-collected")
        if any(
            (root / "Qt6/plugins" / kind).exists() for kind in ("generic", "styles")
        ):
            raise ValueError("Excluded Qt plugin type was re-collected")
    elif not SDK_GRAPHICS_DLLS.issubset(dlls):
        raise ValueError(
            "Feature-only configuration must keep standard SDK graphics deployment"
        )


def verify_qt_runtime_report(report: dict[str, Any]) -> None:
    if report.get("error") or not QT_RUNTIME_CHECKS.issubset(report.get("checks", [])):
        raise ValueError("Incomplete/failed Qt runtime report")


def qt_runtime_check(root: Path, probe: Path, output: Path, label: str) -> None:
    # Copy only the test executable: the build directory contains app-local development DLLs.
    # Loader PATH and Qt's explicit library paths must resolve to the measured distribution.
    isolated = output / f"{label}-runtime-probe"
    isolated.mkdir()
    executable = isolated / "qt-runtime-check.exe"
    shutil.copy2(probe, executable)
    report = output / f"{label}-qt-runtime.json"
    environment = distribution_environment(root)
    environment["QT_DEBUG_PLUGINS"] = "1"
    completed = subprocess.run(
        [
            str(executable),
            str(root.resolve()),
            str(report),
            str(output / f"{label}-japanese.png"),
        ],
        cwd=isolated,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        check=False,
    )
    (output / f"{label}-qt-runtime.log").write_text(
        completed.stdout + completed.stderr, encoding="utf-8"
    )
    if completed.returncode:
        raise ValueError(
            f"Qt runtime probe failed ({completed.returncode}); see {label}-qt-runtime.log/json"
        )
    verify_qt_runtime_report(json.loads(report.read_text(encoding="utf-8")))


def prepare(root: Path, installed: Path, candidate: str, manifest: Path) -> None:
    required = [
        f"bin/comparison-{candidate}.exe",
        "bin/msvcp140.dll",
        "bin/vcruntime140.dll",
        "LICENSE",
        "DISTRIBUTION-NOTICE.txt",
        "licenses/msvc/MSVC-NOTICE.txt",
    ]
    if candidate in ("qt", "qtquick"):
        components = (
            ("Core", "Gui", "Widgets")
            if candidate == "qt"
            else ("Core", "Gui", "Qml", "Quick", "QuickControls2")
        )
        required += [f"bin/Qt6{component}.dll" for component in components]
        if not list(root.rglob("qwindows.dll")):
            raise ValueError("Missing Qt Windows platform plugin")
        if candidate == "qtquick" and not any(
            path.parent.as_posix().endswith("QtQuick/Controls/Fusion")
            for path in root.rglob("qmldir")
        ):
            raise ValueError("Missing deployed Qt Quick Fusion Controls QML module")
    for relative in required:
        if not (root / relative).is_file() or not (root / relative).stat().st_size:
            raise ValueError(f"Missing required distribution file: {relative}")
    for component in ("core", "imgproc", "imgcodecs", "img_hash", "videoio"):
        if not list((root / "bin").glob(f"opencv_{component}*.dll")):
            raise ValueError(f"Missing OpenCV component: {component}")
    if candidate == "wx" and not list((root / "bin").glob("wx*core*.dll")):
        raise ValueError("Missing wxWidgets core DLL")
    if candidate == "webview2":
        for relative in ("bin/WebView2Loader.dll", "bin/ui/index.html"):
            if not (root / relative).is_file():
                raise ValueError(f"Missing WebView2 distribution file: {relative}")
        if not list((root / "bin/ui/assets").glob("*.js")):
            raise ValueError("Missing built TypeScript UI")
        if list(root.rglob("Qt6*.dll")):
            raise ValueError("WebView2 candidate must not depend on Qt")
    owners, _ = installed_inventory(installed)
    metadata = root / "build-metadata"
    metadata.mkdir(parents=True, exist_ok=True)
    collect_sdk_notices(root)
    notices = root / "licenses/vcpkg"
    for share in sorted((installed / "x64-windows/share").iterdir()):
        if (share / "copyright").is_file():
            destination = notices / share.name
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(share / "copyright", destination / "copyright")
            for spdx in share.glob("*.spdx.json"):
                shutil.copy2(spdx, metadata / f"{share.name}-{spdx.name}")
    for package in (GUI_PORTS[candidate], "opencv4"):
        if not (notices / package / "copyright").is_file():
            raise ValueError(f"Missing dependency notice: {package}")
    if candidate == "webview2":
        ui = (
            Path(__file__).resolve().parents[1]
            / "experiments/gui-comparison/webview2/ui"
        )
        for name in ("react", "react-dom", "scheduler", "zod"):
            package_root = ui / "node_modules" / name
            notice = next(
                (
                    package_root / n
                    for n in ("LICENSE", "LICENSE.md")
                    if (package_root / n).is_file()
                ),
                None,
            )
            if notice is None:
                raise ValueError(f"Missing bundled npm notice: {name}")
            destination = root / "licenses/npm" / name
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(notice, destination / notice.name)
            shutil.copy2(package_root / "package.json", destination / "package.json")
        shutil.copy2(ui / "package-lock.json", metadata / "package-lock.json")
    forbidden = {".pdb", ".lib", ".a", ".obj", ".h", ".hpp", ".ilk", ".exp"}
    for path in root.rglob("*"):
        if path.suffix.casefold() in forbidden or path.name.casefold() == "debug":
            raise ValueError(f"Development file in distribution: {path}")
        if path.suffix.casefold() != ".dll":
            continue
        name = path.name.casefold()
        if name.startswith(("processing.ndi", "libndi", "ndi.")):
            raise ValueError(f"NDI is excluded from every candidate: {path}")
        runtime = name.startswith(("msvcp", "vcruntime", "concrt", "vccorlib", "vcomp"))
        if runtime and name.endswith("d.dll"):
            raise ValueError(f"Debug MSVC runtime: {path}")
        if not owners.get(name) and name not in SDK_GRAPHICS_DLLS and not runtime:
            raise ValueError(f"DLL has no known owner: {path}")
        for owner in owners.get(name, set()):
            if not (notices / owner / "copyright").is_file():
                raise ValueError(f"Missing owner notice: {owner}")
    shutil.copy2(manifest, metadata / "vcpkg.json")
    shutil.copy2(installed / "vcpkg/status", metadata / "vcpkg-status.txt")
    toolchain = {
        "candidate": candidate,
        "image": os.environ.get("ImageVersion", "local"),
        "msvc_tools": os.environ.get("VCToolsVersion", "unknown"),
        "windows_sdk": os.environ.get("WindowsSDKVersion", "unknown"),
        "source_commit": os.environ.get("GITHUB_SHA", "local working tree"),
        "triplet": "x64-windows",
        "ndi": "excluded; not tested",
        "cmake": subprocess.check_output(["cmake", "--version"], text=True).strip(),
        "ninja": subprocess.check_output(["ninja", "--version"], text=True).strip(),
    }
    (metadata / "toolchain.json").write_text(
        json.dumps(toolchain, indent=2) + "\n", encoding="utf-8"
    )


def classify(
    path: str, owners: dict[str, set[str]], gui: set[str], cv: set[str]
) -> tuple[str, str]:
    name = Path(path).name.casefold()
    packages = owners.get(name, set())
    if name.endswith(".exe"):
        return "Application (including statically linked GUI code)", "application"
    if path.startswith(("licenses/", "build-metadata/")) or "NOTICE" in path:
        return "Notices and metadata", ""
    if path.startswith("bin/ui/"):
        return (
            "Web UI assets (React/TypeScript/CSS)",
            "application and npm dependencies",
        )
    if name in SDK_GRAPHICS_DLLS:
        return "Windows SDK graphics runtime", "Windows SDK redistributable"
    if name.startswith(("msvcp", "vcruntime", "concrt", "vccorlib", "vcomp")):
        return "MSVC Runtime", "MSVC redistributable"
    if packages & gui and packages & cv:
        return "Shared GUI/OpenCV dependencies", ", ".join(sorted(packages))
    if packages & gui:
        return "GUI and dependencies/plugins", ", ".join(sorted(packages))
    if packages & cv:
        return "OpenCV and dependencies", ", ".join(sorted(packages))
    return "Other", ", ".join(sorted(packages))


def qml_file_owners(installed: Path) -> dict[str, set[str]]:
    """Keep QML source/metadata bytes with their actual installed package owner."""
    owners: dict[str, set[str]] = {}
    prefix = "x64-windows/Qt6/qml/"
    for listing in (installed / "vcpkg/info").glob("*_x64-windows.list"):
        package_name = listing.name.split("_", 1)[0]
        for path in listing.read_text(encoding="utf-8").splitlines():
            if path.startswith(prefix) and not path.endswith("/"):
                owners.setdefault(path[len(prefix) :].casefold(), set()).add(
                    package_name
                )
    return owners


def package(
    root: Path,
    installed: Path,
    candidate: str,
    output: Path,
    manifest: Path,
    *,
    qt_configuration: str = "standard",
    qt_runtime_probe: Path | None = None,
):
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Distribution and reports must be disjoint")
    if candidate != "qt" and qt_configuration != "standard":
        raise ValueError("Qt configuration requires Qt candidate")
    if candidate == "qt":
        verify_qt_configuration(root, installed, qt_configuration)
    prepare(root, installed, candidate, manifest)
    output.mkdir(parents=True, exist_ok=True)
    smoke(root, candidate, output / "installed-smoke.json")
    if candidate == "qt" and qt_runtime_probe:
        qt_runtime_check(root, qt_runtime_probe.resolve(), output, "installed")
    # Reuse the existing exact ZIP conditions; replace Qt-specific categories below.
    report = measure(root, output, f"GUI comparison: {candidate}", "cpp", installed)
    owners, graph = installed_inventory(installed)
    gui, cv = closure(graph, {GUI_PORTS[candidate]}), closure(graph, {"opencv4"})
    qml_owners = qml_file_owners(installed) if candidate == "qtquick" else {}
    totals: Counter[str] = Counter()
    for item in report["files"]:
        item["category"], item["owner"] = classify(item["path"], owners, gui, cv)
        qml_prefix = next(
            (
                prefix
                for prefix in ("Qt6/qml/", "qml/")
                if item["path"].startswith(prefix)
            ),
            None,
        )
        if candidate == "qtquick" and qml_prefix:
            packages = qml_owners.get(item["path"][len(qml_prefix) :].casefold(), set())
            if not packages:
                raise ValueError(
                    f"QML runtime file has no installed owner: {item['path']}"
                )
            item["category"] = "GUI and dependencies/plugins"
            item["owner"] = ", ".join(sorted(packages))
        totals[item["category"]] += item["bytes"]
    variant = candidate if qt_configuration == "standard" else f"qt-{qt_configuration}"
    report.update(
        kind="gui-comparison",
        candidate=candidate,
        ndi_status="EXCLUDED from all candidates; not tested",
        categories=dict(sorted(totals.items())),
        archive=f"{variant}.zip",
    )
    if candidate == "qt":
        report["qt_configuration"] = qt_configuration
    if candidate == "webview2":
        report["runtime_requirement"] = (
            "Evergreen WebView2 Runtime required; detected at startup, excluded from app ZIP. "
            "Host-only CPU/memory reports must not be used for comparison."
        )
    archive = output / f"{variant}.zip"
    (output / "cpp.zip").rename(archive)
    extracted = output / "zip-extracted"
    extract_archive(archive, extracted)
    smoke(extracted / "distribution", candidate, output / "zip-smoke.json", large=True)
    if candidate == "qt":
        verify_qt_configuration(extracted / "distribution", installed, qt_configuration)
        if qt_runtime_probe:
            qt_runtime_check(
                extracted / "distribution", qt_runtime_probe.resolve(), output, "zip"
            )
    report["verification"] = {
        "installed_small_gui_contract": "passed with developer PATH removed",
        "extracted_zip_large_gui_contract": "passed with developer PATH removed",
    }
    if candidate == "qt" and qt_runtime_probe:
        report["verification"]["qt_installed_and_extracted_runtime"] = (
            "passed; synthetic IME events only, native IME conversion not tested"
        )
    (output / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "files.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=report["files"][0].keys())
        writer.writeheader()
        writer.writerows(report["files"])
    lines = [
        f"# {variant}: measured GUI distribution",
        "",
        f"Unpacked: {report['unpacked_bytes']:,} bytes; ZIP: {report['zip_bytes']:,} bytes.",
        "NDI excluded. Outer Actions Artifact size is a separate transport archive.",
        "Installed and extracted-ZIP GUI contracts passed with developer PATH removed.",
        "",
        "| Category | Bytes |",
        "| --- | ---: |",
    ]
    lines += [f"| {key} | {value:,} |" for key, value in sorted(totals.items())]
    lines += [
        "",
        "ImGui is linked statically: its code is included in the executable category.",
        "ZIP conditions: `" + json.dumps(report["zip_settings"], sort_keys=True) + "`",
        "",
    ]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines[:6]))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", choices=GUI_PORTS, required=True)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--qt-configuration", choices=QT_CONFIGURATIONS, default="standard"
    )
    parser.add_argument("--qt-runtime-probe", type=Path)
    parser.add_argument(
        "--manifest", type=Path, default=Path("experiments/gui-comparison/vcpkg.json")
    )
    args = parser.parse_args()
    package(
        args.root,
        args.installed,
        args.candidate,
        args.output,
        args.manifest,
        qt_configuration=args.qt_configuration,
        qt_runtime_probe=args.qt_runtime_probe,
    )


if __name__ == "__main__":
    main()
