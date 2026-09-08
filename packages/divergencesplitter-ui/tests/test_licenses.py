from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from divergencesplitter_ui.licenses import (
    LicenseEntry,
    LicenseInventory,
    LicenseInventoryError,
    license_lines,
    load_inventory,
)


def document(packages: list[dict[str, Any]]) -> dict[str, Any]:
    return {"schema_version": 1, "packages": packages}


def load(packages: list[dict[str, Any]]) -> LicenseInventory:
    return load_inventory(StringIO(json.dumps(document(packages))))


class TestLoadInventory:
    def test_decodes_entries_with_name_version_license(self) -> None:
        inventory = load(
            [
                {
                    "name": "divergencesplitter-ui",
                    "version": "0.1.0",
                    "license": "GPL-3.0-only",
                },
                {"name": "numpy", "version": "2.5.2", "license": "BSD-3-Clause"},
            ]
        )

        assert inventory == LicenseInventory(
            schema_version=1,
            packages=(
                LicenseEntry("divergencesplitter-ui", "0.1.0", "GPL-3.0-only"),
                LicenseEntry("numpy", "2.5.2", "BSD-3-Clause"),
            ),
        )

    def test_preserves_document_order(self) -> None:
        inventory = load(
            [
                {"name": "b", "version": "1", "license": "MIT"},
                {"name": "a", "version": "2", "license": "MIT"},
            ]
        )

        assert [entry.name for entry in inventory.packages] == ["b", "a"]

    @pytest.mark.parametrize(
        "package",
        [
            {"version": "1", "license": "MIT"},
            {"name": "x", "license": "MIT"},
            {"name": "x", "version": "1"},
        ],
    )
    def test_missing_required_field_raises(self, package: dict[str, Any]) -> None:
        with pytest.raises(LicenseInventoryError):
            load([package])

    @pytest.mark.parametrize(
        "package",
        [
            {"name": "", "version": "1", "license": "MIT"},
            {"name": "x", "version": "", "license": "MIT"},
            {"name": "x", "version": "1", "license": ""},
        ],
    )
    def test_empty_required_field_raises(self, package: dict[str, Any]) -> None:
        with pytest.raises(LicenseInventoryError):
            load([package])

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO("{not json"))

    def test_root_must_be_an_object(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO("[]"))

    def test_unsupported_schema_version_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO(json.dumps({"schema_version": 2, "packages": []})))

    def test_missing_packages_list_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO(json.dumps({"schema_version": 1})))

    def test_duplicate_package_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load(
                [
                    {"name": "x", "version": "1", "license": "MIT"},
                    {"name": "x", "version": "1", "license": "MIT"},
                ]
            )


class TestLicenseLines:
    def test_formats_name_version_license_with_separator(self) -> None:
        inventory = LicenseInventory(
            schema_version=1,
            packages=(LicenseEntry("a", "1.0", "MIT"),),
        )

        assert license_lines(inventory) == ("a", "1.0", "MIT", "")

    def test_every_package_contributes_a_separator(self) -> None:
        inventory = load(
            [
                {"name": "a", "version": "1", "license": "MIT"},
                {"name": "b", "version": "2", "license": "GPL-3.0-only"},
            ]
        )

        assert license_lines(inventory) == (
            "a",
            "1",
            "MIT",
            "",
            "b",
            "2",
            "GPL-3.0-only",
            "",
        )
