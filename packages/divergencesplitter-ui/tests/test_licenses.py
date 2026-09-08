from __future__ import annotations

import json
from io import StringIO
from typing import Any

import pytest
from divergencesplitter_ui.licenses import (
    ApplicationLicense,
    LicenseEntry,
    LicenseInventory,
    LicenseInventoryError,
    LicenseSection,
    license_sections,
    load_inventory,
)


def document(
    packages: list[dict[str, Any]],
    *,
    application: dict[str, Any] | None = None,
    schema_version: int = 2,
) -> dict[str, Any]:
    return {
        "schema_version": schema_version,
        "application": application
        or {
            "name": "DivergenceSplitter",
            "license": "GPL-3.0-only",
            "license_text": "GPL text",
        },
        "packages": packages,
    }


def package(**fields: Any) -> dict[str, Any]:
    defaults = {
        "name": "numpy",
        "version": "2.5.2",
        "license": "BSD-3-Clause",
        "license_text": "full BSD text",
    }
    defaults.update(fields)
    return defaults


def package_without(field: str) -> dict[str, Any]:
    data = package()
    del data[field]
    return data


def load(
    packages: list[dict[str, Any]],
    *,
    application: dict[str, Any] | None = None,
    schema_version: int = 2,
) -> LicenseInventory:
    return load_inventory(
        StringIO(
            json.dumps(
                document(
                    packages, schema_version=schema_version, application=application
                )
            )
        )
    )


class TestLoadInventory:
    def test_decodes_application_and_entries(self) -> None:
        inventory = load(
            [package(), package(name="pyyaml", license="MIT")],
        )

        assert inventory == LicenseInventory(
            schema_version=2,
            application=ApplicationLicense(
                "DivergenceSplitter",
                "GPL-3.0-only",
                "GPL text",
            ),
            packages=(
                LicenseEntry("numpy", "2.5.2", "BSD-3-Clause", "full BSD text"),
                LicenseEntry("pyyaml", "2.5.2", "MIT", "full BSD text"),
            ),
        )

    def test_preserves_document_order(self) -> None:
        inventory = load([package(name="b"), package(name="a")])

        assert [entry.name for entry in inventory.packages] == ["b", "a"]

    @pytest.mark.parametrize(
        "removed",
        ["name", "version", "license", "license_text"],
    )
    def test_missing_required_field_raises(self, removed: str) -> None:
        with pytest.raises(LicenseInventoryError):
            load([package_without(removed)])

    @pytest.mark.parametrize(
        "package_fields",
        [
            {"name": ""},
            {"version": ""},
            {"license": ""},
            {"license_text": ""},
        ],
    )
    def test_empty_required_field_raises(self, package_fields: dict[str, Any]) -> None:
        with pytest.raises(LicenseInventoryError):
            load([package(**package_fields)])

    def test_invalid_json_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO("{not json"))

    def test_root_must_be_an_object(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO("[]"))

    def test_unsupported_schema_version_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO(json.dumps(document([], schema_version=1))))

    def test_missing_packages_list_raises(self) -> None:
        bad = document([])
        bad["packages"] = "x"
        with pytest.raises(LicenseInventoryError):
            load_inventory(StringIO(json.dumps(bad)))

    def test_duplicate_package_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load([package(), package()])

    def test_missing_application_section_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load_inventory(
                StringIO(
                    json.dumps(
                        {
                            "schema_version": 2,
                            "packages": [],
                        }
                    )
                )
            )

    def test_empty_application_field_raises(self) -> None:
        with pytest.raises(LicenseInventoryError):
            load(
                [],
                application={
                    "name": "DivergenceSplitter",
                    "license": "GPL-3.0-only",
                    "license_text": "",
                },
            )


class TestLicenseSections:
    def make_inventory(self) -> LicenseInventory:
        return LicenseInventory(
            schema_version=2,
            application=ApplicationLicense(
                "DivergenceSplitter",
                "GPL-3.0-only",
                "the GPL text",
            ),
            packages=(LicenseEntry("numpy", "2.5.2", "BSD-3-Clause", "the BSD text"),),
        )

    def test_application_section_comes_first(self) -> None:
        sections = license_sections(self.make_inventory())

        assert sections[0] == LicenseSection(
            title="DivergenceSplitter — GPL-3.0-only",
            text="the GPL text",
        )

    def test_every_package_is_a_section(self) -> None:
        sections = license_sections(self.make_inventory())

        assert sections[1] == LicenseSection(
            title="numpy 2.5.2 — BSD-3-Clause",
            text="the BSD text",
        )
