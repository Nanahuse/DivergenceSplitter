"""Pure loading and presentation of the bundled license inventory.

The inventory is a static data file generated at release time from the
Windows dependency closure of ``divergencesplitter-ui``. It bundles both the
license identifiers and the full license texts redistributed inside the
executable, plus the application's own GPL-3.0 text. The screen never queries
the network and never enumerates the installed environment; it reads exactly
this file through ``importlib.resources``, which resolves identically from a
source checkout and from a PyInstaller bundle.
"""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from typing import IO

SCHEMA_VERSION = 3
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

    Unlike ``LicenseEntry`` it has no package version because it is not a
    distribution; the bundled Noto Sans JP font is conveyed this way.
    """

    name: str
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


def load_inventory(source: IO[str]) -> LicenseInventory:
    """Decode one inventory JSON document and validate its schema.

    Every package must carry a name, version, license, and the full license
    text; the application section must carry its conveyed license text. The
    generator writes the file already sorted by normalized name; this loader
    preserves that order and only rejects structural mistakes.
    """

    try:
        document = json.load(source)
    except json.JSONDecodeError as error:
        raise LicenseInventoryError(
            f"license inventory is not valid JSON: {error}"
        ) from error
    if not isinstance(document, dict):
        raise LicenseInventoryError("license inventory must be a JSON object")
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
    application = ApplicationLicense(
        *_entry(0, application_data, ("name", "license", "license_text"))
    )

    packages = document.get("packages")
    if not isinstance(packages, list):
        raise LicenseInventoryError("license inventory must list packages")

    entries: list[LicenseEntry] = []
    seen: set[str] = set()
    for index, package in enumerate(packages):
        name, version, license, license_text = _entry(
            index,
            package,
            ("name", "version", "license", "license_text"),
        )
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
        name, license, license_text = _entry(
            index, asset, ("name", "license", "license_text")
        )
        if name in seen_assets:
            raise LicenseInventoryError(f"license inventory lists asset {name!r} twice")
        seen_assets.add(name)
        assets.append(AssetLicense(name, license, license_text))
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
                title=f"{asset.name} — {asset.license}",
                text=asset.license_text,
            )
        )
    return tuple(sections)


def bundled_inventory() -> LicenseInventory:
    """Load the inventory shipped next to this package.

    ``importlib.resources`` reads the data file from the source tree, from an
    installed wheel, and from a PyInstaller bundle without any path special
    cases in application code.
    """

    resource = importlib.resources.files("divergencesplitter_ui").joinpath(
        INVENTORY_RESOURCE
    )
    with resource.open("r", encoding="utf-8") as source:
        return load_inventory(source)
