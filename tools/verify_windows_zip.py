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
from pathlib import Path

import collect_licenses


SCENARIO = """schema_version: 2
start_condition: {type: elapsed, duration: 1s}
splits: []
"""

NODE_TOOLS = {
    "node.exe", "node",
    "npm", "npm.cmd", "npm.ps1",
    "npx", "npx.cmd", "npx.ps1",
    "corepack", "corepack.cmd", "corepack.ps1",
}


def verify_archive_names(names: list[str]) -> None:
    normalized = [name.casefold() for name in names if name and not name.endswith("/")]
    duplicates = sorted(
        name for name, count in Counter(normalized).items() if count > 1
    )
    if duplicates:
        raise RuntimeError(
            "ZIP contains duplicate entries: " + ", ".join(duplicates)
        )


def sha256(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_contents(root: Path, lock: dict[str, str], *, builder_only: bool = False) -> None:
    inventory = collect_licenses.load_inventory(root)
    distribution = "scenario-builder" if builder_only else "combined"
    expected = collect_licenses.distribution_inventory(distribution)
    if inventory["application"] != expected["application"] or {
        component["name"]: component for component in inventory["components"]
    } != {component["name"]: component for component in expected["components"]}:
        raise RuntimeError(f"ZIP has an incorrect license inventory for {distribution}")
    collect_licenses.validate_application(root, expected)
    collect_licenses.validate_destination(root / "licenses", inventory)
    notice = root / "DISTRIBUTION-NOTICE.txt"
    if not collect_licenses.has_notice(notice):
        raise RuntimeError("ZIP missing or empty DISTRIBUTION-NOTICE.txt")

    restricted_ndi_files = {
        lock[key]
        for key in (
            "installer_sha256",
            "runtime_sha256",
            "runtime_licenses_sha256",
            "agreement_sha256",
        )
    }
    for file in root.rglob("*"):
        path = file.relative_to(root)
        name = file.name.casefold()
        if name in NODE_TOOLS or name == "node_modules":
            raise RuntimeError(f"ZIP contains Node.js development files: {path}")
        if not file.is_file():
            continue
        if file.suffix.casefold() in {".h", ".hpp", ".lib"}:
            raise RuntimeError(f"ZIP contains a development header or library: {path}")
        if name == "msedgewebview2.exe":
            raise RuntimeError(f"ZIP contains a bundled WebView2 Runtime: {path}")
        if (
            (name.startswith("processing.ndi.lib.") and name.endswith(".dll"))
            or name == "processing.ndi.lib.licenses.txt"
            or re.search(r"ndi.*(license|agreement|eula).*\.pdf$", name)
            or re.search(r"ndi.*(sdk|runtime).*\.exe$", name)
            or sha256(file) in restricted_ndi_files
        ):
            raise RuntimeError(f"ZIP contains a separately distributed NDI file: {path}")


def launch(root: Path, *, builder_only: bool = False) -> None:
    # os.environ is case-insensitive on Windows; a plain copied dict is not.
    environment = {name.upper(): value for name, value in os.environ.items()}
    for name in ("NDI_RUNTIME_DIR_V6", "NDI_RUNTIME_DIR_V5"):
        environment.pop(name, None)
    system = Path(environment["SYSTEMROOT"])
    environment["PATH"] = os.pathsep.join(map(str, (root, system / "System32", system)))
    hidden = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    if not builder_only:
        subprocess.run(
            [str(root / "DivergenceSplitter.exe"), "--smoke-test"],
            cwd=root,
            env=environment,
            check=True,
            timeout=30,
            **hidden,
        )
    with tempfile.TemporaryDirectory(prefix="scenario-builder-smoke-") as temporary:
        scenario = Path(temporary).resolve() / "scenario.yaml"
        scenario.write_text(SCENARIO, encoding="utf-8")
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--build-dir", type=Path, default=Path("build/ci"))
    source.add_argument("--archive", type=Path)
    parser.add_argument("--scenario-builder-only", action="store_true")
    args = parser.parse_args()
    archive = args.archive
    if archive is None:
        packages = list(args.build_dir.glob("*.zip"))
        if len(packages) != 1:
            raise RuntimeError("Expected exactly one Windows ZIP package")
        archive = packages[0]
    lock = json.loads(
        Path(__file__).with_name("ndi-sdk-lock.json").read_text(encoding="utf-8")
    )
    with tempfile.TemporaryDirectory(
        prefix="divergencesplitter-zip-", dir=os.environ.get("RUNNER_TEMP")
    ) as temporary:
        root = Path(temporary).resolve()
        with zipfile.ZipFile(archive) as package:
            verify_archive_names(package.namelist())
            package.extractall(root)
        verify_contents(root, lock, builder_only=args.scenario_builder_only)
        launch(root, builder_only=args.scenario_builder_only)
    print(f"Verified redistribution contents and application startup from {archive.name}")


if __name__ == "__main__":
    main()
