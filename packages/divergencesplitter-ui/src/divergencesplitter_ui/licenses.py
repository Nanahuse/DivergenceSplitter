"""Pure loading and presentation of the bundled license inventory.

The inventory is a static data file generated at release time from the
Windows dependency closure of ``divergencesplitter-ui``. It contains component
metadata and references license texts stored in the distribution's ``licenses``
directory. The screen never queries the network or enumerates installed
packages; it loads the inventory and its referenced files from the distribution.
"""

from __future__ import annotations

import importlib.resources
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import IO

SCHEMA_VERSION = 6
INVENTORY_RESOURCE = "license_inventory.json"


class LicenseInventoryError(ValueError):
    """The bundled license inventory is malformed.

    A broken inventory is a defect of the distribution itself, so it raises
    instead of degrading the license screen into an empty list. It is not a
    session runtime failure.
    """


@dataclass(frozen=True)
class LicenseEntry:
    """One packaged distribution in the release dependency closure."""

    name: str
    version: str
    license: str
    license_text: str


@dataclass(frozen=True)
class ApplicationLicense:
    """The license conveyed with the application itself."""

    name: str
    license: str
    license_text: str


@dataclass(frozen=True)
class AssetLicense:
    """A non-Python asset redistributed inside the application.

    Non-Python runtime components retain the runtime version when known.
    """

    name: str
    version: str | None
    license: str
    license_text: str


@dataclass(frozen=True)
class LicenseInventory:
    """The machine-readable license inventory bundled with the UI."""

    schema_version: int
    application: ApplicationLicense
    packages: tuple[LicenseEntry, ...]
    assets: tuple[AssetLicense, ...]


@dataclass(frozen=True)
class LicenseSection:
    """One expandable license block shown by the license screen."""

    title: str
    text: str


def _entry(
    index: int,
    package: object,
    fields: tuple[str, ...],
) -> tuple[str, ...]:
    if not isinstance(package, dict):
        raise LicenseInventoryError(
            f"license inventory package {index} is not an object"
        )
    values: dict[str, str] = {}
    for field in fields:
        value = package.get(field)
        if not isinstance(value, str) or not value:
            raise LicenseInventoryError(
                f"license inventory package {index} has an empty {field!r}"
            )
        values[field] = value
    return tuple(values[field] for field in fields)


def _license_root(package_root: Path) -> Path:
    """Find license files beside the Windows distribution or in the source tree."""
    candidates = [Path(sys.executable).resolve().parent / "licenses"]
    candidates.extend(
        candidate
        for ancestor in (package_root, *package_root.parents)
        for candidate in (ancestor / "licenses", ancestor / "tools" / "licenses")
    )
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise LicenseInventoryError("license files directory is missing")


def _read_license_file(relative_path: object, license_root: Path) -> str:
    if not isinstance(relative_path, str) or not relative_path:
        raise LicenseInventoryError("inventory entry has an empty 'license_file'")
    relative = Path(relative_path)
    root = license_root.resolve()
    if relative.is_absolute() or ".." in relative.parts:
        raise LicenseInventoryError(f"invalid license_file reference {relative_path!r}")
    target = (root / relative).resolve()
    if not target.is_relative_to(root):
        raise LicenseInventoryError(f"invalid license_file reference {relative_path!r}")
    try:
        return target.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise LicenseInventoryError(
            f"license file referenced by inventory is missing: {relative_path}"
        ) from error


def load_inventory(
    source: IO[str], *, license_root: Path | None = None
) -> LicenseInventory:
    """Decode one inventory JSON document and validate its schema.

    Entries reference license texts by relative file path. The loader reads
    those files and retains the text in the runtime model for presentation.
    """

    try:
        document = json.load(source)
    except json.JSONDecodeError as error:
        raise LicenseInventoryError(
            f"license inventory is not valid JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise LicenseInventoryError("license inventory must be a JSON object")
    if license_root is None:
        package_root = Path(str(importlib.resources.files("divergencesplitter_ui")))
        license_root = _license_root(package_root)
    schema_version = document.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise LicenseInventoryError(
            f"unsupported license inventory schema {schema_version!r}"
        )

    application_data = document.get("application")
    if not isinstance(application_data, dict):
        raise LicenseInventoryError(
            "license inventory must include an application section"
        )
    application_name, application_license = _entry(
        0, application_data, ("name", "license")
    )
    application = ApplicationLicense(
        application_name,
        application_license,
        _read_license_file(application_data.get("license_file"), license_root),
    )

    packages = document.get("packages")
    if not isinstance(packages, list):
        raise LicenseInventoryError("license inventory must list packages")

    entries: list[LicenseEntry] = []
    seen: set[str] = set()
    for index, package in enumerate(packages):
        name, version, license = _entry(
            index,
            package,
            ("name", "version", "license"),
        )
        license_text = _read_license_file(package.get("license_file"), license_root)
        if name in seen:
            raise LicenseInventoryError(
                f"license inventory lists package {name!r} twice"
            )
        seen.add(name)
        entries.append(LicenseEntry(name, version, license, license_text))

    assets_data = document.get("assets")
    if not isinstance(assets_data, list):
        raise LicenseInventoryError("license inventory must list assets")

    assets: list[AssetLicense] = []
    seen_assets: set[str] = set()
    for index, asset in enumerate(assets_data):
        name, license = _entry(index, asset, ("name", "license"))
        license_text = _read_license_file(asset.get("license_file"), license_root)
        version = asset.get("version")
        if version is not None and (not isinstance(version, str) or not version):
            raise LicenseInventoryError(
                f"license inventory package {index} has an empty 'version'"
            )
        if name in seen_assets:
            raise LicenseInventoryError(f"license inventory lists asset {name!r} twice")
        seen_assets.add(name)
        assets.append(AssetLicense(name, version, license, license_text))
    return LicenseInventory(schema_version, application, tuple(entries), tuple(assets))


def license_sections(inventory: LicenseInventory) -> tuple[LicenseSection, ...]:
    """Group the inventory into one expandable section per component.

    The application's own license comes first, followed by every third-party
    package in the bundled order.
    """

    sections = [
        LicenseSection(
            title=f"{inventory.application.name} — {inventory.application.license}",
            text=inventory.application.license_text,
        )
    ]
    for entry in inventory.packages:
        sections.append(
            LicenseSection(
                title=f"{entry.name} {entry.version} — {entry.license}",
                text=entry.license_text,
            )
        )
    for asset in inventory.assets:
        sections.append(
            LicenseSection(
                title=(
                    f"{asset.name} {asset.version} — {asset.license}"
                    if asset.version
                    else f"{asset.name} — {asset.license}"
                ),
                text=asset.license_text,
            )
        )
    return tuple(sections)


def bundled_inventory() -> LicenseInventory:
    """Load the inventory shipped with the app or next to this package.

    The Windows distribution keeps its data files beside the executable.
    Development and installed-package runs use ``importlib.resources``.
    """

    distribution_root = Path(sys.executable).resolve().parent
    distribution_inventory = distribution_root / INVENTORY_RESOURCE
    if distribution_inventory.is_file():
        with distribution_inventory.open("r", encoding="utf-8") as source:
            return load_inventory(source, license_root=distribution_root / "licenses")

    resource = importlib.resources.files("divergencesplitter_ui").joinpath(
        INVENTORY_RESOURCE
    )
    with resource.open("r", encoding="utf-8") as source:
        return load_inventory(source)
