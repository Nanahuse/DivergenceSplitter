"""Pure loading and presentation of the bundled license inventory.

The inventory is a static data file generated at release time from the
Windows dependency closure of ``divergencesplitter-ui``. The screen never
queries the network and never enumerates the installed environment; it reads
exactly this file through ``importlib.resources``, which resolves identically
from a source checkout and from a PyInstaller bundle.
"""

from __future__ import annotations

import importlib.resources
import json
from dataclasses import dataclass
from typing import IO

SCHEMA_VERSION = 1
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


@dataclass(frozen=True)
class LicenseInventory:
    """The machine-readable license inventory bundled with the UI."""

    schema_version: int
    packages: tuple[LicenseEntry, ...]


def load_inventory(source: IO[str]) -> LicenseInventory:
    """Decode one inventory JSON document and validate its schema.

    Entries are required to carry a package name, version, and license. The
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
    packages = document.get("packages")
    if not isinstance(packages, list):
        raise LicenseInventoryError("license inventory must list packages")

    entries: list[LicenseEntry] = []
    seen: set[str] = set()
    for index, package in enumerate(packages):
        if not isinstance(package, dict):
            raise LicenseInventoryError(
                f"license inventory package {index} is not an object"
            )
        try:
            entry = LicenseEntry(
                name=package["name"],
                version=package["version"],
                license=package["license"],
            )
        except KeyError as error:
            raise LicenseInventoryError(
                f"license inventory package {index} is missing {error.args[0]!r}"
            ) from error
        if not entry.name or not entry.version or not entry.license:
            raise LicenseInventoryError(
                f"license inventory package {index} has an empty required field"
            )
        if entry.name in seen:
            raise LicenseInventoryError(
                f"license inventory lists package {entry.name!r} twice"
            )
        seen.add(entry.name)
        entries.append(entry)
    return LicenseInventory(schema_version, tuple(entries))


def license_lines(inventory: LicenseInventory) -> tuple[str, ...]:
    """Format every package into display lines, one per displayed row.

    Each package contributes its name, version, license, and a blank
    separator so the list stays legible without a table component.
    """

    lines: list[str] = []
    for entry in inventory.packages:
        lines.append(entry.name)
        lines.append(entry.version)
        lines.append(entry.license)
        lines.append("")
    return tuple(lines)


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
