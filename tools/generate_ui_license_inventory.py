"""Generate and verify the license inventory bundled into the UI package.

The inventory is computed from the Windows release dependency closure of the
``divergencesplitter-ui`` distribution. The closure walks ``Requires-Dist``
edges of the root distribution, evaluates environment markers for a Windows
target, and resolves each requirement to a distribution installed in the
current environment. It never queries a network and never lists every
installed package.

The Windows build also explicitly includes ``ndi-python`` as a release root.
The NDI runtime notices stored outside its distribution metadata are emitted as
separate ``assets`` rather than folded into the ``ndi-python`` MIT entry, so the
MIT binding and the separately licensed NDI Runtime stay distinguishable.

For each inventoried component the generator also bundles the full license
text files shipped by the installed distribution, so the license screen can
reproduce the actual license texts (not just SPDX identifiers) that are
redistributed inside the executable. Some releases declare an SPDX expression
in metadata but omit every license file from the wheel (``flet`` is one such
distribution); for those a canonical text vendored under ``tools/licenses`` is
used so the inventory still reproduces the license rather than failing. The
application's own MIT text from the repository ``LICENSE`` is included as the
``application`` section. Components under MPL-2.0 also carry a short note
pointing at where their upstream source can be obtained.

Generation is deterministic: packages are emitted sorted by their normalized
name, license files are sorted by their normalized sub-path, and every run
over the same environment produces identical JSON. The ``--check`` mode
rebuilds the expected inventory and fails on any name/version/license/text
difference, including both missing and extra packages. The license screen
covers third-party components only, so the own DivergenceSplitter
distributions are excluded from the emitted inventory via an explicit,
documented set.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Mapping
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import NamedTuple, TypedDict

from packaging.licenses import (
    InvalidLicenseExpression,
    canonicalize_license_expression,
)
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = Path(__file__).resolve().parent
UI_MODULE_ROOT = (
    REPO_ROOT / "packages" / "divergencesplitter-ui" / "src" / "divergencesplitter_ui"
)
INVENTORY_PATH = UI_MODULE_ROOT / "license_inventory.json"
ROOT_DISTRIBUTION = "divergencesplitter-ui"
SCHEMA_VERSION = 3
APPLICATION_NAME = "DivergenceSplitter"
APPLICATION_LICENSE = "MIT"
APPLICATION_LICENSE_PATH = REPO_ROOT / "LICENSE"
LICENSE_NAME_STARTS = ("license", "licence", "copying", "notice")

# The NDI runtime is conveyed alongside the MIT-licensed ``ndi-python`` binding
# but is licensed separately by Vizrt NDI AB. It is emitted as assets instead
# of being folded into the ``ndi-python`` package so the two are never confused.
NDI_PACKAGE = "ndi-python"
NDI_RUNTIME_ASSET_NAME = "NDI Runtime"
NDI_RUNTIME_NOTICES_ASSET_NAME = "NDI Runtime Third-Party Notices"
NDI_SDK_LICENSE = "NDI SDK License Agreement"
NDI_RUNTIME_NOTICES_PATH = "NDIlib/Processing.NDI.Lib.Licenses.txt"
NDI_LICENSE_DOCUMENT_PATH = REPO_ROOT / "THIRD_PARTY_LICENSES" / "NDI.md"

# MPL-2.0 requires that the Corresponding Source be made available. Rather than
# building a dependency metadata system, MPL components get a short pointer to
# their upstream source appended to their bundled license text.
MPL_LICENSE_ID = "MPL-2.0"
MPL_SOURCE_NOTE = (
    "=== MPL-2.0 Source Availability ===\n"
    "{name} {version} is distributed under the Mozilla Public License 2.0.\n"
    "The Corresponding Source for this component is available from its\n"
    "upstream project and from the Python Package Index:\n"
    "https://pypi.org/project/{name}/{version}/#files"
)

# Canonical license texts vendored for distributions that declare an SPDX
# expression but ship no license file in their wheel, keyed by that expression.
# They are read like any bundled text so the emitted inventory stays
# deterministic across platforms.
SPDX_LICENSE_TEXTS: dict[str, Path] = {
    "Apache-2.0": TOOLS_ROOT / "licenses" / "Apache-2.0.txt",
}

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
    license_text: str


class ApplicationEntry(TypedDict):
    name: str
    license: str
    license_text: str


class AssetEntry(TypedDict):
    name: str
    license: str
    license_text: str


class InventoryDocument(TypedDict):
    schema_version: int
    application: ApplicationEntry
    packages: list[PackageEntry]
    assets: list[AssetEntry]


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
    "opencv-contrib-python": Override(
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
    *,
    additional_roots: tuple[str, ...] = (),
) -> dict[str, metadata.Distribution]:
    """Return the Windows release closure keyed by normalized package name.

    ``installed`` maps normalized package names to the available distribution
    metadata so the closure can be built from fixtures in tests.
    ``additional_roots`` includes optional backends collected by PyInstaller.
    """

    environment = _windows_environment()
    closure: dict[str, metadata.Distribution] = {}
    pending = [ROOT_DISTRIBUTION, *additional_roots]
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


def _dist_info_subpath(file_path: object) -> str | None:
    """Return a distribution file path relative to its ``.dist-info`` dir."""

    parts = PurePosixPath(str(file_path).replace("\\", "/")).parts
    for index, segment in enumerate(parts):
        if segment.endswith(".dist-info"):
            return "/".join(parts[index + 1 :])
    return None


def _declared_license_files(
    dist: metadata.Distribution,
) -> list[tuple[str, str]]:
    """Read the license files named by ``License-File`` metadata.

    PEP 639 paths may be relative to the ``.dist-info/licenses`` directory or
    to the ``.dist-info`` directory itself, so both are tried. A declared file
    that cannot be read is a metadata inconsistency and fails loudly.
    """

    resolved: list[tuple[str, str]] = []
    for declared_path in dist.metadata.get_all("License-File") or ():
        read_path: str | None = None
        content: str | None = None
        for candidate in (f"licenses/{declared_path}", declared_path):
            text = dist.read_text(candidate)
            if text is not None:
                read_path, content = candidate, text
                break
        if read_path is None or content is None:
            raise RuntimeError(
                f"declared license file {declared_path!r} for "
                f"{dist.metadata['Name']!r} cannot be read"
            )
        resolved.append((read_path, content))
    return resolved


def _scanned_license_files(
    dist: metadata.Distribution,
) -> list[tuple[str, str]]:
    """Discover license files under the distribution's ``.dist-info`` dir.

    This catches components whose metadata omits ``License-File`` while the
    installed wheel still ships license texts, including nested sub-licenses.
    """

    scanned: dict[str, str] = {}
    for file_path in dist.files or ():
        subpath = _dist_info_subpath(file_path)
        if subpath is None:
            continue
        if not PurePosixPath(subpath).name.lower().startswith(LICENSE_NAME_STARTS):
            continue
        text = dist.read_text(subpath)
        if text is not None:
            scanned[subpath] = text
    return sorted(scanned.items())


def _vendored_license_text(dist: metadata.Distribution) -> str | None:
    """Return a vendored canonical text for a wheel that ships no license file.

    The text is selected by the distribution's resolved SPDX expression when
    that expression has a canonical file under ``tools/licenses``. Returns
    ``None`` when no vendored text applies, so the caller can fail loudly.
    """

    path = SPDX_LICENSE_TEXTS.get(resolve_license(dist))
    if path is None:
        return None
    relative = path.relative_to(REPO_ROOT).as_posix()
    return f"=== {relative} ===\n{path.read_text(encoding='utf-8')}"


def _contains_mpl(expression: str) -> bool:
    """Return whether an SPDX expression includes MPL-2.0."""

    tokens = expression.replace("(", " ").replace(")", " ").split()
    return MPL_LICENSE_ID in tokens


def _source_availability_note(dist: metadata.Distribution) -> str | None:
    """Return an MPL-2.0 source-availability note when the component needs one.

    The note is best-effort: a component whose license cannot be resolved is
    not treated as MPL, because its own license-text collection already fails
    loudly when it is genuinely broken.
    """

    try:
        expression = resolve_license(dist)
    except RuntimeError:
        return None
    if not _contains_mpl(expression):
        return None
    return MPL_SOURCE_NOTE.format(
        name=dist.metadata["Name"],
        version=dist.metadata["Version"],
    )


def license_text(dist: metadata.Distribution) -> str:
    """Collect every license text shipped by the installed distribution.

    The NDI runtime notices are deliberately not collected here: they license
    the separately distributed NDI Runtime, not the MIT-licensed ``ndi-python``
    binding, and are emitted as their own assets by ``ndi_runtime_assets``.
    """

    entries: dict[str, str] = {}
    for read_path, content in _declared_license_files(dist):
        entries[read_path] = content
    for read_path, content in _scanned_license_files(dist):
        entries[read_path] = content
    if not entries:
        vendored = _vendored_license_text(dist)
        if vendored is None:
            raise RuntimeError(
                f"cannot collect any license text for {dist.metadata['Name']!r}"
            )
        text = vendored
    else:
        blocks = [
            f"=== {read_path} ===\n{entries[read_path]}"
            for read_path in sorted(entries)
        ]
        text = "\n\n".join(blocks)
    source_note = _source_availability_note(dist)
    if source_note is not None:
        return f"{text}\n\n{source_note}"
    return text


def ndi_runtime_assets(
    closure: dict[str, metadata.Distribution],
) -> list[AssetEntry]:
    """Return the NDI Runtime assets when the NDI binding is in the closure.

    ``ndi-python`` is MIT, but it ships the NDI Runtime, which is licensed by
    Vizrt NDI AB under the NDI SDK License Agreement. These assets keep the
    runtime and its third-party notices distinct from the MIT binding on the
    license screen.
    """

    dist = closure.get(canonicalize_name(NDI_PACKAGE))
    if dist is None:
        return []
    notices = dist.locate_file(NDI_RUNTIME_NOTICES_PATH).read_text(encoding="utf-8")
    return [
        {
            "name": NDI_RUNTIME_ASSET_NAME,
            "license": NDI_SDK_LICENSE,
            "license_text": NDI_LICENSE_DOCUMENT_PATH.read_text(encoding="utf-8"),
        },
        {
            "name": NDI_RUNTIME_NOTICES_ASSET_NAME,
            "license": NDI_SDK_LICENSE,
            "license_text": notices,
        },
    ]


def application_entry() -> ApplicationEntry:
    """Return the application's own license section from the repo ``LICENSE``.

    The MIT text is bundled alongside the third-party inventory so the license
    screen carries the application's own terms as well.
    """

    return {
        "name": APPLICATION_NAME,
        "license": APPLICATION_LICENSE,
        "license_text": APPLICATION_LICENSE_PATH.read_text(encoding="utf-8"),
    }


def build_inventory(
    closure: dict[str, metadata.Distribution],
) -> InventoryDocument:
    """Emit one inventory entry per non-excluded package.

    The own DivergenceSplitter distributions are excluded because their
    licenses are not part of the third-party license screen. Components that
    are not Python distributions (the NDI Runtime) are emitted as assets.
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
                "license_text": license_text(dist),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "application": application_entry(),
        "packages": packages,
        "assets": ndi_runtime_assets(closure),
    }


def write_inventory(inventory: InventoryDocument) -> None:
    INVENTORY_PATH.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def check_inventory(inventory: InventoryDocument) -> bool:
    if not INVENTORY_PATH.exists():
        print(f"missing bundled inventory: {INVENTORY_PATH}")
        return False
    stored = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    if stored == inventory:
        return True
    mismatched = False
    if stored.get("schema_version") != inventory["schema_version"]:
        print(
            f"schema_version: expected {inventory['schema_version']!r}, "
            f"stored {stored.get('schema_version')!r}"
        )
        mismatched = True
    if stored.get("application") != inventory["application"]:
        print("application license section differs from the release closure")
        mismatched = True

    expected = {entry["name"]: entry for entry in inventory["packages"]}
    actual = {entry["name"]: entry for entry in stored.get("packages", [])}
    for name in sorted(expected.keys() - actual.keys()):
        print(f"missing from inventory: {name}")
        mismatched = True
    for name in sorted(actual.keys() - expected.keys()):
        print(f"extra in inventory: {name}")
        mismatched = True
    for name in sorted(expected.keys() & actual.keys()):
        for field in ("version", "license", "license_text"):
            expected_value = expected[name][field]
            actual_value = actual[name][field]
            if expected_value != actual_value:
                print(
                    f"{name} {field}: expected {expected_value!r}, "
                    f"stored {actual_value!r}"
                )
                mismatched = True

    expected_assets = {entry["name"]: entry for entry in inventory["assets"]}
    actual_assets = {entry["name"]: entry for entry in stored.get("assets", [])}
    for name in sorted(expected_assets.keys() - actual_assets.keys()):
        print(f"missing from inventory assets: {name}")
        mismatched = True
    for name in sorted(actual_assets.keys() - expected_assets.keys()):
        print(f"extra in inventory assets: {name}")
        mismatched = True
    for name in sorted(expected_assets.keys() & actual_assets.keys()):
        for field in ("license", "license_text"):
            expected_value = expected_assets[name][field]
            actual_value = actual_assets[name][field]
            if expected_value != actual_value:
                print(
                    f"asset {name} {field}: expected {expected_value!r}, "
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

    # The Windows executable also bundles the optional NDI input backend.
    closure = release_closure(
        installed_distributions(), additional_roots=("ndi-python",)
    )
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
