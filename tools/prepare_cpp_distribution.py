"""Collect vcpkg license/source inventories and validate the installed probe."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from pathlib import Path

from measure_distribution import installed_inventory, sha256

SDK_GRAPHICS_DLLS = {"d3dcompiler_47.dll", "dxcompiler.dll", "dxil.dll"}


def collect_sdk_notices(root: Path) -> None:
    """Verify Qt's default graphics deployment against SDK redistributables."""
    deployed = [
        root / "bin" / name
        for name in sorted(SDK_GRAPHICS_DLLS)
        if (root / "bin" / name).is_file()
    ]
    if not deployed:
        return
    sdk_dir = os.environ.get("WindowsSdkDir")
    sdk_version = os.environ.get("WindowsSDKVersion", "").rstrip("\\/")
    if not sdk_dir or not sdk_version:
        raise ValueError(
            "Windows SDK environment required to verify graphics DLL provenance"
        )
    sdk = Path(sdk_dir)
    notices = root / "licenses/windows-sdk"
    notices.mkdir(parents=True, exist_ok=True)
    records = []
    for dll in deployed:
        original = sdk / "Redist/D3D/x64" / dll.name
        if not original.is_file() or sha256(original) != sha256(dll):
            raise ValueError(
                f"Graphics DLL does not match SDK x64 redistributable: {dll}"
            )
        records.append(
            {
                "file": dll.name,
                "source": f"Redist/D3D/x64/{dll.name}",
                "sha256": sha256(dll),
            }
        )
    for name in ("sdk_license.rtf", "sdk_third_party_notices.rtf"):
        original = sdk / "Licenses" / sdk_version / name
        if not original.is_file() or not original.stat().st_size:
            raise ValueError(f"Windows SDK license/notice missing: {original}")
        shutil.copy2(original, notices / name)
    (root / "build-metadata/windows-sdk-graphics.json").write_text(
        json.dumps({"sdk_version": sdk_version, "files": records}, indent=2) + "\n",
        encoding="utf-8",
    )


def prepare(root: Path, installed: Path, manifest: Path) -> None:
    required = [
        "bin/size-probe.exe",
        "bin/Qt6Core.dll",
        "bin/Qt6Gui.dll",
        "bin/Qt6Widgets.dll",
        "bin/Qt6Network.dll",
        "bin/Qt6WebSockets.dll",
        "LICENSE",
        "DISTRIBUTION-NOTICE.txt",
        "ndi-status.txt",
        "licenses/msvc/MSVC-NOTICE.txt",
    ]
    for relative in required:
        path = root / relative
        if not path.is_file() or not path.stat().st_size:
            raise ValueError(f"Missing or empty distribution file: {path}")
    if not list(root.rglob("qwindows.dll")):
        raise ValueError("Windows Qt platform plugin is missing")
    for component in ("core", "imgproc", "imgcodecs", "img_hash", "videoio"):
        if not list((root / "bin").glob(f"opencv_{component}*.dll")):
            raise ValueError(f"OpenCV component missing: {component}")
    if (
        not list((root / "bin").glob("vcruntime140*.dll"))
        or not (root / "bin/msvcp140.dll").is_file()
    ):
        raise ValueError("App-local MSVC runtime DLLs missing")
    owners, _ = installed_inventory(installed)
    licenses = root / "licenses/vcpkg"
    metadata = root / "build-metadata"
    licenses.mkdir(parents=True, exist_ok=True)
    metadata.mkdir(parents=True, exist_ok=True)
    collect_sdk_notices(root)
    # Keep every installed port notice, including build-only dependencies. This
    # avoids brittle manual license lists and records the conservative overhead.
    for share in sorted((installed / "x64-windows/share").iterdir()):
        copyright_file = share / "copyright"
        if copyright_file.is_file():
            destination = licenses / share.name
            destination.mkdir(exist_ok=True)
            shutil.copy2(copyright_file, destination / "copyright")
            for spdx in share.glob("*.spdx.json"):
                shutil.copy2(spdx, metadata / f"{share.name}-{spdx.name}")
    for dll in root.rglob("*.dll"):
        name = dll.name.casefold()
        if name.startswith(
            ("msvcp", "vcruntime", "concrt", "vccorlib")
        ) and name.endswith("d.dll"):
            raise ValueError(f"Debug MSVC runtime in distribution: {dll}")
        packages = owners.get(name, set())
        for package in packages:
            notice = licenses / package / "copyright"
            if not notice.is_file() or not notice.stat().st_size:
                raise ValueError(f"License missing for {dll}: {package}")
        if (
            not packages
            and name not in SDK_GRAPHICS_DLLS
            and not name.startswith(
                ("vcruntime", "msvcp", "concrt", "vccorlib", "vcomp", "processing.ndi.")
            )
        ):
            raise ValueError(f"DLL has no vcpkg owner or known vendor: {dll}")
    for package in ("qtbase", "qtwebsockets", "opencv4"):
        if not (licenses / package / "copyright").is_file():
            raise ValueError(f"Required dependency notice missing: {package}")
    status = (root / "ndi-status.txt").read_text(encoding="utf-8")
    if not status.startswith("UNVERIFIED"):
        for relative in (
            "bin/Processing.NDI.Lib.x64.dll",
            "licenses/ndi/Processing.NDI.Lib.Licenses.txt",
        ):
            if not (root / relative).is_file() or not (root / relative).stat().st_size:
                raise ValueError(f"NDI redistribution component missing: {relative}")
        if len(list((root / "licenses/ndi").iterdir())) < 2:
            raise ValueError("Official NDI SDK license agreement missing")
    forbidden = {".pdb", ".lib", ".a", ".obj", ".h", ".hpp", ".ilk", ".exp"}
    for path in root.rglob("*"):
        if path.suffix.casefold() in forbidden or path.name.casefold() == "debug":
            raise ValueError(f"Development file in distribution: {path}")
    shutil.copy2(manifest, metadata / "vcpkg.json")
    shutil.copy2(installed / "vcpkg/status", metadata / "vcpkg-status.txt")
    (metadata / "toolchain.json").write_text(
        json.dumps(
            {
                "runner_image": os.environ.get("ImageVersion", "local"),
                "msvc_tools": os.environ.get("VCToolsVersion", "unknown"),
                "windows_sdk": os.environ.get("WindowsSDKVersion", "unknown"),
                "cmake": subprocess.check_output(
                    ["cmake", "--version"], text=True
                ).strip(),
                "ninja": subprocess.check_output(
                    ["ninja", "--version"], text=True
                ).strip(),
                "source_commit": os.environ.get("GITHUB_SHA", "local working tree"),
                "triplet": "x64-windows",
                "ndi_sdk_archive_sha256": os.environ.get(
                    "NDI_SDK_SHA256", "not supplied"
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def smoke(root: Path) -> None:
    """Use only the distribution and Windows system DLLs, away from the build."""
    root = root.resolve()
    env = os.environ.copy()
    windows = Path(os.environ["SystemRoot"])
    env["PATH"] = os.pathsep.join(
        (str(root / "bin"), str(windows / "System32"), str(windows))
    )
    for name in list(env):
        if name.startswith(("QT_", "QML", "NDI_", "OPENCV_")):
            del env[name]
    command = [str(root / "bin/size-probe.exe"), "--self-test"]
    if (
        not (root / "ndi-status.txt")
        .read_text(encoding="utf-8")
        .startswith("UNVERIFIED")
    ):
        command.append("--require-ndi")
    completed = subprocess.run(
        command,
        cwd=root,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=45,
    )
    (root / "build-metadata/smoke-test.txt").write_text(
        "Deployed executable self-test passed with development PATH removed.\n"
        + completed.stdout
        + completed.stderr,
        encoding="utf-8",
    )
    if "--require-ndi" in command:
        (root / "ndi-status.txt").write_text(
            "VERIFIED: official SDK runtime bundled; dynamic loading and initialization passed.\n",
            encoding="utf-8",
        )
    print(completed.stdout)
    print(completed.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--installed", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    args = parser.parse_args()
    prepare(args.root, args.installed, args.manifest)
    smoke(args.root)


if __name__ == "__main__":
    main()
