"""Generate license files and an inventory from the Windows distribution.

The generator scans the actual ``site-packages`` and staged Python runtime
inside the Flet build output, resolves license metadata and text, and writes
the inventory and referenced files into the final distribution directory.
The root application license is copied from ``LICENSE``. Only components with
no license text in their distributed artifact may use a component-specific
fallback under ``tools/licenses``. Flutter and Dart notices remain in
``flutter_assets/NOTICES.Z``.
"""

from __future__ import annotations

import argparse
import json
import shutil
from importlib import metadata
from pathlib import Path, PurePosixPath
from typing import NamedTuple, NotRequired, TypedDict

from packaging.licenses import (
    InvalidLicenseExpression,
    canonicalize_license_expression,
)
from packaging.utils import canonicalize_name

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = Path(__file__).resolve().parent
LICENSES_ROOT = TOOLS_ROOT / "licenses"
SCHEMA_VERSION = 4
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
NDI_RUNTIME_LICENSE = "Licensing Notice"
NDI_RUNTIME_NOTICES_LICENSE = "Third-party notices"
NDI_RUNTIME_NOTICES_PATH = "NDIlib/Processing.NDI.Lib.Licenses.txt"
NDI_LICENSE_FALLBACK = LICENSES_ROOT / "NDI-SDK-License-Agreement.txt"

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


class LicenseTextFallback(NamedTuple):
    path: Path
    reason: str


LICENSE_TEXT_FALLBACKS: dict[str, LicenseTextFallback] = {
    "flet": LicenseTextFallback(
        LICENSES_ROOT / "Apache-2.0.txt",
        "the installed wheel declares Apache-2.0 but ships no license text",
    ),
    "dart-bridge": LicenseTextFallback(
        LICENSES_ROOT / "dart_bridge-MIT.txt",
        "the native runtime artifact does not contain a license text",
    ),
    "ndi-runtime": LicenseTextFallback(
        NDI_LICENSE_FALLBACK,
        "ndi-python ships third-party notices but not the NDI SDK agreement",
    ),
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
    license_file: str


class ApplicationEntry(TypedDict):
    name: str
    license: str
    license_file: str


class AssetEntry(TypedDict):
    name: str
    version: NotRequired[str]
    license: str
    license_file: str


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


def distribution_packages(
    site_packages: Path,
) -> dict[str, metadata.Distribution]:
    """Read Python distributions from the final Windows app's site-packages."""
    if not site_packages.is_dir():
        raise RuntimeError(
            f"distribution site-packages directory is missing: {site_packages}"
        )
    dist_info_dirs = sorted(site_packages.glob("*.dist-info"))
    if not dist_info_dirs:
        raise RuntimeError(
            f"final distribution has no .dist-info metadata under {site_packages}"
        )
    distributions: dict[str, metadata.Distribution] = {}
    for dist in metadata.distributions(path=[str(site_packages)]):
        name = dist.metadata.get("Name")
        if not name:
            raise RuntimeError(f"distribution metadata has no Name field: {dist}")
        key = canonicalize_name(name)
        if key in distributions:
            raise RuntimeError(f"duplicate distribution metadata for {name!r}")
        distributions[key] = dist
    if not distributions:
        raise RuntimeError(f"could not read any distributions from {site_packages}")
    return distributions


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
    """Discover license and notice files retained in the distribution.

    This catches components whose metadata omits ``License-File`` while the
    installed wheel still ships license texts, including nested sub-licenses
    and top-level LICENSE/NOTICE files.
    """

    scanned: dict[str, str] = {}
    for file_path in dist.files or ():
        subpath = _dist_info_subpath(file_path)
        candidate = PurePosixPath(str(file_path).replace("\\", "/"))
        if not candidate.name.lower().startswith(LICENSE_NAME_STARTS):
            continue
        if subpath is not None:
            text = dist.read_text(subpath)
            key = subpath
        else:
            path = Path(str(dist.locate_file(file_path)))
            text = path.read_text(encoding="utf-8") if path.is_file() else None
            key = candidate.as_posix()
        if text is not None:
            scanned[key] = text
    return sorted(scanned.items())


def _fallback_license_text(component: str) -> str | None:
    """Return a component-specific fallback text, if one is explicitly set."""

    fallback = LICENSE_TEXT_FALLBACKS.get(canonicalize_name(component))
    if fallback is None:
        return None
    if not fallback.path.is_file():
        raise RuntimeError(
            f"license text fallback for {component!r} is missing: {fallback.path}"
        )
    return fallback.path.read_text(encoding="utf-8")


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
        fallback_text = _fallback_license_text(dist.metadata["Name"])
        if fallback_text is None:
            raise RuntimeError(
                f"cannot collect any license text for {dist.metadata['Name']!r}"
            )
        text = fallback_text
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


def _write_text(distribution_root: Path, relative_path: str, text: str) -> None:
    target = resolve_license_file(relative_path, distribution_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8", newline="\n")


def resolve_license_file(relative_path: str, distribution_root: Path) -> Path:
    """Resolve a distribution-relative file reference without allowing escape."""
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise RuntimeError(f"invalid license_file reference: {relative_path!r}")
    root = distribution_root.resolve()
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise RuntimeError(f"invalid license_file reference: {relative_path!r}")
    return target


def application_entry(distribution_root: Path) -> ApplicationEntry:
    """Copy the project LICENSE and return its distribution inventory entry."""
    relative_path = "licenses/application/DivergenceSplitter.txt"
    target = resolve_license_file(relative_path, distribution_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(APPLICATION_LICENSE_PATH, target)
    return {
        "name": APPLICATION_NAME,
        "license": APPLICATION_LICENSE,
        "license_file": relative_path,
    }


def _ndi_sdk_license_text(dist: metadata.Distribution) -> str:
    """Use an agreement shipped by ndi-python, or its explicit official fallback."""
    for file_path in dist.files or ():
        candidate = PurePosixPath(str(file_path))
        stem = candidate.stem.casefold().replace("_", " ").replace("-", " ")
        if "license" not in stem or "agreement" not in stem:
            continue
        if candidate.suffix.casefold() not in {".txt", ".md", ".rst"}:
            continue
        path = Path(str(dist.locate_file(file_path)))
        if path.is_file():
            return path.read_text(encoding="utf-8")
    fallback = _fallback_license_text("ndi-runtime")
    if fallback is None:
        raise RuntimeError("NDI Runtime requires its official SDK License Agreement")
    return fallback


def ndi_runtime_assets(
    distributions: dict[str, metadata.Distribution], distribution_root: Path
) -> list[AssetEntry]:
    """Write the NDI agreement and installed binding notices as separate assets."""
    dist = distributions.get(canonicalize_name(NDI_PACKAGE))
    if dist is None:
        return []
    runtime_license = "licenses/runtime/NDI-SDK-License-Agreement.txt"
    third_party_notices = "licenses/runtime/NDI-Runtime-Third-Party-Notices.txt"
    _write_text(distribution_root, runtime_license, _ndi_sdk_license_text(dist))
    notice_path = Path(str(dist.locate_file(NDI_RUNTIME_NOTICES_PATH)))
    if not notice_path.is_file():
        raise RuntimeError(f"ndi-python NDI notice is missing: {notice_path}")
    _write_text(
        distribution_root,
        third_party_notices,
        notice_path.read_text(encoding="utf-8"),
    )
    return [
        {
            "name": NDI_RUNTIME_ASSET_NAME,
            "license": NDI_RUNTIME_LICENSE,
            "license_file": runtime_license,
        },
        {
            "name": NDI_RUNTIME_NOTICES_ASSET_NAME,
            "license": NDI_RUNTIME_NOTICES_LICENSE,
            "license_file": third_party_notices,
        },
    ]


def runtime_component_assets(
    staged_python_runtime: Path, distribution_root: Path
) -> list[AssetEntry]:
    """Collect the staged Python runtime's complete license bundle as one asset."""
    license_source = staged_python_runtime / "LICENSE.txt"
    if not license_source.is_file():
        raise RuntimeError(
            f"staged Flet Python runtime has no LICENSE.txt: {license_source}"
        )
    runtime_files = [license_source]
    license_dir = staged_python_runtime / "licenses"
    if license_dir.is_dir():
        runtime_files.extend(
            sorted(path for path in license_dir.rglob("*") if path.is_file())
        )
    runtime_bundle = "\n\n".join(
        f"=== {path.relative_to(staged_python_runtime).as_posix()} ===\n"
        f"{path.read_text(encoding='utf-8')}"
        for path in runtime_files
    )
    runtime_reference = "licenses/runtime/Flet-Python-runtime.txt"
    _write_text(distribution_root, runtime_reference, runtime_bundle)
    assets: list[AssetEntry] = [
        {
            "name": "Flet embedded Python runtime",
            "license": "Runtime license bundle",
            "license_file": runtime_reference,
        }
    ]

    dart_fallback = _fallback_license_text("dart_bridge")
    if dart_fallback is None:
        raise RuntimeError("dart_bridge requires an explicit license text fallback")
    dart_reference = "licenses/dart_bridge.txt"
    _write_text(distribution_root, dart_reference, dart_fallback)
    assets.append(
        {"name": "dart_bridge", "license": "MIT", "license_file": dart_reference}
    )

    return assets


def build_inventory(
    distributions: dict[str, metadata.Distribution],
    *,
    staged_python_runtime: Path,
    distribution_root: Path,
) -> InventoryDocument:
    """Resolve all release licenses and write their files into the distribution."""
    packages: list[PackageEntry] = []
    for key in sorted(distributions):
        if key in EXCLUDED_DISTRIBUTIONS:
            continue
        dist = distributions[key]
        reference = f"licenses/packages/{canonicalize_name(dist.metadata['Name'])}.txt"
        _write_text(distribution_root, reference, license_text(dist))
        packages.append(
            {
                "name": dist.metadata["Name"],
                "version": dist.metadata["Version"],
                "license": resolve_license(dist),
                "license_file": reference,
            }
        )
    assets = runtime_component_assets(staged_python_runtime, distribution_root)
    assets.extend(ndi_runtime_assets(distributions, distribution_root))
    inventory: InventoryDocument = {
        "schema_version": SCHEMA_VERSION,
        "application": application_entry(distribution_root),
        "packages": packages,
        "assets": assets,
    }
    inventory_path = distribution_root / "license_inventory.json"
    inventory_path.write_text(
        json.dumps(inventory, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    validate_inventory_files(inventory, distribution_root)
    return inventory


def validate_inventory_files(
    inventory: InventoryDocument, distribution_root: Path
) -> None:
    """Require every inventory reference to resolve to a nonempty file."""
    entries = [inventory["application"], *inventory["packages"], *inventory["assets"]]
    for entry in entries:
        path = resolve_license_file(entry["license_file"], distribution_root)
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(
                f"license file was not generated: {entry['license_file']}"
            )


def render_third_party_notices(
    inventory: InventoryDocument, *, distribution_root: Path
) -> str:
    """Render notices from the exact license files generated for the distribution."""
    groups: dict[str, list[str]] = {}
    for entry in [
        inventory["application"],
        *inventory["packages"],
        *inventory["assets"],
    ]:
        path = resolve_license_file(entry["license_file"], distribution_root)
        if not path.is_file():
            raise RuntimeError(
                f"license file referenced by inventory is missing: {path}"
            )
        text = path.read_text(encoding="utf-8")
        version = entry.get("version")
        label = f"{entry['name']} {version}" if version else entry["name"]
        groups.setdefault(text, []).append(f"{label} — {entry['license']}")
    lines = [
        "DivergenceSplitter Windows Distribution — Third-Party Notices",
        "",
        "License texts below were generated from the resolved release dependencies",
        "and runtime artifacts. Flutter and Dart dependency notices are provided by",
        "DivergenceSplitter/flutter_assets/NOTICES.Z, the authoritative source for",
        "Flutter, Flet Dart packages, serious_python, and other pub dependencies.",
    ]
    for text in sorted(groups):
        names = ", ".join(sorted(groups[text], key=str.casefold))
        lines.extend(["", "=" * 78, names, "=" * 78, "", text.rstrip()])
    return "\n".join(lines).rstrip() + "\n"


def staged_python_runtime(root: Path) -> Path:
    """Find the single Python runtime expanded by the Flet Windows build."""
    build_root = (
        root / "packages" / "divergencesplitter-ui" / "build" / "flutter" / "build"
    )
    candidates = sorted(
        path / "python"
        for path in build_root.glob("build_python_*")
        if (path / "python" / "python.exe").is_file()
        and (path / "python" / "LICENSE.txt").is_file()
    )
    if len(candidates) != 1:
        raise RuntimeError(
            f"Expected exactly one staged Flet Python runtime under {build_root}; "
            f"found {len(candidates)}"
        )
    return candidates[0]


def generate_from_distribution(
    *, root: Path, distribution_root: Path
) -> InventoryDocument:
    """Generate inventory from the final Windows distribution and staged runtime."""
    distributions = distribution_packages(distribution_root / "site-packages")
    return build_inventory(
        distributions,
        staged_python_runtime=staged_python_runtime(root),
        distribution_root=distribution_root,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=REPO_ROOT,
        help="repository root containing the Flet build",
    )
    parser.add_argument(
        "--distribution-root",
        type=Path,
        default=REPO_ROOT / "dist" / "windows" / "DivergenceSplitter",
        help="directory where inventory and license files are written",
    )
    args = parser.parse_args()
    inventory = generate_from_distribution(
        root=args.root, distribution_root=args.distribution_root
    )
    print(
        f"Generated license inventory for {len(inventory['packages'])} Python packages"
    )


if __name__ == "__main__":
    main()
