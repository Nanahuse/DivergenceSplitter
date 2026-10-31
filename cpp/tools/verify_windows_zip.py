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
from pathlib import Path


def verify_contents(root: Path, ndi: bool, lock: dict[str, str]) -> None:
    required = [
        "platforms/qwindows.dll",
        "Qt6Core.dll",
        "opencv_core4.dll",
        "vc_redist.x64.exe",
        "LICENSE.txt",
        "DISTRIBUTION-NOTICE.txt",
        "licenses/NDI-TERMS.txt",
    ]
    required += [
        f"licenses/{name}.txt"
        for name in (
            "qtbase",
            "opencv",
            "boost",
            "yaml-cpp",
            "nlohmann-json",
            "livesplit-bridge-client-cpp",
            "windows-capture-device-list",
        )
    ]
    for name in required:
        if not (root / name).is_file() or not (root / name).stat().st_size:
            raise RuntimeError(f"ZIP missing required distribution file: {name}")
    if ndi:
        for name, key in (
            ("Processing.NDI.Lib.x64.dll", "runtime_sha256"),
            ("Processing.NDI.Lib.Licenses.txt", "runtime_licenses_sha256"),
        ):
            file = root / name
            if (
                not file.is_file()
                or hashlib.sha256(file.read_bytes()).hexdigest() != lock[key]
            ):
                raise RuntimeError(
                    f"ZIP missing or modified NDI redistribution file: {name}"
                )
    elif (root / "Processing.NDI.Lib.x64.dll").exists():
        raise RuntimeError("SDK-disabled ZIP contains the NDI runtime")
    if (root / "licenses/ndi-sdk").exists():
        raise RuntimeError("ZIP contains the SDK agreement directory")
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


def launch(root: Path, ndi: bool) -> None:
    # os.environ is case-insensitive on Windows; a plain copied dict is not.
    environment = {name.upper(): value for name, value in os.environ.items()}
    for name in (
        "QT_PLUGIN_PATH",
        "QML2_IMPORT_PATH",
        "NDI_RUNTIME_DIR_V6",
        "NDI_RUNTIME_DIR_V5",
    ):
        environment.pop(name, None)
    system = Path(environment["SYSTEMROOT"])
    environment["PATH"] = os.pathsep.join(map(str, (root, system / "System32", system)))
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    for executable, arguments in (
        ("divergencesplitter-cli.exe", ["--help"]),
        ("DivergenceSplitter.exe", ["--smoke-test"]),
    ):
        subprocess.run(
            [str(root / executable), *arguments],
            cwd=root,
            env=environment,
            check=True,
            timeout=30,
            **hidden,
        )
    if ndi:
        subprocess.run(
            [str(root / "divergencesplitter-cli.exe"), "--ndi-check"],
            cwd=root,
            env=environment,
            check=True,
            timeout=30,
            **hidden,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-dir", type=Path, default=Path("build/ci"))
    parser.add_argument("--ndi", choices=("ON", "OFF"), required=True)
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
            package.extractall(root)
        verify_contents(root, args.ndi == "ON", lock)
        launch(root, args.ndi == "ON")
    print("Verified ZIP notices, SDK exclusions, CLI/GUI startup and local NDI runtime")


if __name__ == "__main__":
    main()
