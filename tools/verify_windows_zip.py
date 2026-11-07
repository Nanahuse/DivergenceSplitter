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

import collect_licenses


def verify_contents(root: Path, lock: dict[str, str]) -> None:
    required = [
        "DivergenceSplitter.exe",
        "opencv_core4.dll",
        "vc_redist.x64.exe",
        "LICENSE.txt",
        "DISTRIBUTION-NOTICE.txt",
        "licenses/components.json",
        "licenses/NDI-TERMS.txt",
    ]
    for name in required:
        if not (root / name).is_file() or not (root / name).stat().st_size:
            raise RuntimeError(f"ZIP missing required distribution file: {name}")
    if (root / "divergencesplitter-cli.exe").exists():
        raise RuntimeError("ZIP still contains the removed product CLI")
    for name in ("Qt6Core.dll", "platforms/qwindows.dll"):
        if (root / name).exists():
            raise RuntimeError(f"ZIP still contains Qt runtime: {name}")
    for name in ("Processing.NDI.Lib.x64.dll", "Processing.NDI.Lib.Licenses.txt"):
        if (root / name).exists():
            raise RuntimeError(f"ZIP contains the optional NDI runtime: {name}")
    if (root / "licenses/ndi-sdk").exists():
        raise RuntimeError("ZIP contains the SDK agreement directory")

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
            package.extractall(root)
        verify_contents(root, lock)
        launch(root)
    print("Verified ZIP licenses, SDK exclusions and GUI startup without NDI runtime")


if __name__ == "__main__":
    main()
