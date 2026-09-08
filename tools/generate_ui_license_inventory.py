"""Generate and verify the license inventory bundled into the UI package.

The inventory is computed from the Windows release dependency closure of the
``divergencesplitter-ui`` distribution. The closure walks ``Requires-Dist``
edges of the root distribution, evaluates environment markers for a Windows
target, and resolves each requirement to a distribution installed in the
current environment. It never queries a network and never lists every
installed package.

Generation is deterministic: packages are emitted sorted by their normalized
name, and every run over the same environment produces identical JSON. The
``--check`` mode rebuilds the expected inventory and fails on any
name/version/license difference, including both missing and extra packages.
The license screen covers third-party components only, so the own
DivergenceSplitter distributions are excluded from the emitted inventory via
an explicit, documented set.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path
from typing import NamedTuple, TypedDict

from packaging.licenses import (
    InvalidLicenseExpression,
    canonicalize_license_expression,
)
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = (
    REPO_ROOT
    / "packages"
    / "divergencesplitter-ui"
    / "src"
    / "divergencesplitter_ui"
    / "license_inventory.json"
)
ROOT_DISTRIBUTION = "divergencesplitter-ui"
SCHEMA_VERSION = 1

EXCLUDED_DISTRIBUTIONS: dict[str, str] = {
    "divergencesplitter": "own package, not a third-party license",
    "divergencesplitter-runtime": "own package, not a third-party license",
    "divergencesplitter-ui": "own package, not a third-party license",
}


class Override(NamedTuple):
    license: str
    reason: str


class PackageEntry(TypedDict):
    name: str
    version: str
    license: str


class InventoryDocument(TypedDict):
    schema_version: int
    packages: list[PackageEntry]


OVERRIDES: dict[str, Override] = {
    "windows-capture-device-list": Override(
        "MIT",
        "release metadata carries no license fields and the repository LICENSE is MIT",
    ),
    "livesplit-bridge-client": Override(
        "MIT",
        "release metadata License is the full MIT text, not an SPDX expression",
    ),
    "protobuf": Override(
        "BSD-3-Clause",
        "release metadata License is '3-Clause BSD License', not an SPDX expression",
    ),
    "opencv-python": Override(
        "Apache-2.0",
        "release metadata License is 'Apache 2.0', not an SPDX expression",
    ),
}


def _windows_environment() -> dict[str, str]:
    return {
        "implementation_name": sys.implementation.name,
        "implementation_version": platform.python_version(),
        "os_name": "nt",
        "platform_machine": platform.machine(),
        "platform_python_implementation": platform.python_implementation(),
        "platform_release": platform.release(),
        "platform_system": "Windows",
        "platform_version": sys.version,
        "python_full_version": platform.python_version(),
        "python_version": ".".join(platform.python_version().split(".")[:2]),
        "sys_platform": "win32",
        "extra": "",
    }


def release_closure(
    installed: Mapping[str, metadata.Distribution],
) -> dict[str, metadata.Distribution]:
    """Return the Windows release closure keyed by normalized package name.

    ``installed`` maps normalized package names to the available distribution
    metadata so the closure can be built from fixtures in tests.
    """

    environment = _windows_environment()
    closure: dict[str, metadata.Distribution] = {}
    pending = [ROOT_DISTRIBUTION]
    while pending:
        requested = pending.pop()
        key = canonicalize_name(requested)
        if key in closure:
            continue
        dist = installed.get(key)
        if dist is None:
            raise RuntimeError(
                f"{requested!r} is in the release closure but is not installed"
            )
        closure[key] = dist
        for requirement_string in dist.requires or ():
            requirement = Requirement(requirement_string)
            if requirement.marker is not None and not requirement.marker.evaluate(
                environment
            ):
                continue
            child = canonicalize_name(requirement.name)
            if child not in closure:
                pending.append(requirement.name)
    return closure


def installed_distributions() -> dict[str, metadata.Distribution]:
    """Index the current environment by normalized package name."""

    return {
        canonicalize_name(dist.metadata["Name"]): dist
        for dist in metadata.distributions()
    }


def _license_from_metadata(dist: metadata.Distribution) -> str | None:
    expression = dist.metadata.get("License-Expression")
    if expression and expression != "UNKNOWN":
        return expression
    license_value = (dist.metadata.get("License") or "").strip()
    if license_value and license_value != "UNKNOWN":
        return license_value
    classifiers = dist.metadata.get_all("Classifier") or ()
    for classifier in classifiers:
        if classifier.startswith("License :: OSI Approved :: "):
            return classifier.removeprefix("License :: OSI Approved :: ")
        if classifier.startswith("License :: "):
            return classifier.removeprefix("License :: ")
    return None


def resolve_license(dist: metadata.Distribution) -> str:
    """Resolve one distribution to a single SPDX license expression."""

    key = canonicalize_name(dist.metadata["Name"])
    override = OVERRIDES.get(key)
    if override is not None:
        return override.license
    value = _license_from_metadata(dist)
    if value is None:
        raise RuntimeError(
            f"cannot resolve a license for {dist.metadata['Name']!r}; "
            "add an explicit override with a documented reason"
        )
    try:
        return canonicalize_license_expression(value)
    except InvalidLicenseExpression:
        raise RuntimeError(
            f"license {value!r} for {dist.metadata['Name']!r} is not an SPDX "
            "expression; add an explicit override with a documented reason"
        ) from None


def build_inventory(
    closure: dict[str, metadata.Distribution],
) -> InventoryDocument:
    """Emit one inventory entry per non-excluded package.

    The own DivergenceSplitter distributions are excluded because their
    licenses are not part of the third-party license screen.
    """

    packages: list[PackageEntry] = []
    for key in sorted(closure):
        if key in EXCLUDED_DISTRIBUTIONS:
            continue
        dist = closure[key]
        packages.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.metadata["Version"],
                "license": resolve_license(dist),
            }
        )
    return {"schema_version": SCHEMA_VERSION, "packages": packages}


def write_inventory(inventory: InventoryDocument) -> None:
    INVENTORY_PATH.write_text(
        json.dumps(inventory, indent=2) + "\n",
        encoding="utf-8",
    )


def check_inventory(inventory: InventoryDocument) -> bool:
    if not INVENTORY_PATH.exists():
        print(f"missing bundled inventory: {INVENTORY_PATH}")
        return False
    stored = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    if stored == inventory:
        return True
    expected = {entry["name"]: entry for entry in inventory["packages"]}
    actual = {entry["name"]: entry for entry in stored["packages"]}
    mismatched = False
    for name in sorted(expected.keys() - actual.keys()):
        print(f"missing from inventory: {name}")
        mismatched = True
    for name in sorted(actual.keys() - expected.keys()):
        print(f"extra in inventory: {name}")
        mismatched = True
    for name in sorted(expected.keys() & actual.keys()):
        for field in ("version", "license"):
            expected_value = expected[name][field]
            actual_value = actual[name][field]
            if expected_value != actual_value:
                print(
                    f"{name} {field}: expected {expected_value!r}, "
                    f"stored {actual_value!r}"
                )
                mismatched = True
    return not mismatched


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the stored inventory with the release closure",
    )
    args = parser.parse_args()

    closure = release_closure(installed_distributions())
    inventory = build_inventory(closure)
    if args.check:
        if not check_inventory(inventory):
            raise SystemExit(1)
        print(
            f"license inventory is up to date ({len(inventory['packages'])} packages)"
        )
        return
    write_inventory(inventory)
    print(
        f"wrote {len(inventory['packages'])} packages to {INVENTORY_PATH.relative_to(REPO_ROOT)}"
    )


if __name__ == "__main__":
    main()
