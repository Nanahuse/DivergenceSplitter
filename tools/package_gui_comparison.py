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

GUI_PORTS = {"qt": "qtbase", "wx": "wxwidgets", "imgui": "imgui"}
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
    ):
        raise ValueError(f"Incomplete/failed GUI contract report: {candidate}")


def smoke(root: Path, candidate: str, report: Path, *, large: bool = False) -> None:
    windows = Path(os.environ["SystemRoot"])
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("QT_", "QML", "OPENCV_", "NDI_"))
    }
    environment["PATH"] = os.pathsep.join(
        (str(root.resolve() / "bin"), str(windows / "System32"), str(windows))
    )
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


def prepare(root: Path, installed: Path, candidate: str, manifest: Path) -> None:
    required = [
        f"bin/comparison-{candidate}.exe",
        "bin/msvcp140.dll",
        "bin/vcruntime140.dll",
        "LICENSE",
        "DISTRIBUTION-NOTICE.txt",
        "licenses/msvc/MSVC-NOTICE.txt",
    ]
    if candidate == "qt":
        required += [
            f"bin/Qt6{component}.dll" for component in ("Core", "Gui", "Widgets")
        ]
        if not list(root.rglob("qwindows.dll")):
            raise ValueError("Missing Qt Windows platform plugin")
    for relative in required:
        if not (root / relative).is_file() or not (root / relative).stat().st_size:
            raise ValueError(f"Missing required distribution file: {relative}")
    for component in ("core", "imgproc", "imgcodecs", "img_hash", "videoio"):
        if not list((root / "bin").glob(f"opencv_{component}*.dll")):
            raise ValueError(f"Missing OpenCV component: {component}")
    if candidate == "wx" and not list((root / "bin").glob("wx*core*.dll")):
        raise ValueError("Missing wxWidgets core DLL")
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


def package(root: Path, installed: Path, candidate: str, output: Path, manifest: Path):
    root, output = root.resolve(), output.resolve()
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Distribution and reports must be disjoint")
    prepare(root, installed, candidate, manifest)
    output.mkdir(parents=True, exist_ok=True)
    smoke(root, candidate, output / "installed-smoke.json")
    # Reuse the existing exact ZIP conditions; replace Qt-specific categories below.
    report = measure(root, output, f"GUI comparison: {candidate}", "cpp", installed)
    owners, graph = installed_inventory(installed)
    gui, cv = closure(graph, {GUI_PORTS[candidate]}), closure(graph, {"opencv4"})
    totals: Counter[str] = Counter()
    for item in report["files"]:
        item["category"], item["owner"] = classify(item["path"], owners, gui, cv)
        totals[item["category"]] += item["bytes"]
    report.update(
        kind="gui-comparison",
        candidate=candidate,
        ndi_status="EXCLUDED from all candidates; not tested",
        categories=dict(sorted(totals.items())),
        archive=f"{candidate}.zip",
    )
    archive = output / f"{candidate}.zip"
    (output / "cpp.zip").rename(archive)
    extracted = output / "zip-extracted"
    extract_archive(archive, extracted)
    smoke(extracted / "distribution", candidate, output / "zip-smoke.json", large=True)
    report["verification"] = {
        "installed_small_gui_contract": "passed with developer PATH removed",
        "extracted_zip_large_gui_contract": "passed with developer PATH removed",
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    with (output / "files.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=report["files"][0].keys())
        writer.writeheader()
        writer.writerows(report["files"])
    lines = [
        f"# {candidate}: measured GUI distribution",
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
        "--manifest", type=Path, default=Path("experiments/gui-comparison/vcpkg.json")
    )
    args = parser.parse_args()
    package(args.root, args.installed, args.candidate, args.output, args.manifest)


if __name__ == "__main__":
    main()
