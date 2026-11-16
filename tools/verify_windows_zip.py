"""Verify redistribution contents and launch the extracted Windows package."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from collections import Counter
from pathlib import Path, PurePosixPath

import collect_licenses


SCENARIO = """schema_version: 2
start_condition: {type: elapsed, duration: 1s}
splits: []
"""


def verify_archive_names(names: list[str]) -> None:
    normalized = [name.casefold() for name in names if name and not name.endswith("/")]
    duplicates = sorted(
        name for name, count in Counter(normalized).items() if count > 1
    )
    if duplicates:
        raise RuntimeError(
            "ZIP contains duplicate entries: " + ", ".join(duplicates)
        )

    dlls = [
        PurePosixPath(name)
        for name in names
        if name and PurePosixPath(name).suffix.casefold() == ".dll"
    ]
    duplicate_dlls = sorted(
        name for name, count in Counter(path.name.casefold() for path in dlls).items()
        if count > 1
    )
    if duplicate_dlls:
        raise RuntimeError(
            "ZIP contains duplicate DLL copies: " + ", ".join(duplicate_dlls)
        )
    outside_root = [str(path) for path in dlls if len(path.parts) != 1]
    if outside_root:
        raise RuntimeError(
            "ZIP stores DLLs outside the package root: " + ", ".join(outside_root)
        )


def verify_contents(root: Path, lock: dict[str, str]) -> None:
    required = [
        "DivergenceSplitter.exe",
        "ScenarioBuilder.exe",
        "scenario-builder-ui/index.html",
        "opencv_core4.dll",
        "LICENSE.txt",
        "DISTRIBUTION-NOTICE.txt",
        "licenses/components.json",
        "licenses/NDI-TERMS.txt",
        "licenses/webview2.txt",
    ]
    for name in required:
        if not (root / name).is_file() or not (root / name).stat().st_size:
            raise RuntimeError(f"ZIP missing required distribution file: {name}")
    ui_assets = root / "scenario-builder-ui" / "assets"
    if not ui_assets.is_dir() or not any(
        file.is_file() and file.stat().st_size for file in ui_assets.rglob("*")
    ):
        raise RuntimeError("ZIP is missing the built Scenario Builder UI assets")
    if (root / "divergencesplitter-cli.exe").exists():
        raise RuntimeError("ZIP still contains the removed product CLI")
    if (root / "vc_redist.x64.exe").exists():
        raise RuntimeError("ZIP contains the Visual C++ Redistributable installer")
    for name in ("Qt6Core.dll", "platforms/qwindows.dll"):
        if (root / name).exists():
            raise RuntimeError(f"ZIP still contains Qt runtime: {name}")
    for name in ("Processing.NDI.Lib.x64.dll", "Processing.NDI.Lib.Licenses.txt"):
        if (root / name).exists():
            raise RuntimeError(f"ZIP contains the optional NDI runtime: {name}")
    if (root / "licenses/ndi-sdk").exists():
        raise RuntimeError("ZIP contains the SDK agreement directory")
    for name in ("WebView2Loader.dll", "Microsoft.Web.WebView2.Core.dll"):
        if (root / name).exists():
            raise RuntimeError(f"ZIP contains the WebView2 SDK runtime: {name}")
    if (root / "EBWebView").exists():
        raise RuntimeError("ZIP contains a fixed-version WebView2 runtime")

    inventory = collect_licenses.load_inventory(root)
    collect_licenses.validate_application(root, inventory)
    collect_licenses.validate_destination(root / "licenses", inventory)

    for file in root.rglob("*"):
        if not file.is_file():
            continue
        if file.suffix.lower() == ".pdf" and (
            re.search(r"ndi.*(license|agreement|eula)", file.name, re.IGNORECASE)
            or hashlib.sha256(file.read_bytes()).hexdigest() == lock["agreement_sha256"]
        ):
            raise RuntimeError("ZIP contains an NDI SDK contract PDF")
        if file.suffix.lower() in (".h", ".hpp", ".lib") or re.search(
            r"ndi.*(sdk|runtime).*\.exe$", file.name, re.IGNORECASE
        ):
            raise RuntimeError(
                f"ZIP contains development files or installers: {file.name}"
            )
        if file.name.casefold() in ("node.exe", "npm", "npm.cmd", "npx.cmd"):
            raise RuntimeError(f"ZIP contains Node.js tooling: {file.name}")
        if "node_modules" in (part.casefold() for part in file.parts):
            raise RuntimeError("ZIP contains Node.js dependencies")


def launch(root: Path) -> None:
    # os.environ is case-insensitive on Windows; a plain copied dict is not.
    environment = {name.upper(): value for name, value in os.environ.items()}
    for name in ("NDI_RUNTIME_DIR_V6", "NDI_RUNTIME_DIR_V5"):
        environment.pop(name, None)
    system = Path(environment["SYSTEMROOT"])
    environment["PATH"] = os.pathsep.join(map(str, (root, system / "System32", system)))
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    subprocess.run(
        [str(root / "DivergenceSplitter.exe"), "--smoke-test"],
        cwd=root,
        env=environment,
        check=True,
        timeout=30,
        **hidden,
    )

    scenario = root / "scenario-builder-smoke.yaml"
    scenario.write_text(SCENARIO, encoding="utf-8")
    try:
        subprocess.run(
            [str(root / "ScenarioBuilder.exe"), "--check", str(scenario)],
            cwd=root,
            env=environment,
            check=True,
            timeout=30,
            **hidden,
        )
        subprocess.run(
            [
                str(root / "ScenarioBuilder.exe"),
                "--open",
                str(scenario),
                "--smoke-test",
            ],
            cwd=root,
            env=environment,
            check=True,
            timeout=60,
            **hidden,
        )
    finally:
        scenario.unlink(missing_ok=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=Path("build/ci"))
    args = parser.parse_args()
    packages = list(args.build_dir.glob("*.zip"))
    if len(packages) != 1:
        raise RuntimeError("Expected exactly one Windows ZIP package")
    lock = json.loads(
        Path(__file__).with_name("ndi-sdk-lock.json").read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory(
        prefix="divergencesplitter-zip-", dir=os.environ.get("RUNNER_TEMP")
    ) as temporary:
        root = Path(temporary).resolve()
        with zipfile.ZipFile(packages[0]) as package:
            verify_archive_names(package.namelist())
            package.extractall(root)
        verify_contents(root, lock)
        launch(root)
    print(
        "Verified combined ZIP contents, licenses, SDK exclusions, "
        "and both GUI startup paths without NDI runtime"
    )


if __name__ == "__main__":
    main()
